"""Copy public fund offering documents that were uploaded to households into the shared fund library.

Dry run by default; pass --apply to write. Nothing is deleted or modified: household documents, their pages,
terms and approvals stay exactly as they are. For each firm, every distinct file (by SHA-256) of a fund-type
category becomes one library document under a library fund:

- the fund gets a provisional name from the file name and `metadata_status = needs_review` (a reviewer
  must confirm the name, issuer and identifiers); its type comes from the asset type of the document's terms;
- the PDF is copied to library storage (the household copy is untouched) and its SHA-256 re-verified;
- page text and terms are copied; every copied term is `needs_review`, because household approvals were
  not made by the firm's library reviewers. Each copy records its source in a revision note;
- holdings are NOT linked automatically; candidate holdings are listed for the advisor to link.

Demo fixtures (synthetic documents) are skipped unless --include-demo. Re-running is safe: files already in
the firm's library are skipped.

    cd backend && ../.venv/bin/python scripts/backfill_fund_library.py [--apply] [--include-demo]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.audit import audit  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app.models import (  # noqa: E402
    FUND_DOC_CATEGORIES,
    Asset,
    ConstraintRevision,
    Document,
    DocumentPage,
    ExtractedConstraint,
    Fund,
    Household,
)
from app.services.documents import storage_path_for  # noqa: E402
from app.storage import get_storage  # noqa: E402

ASSET_TO_FUND_TYPE = {"non_traded_reit": "non_traded_reit", "interval_fund": "interval_fund",
                      "private_fund": "private_fund"}
FUND_TYPE_TO_HOLDING = {"non_traded_reit": "non_traded_reit", "interval_fund": "interval_fund",
                        "private_fund": "private_fund_commitment", "other": "other"}
COPIED_TERM_FIELDS = (
    "extraction_key", "constraint_type", "asset_key", "description", "value", "lower_bound", "upper_bound",
    "original_value", "unit", "timing", "conditions", "pdf_page", "printed_page", "document_section",
    "evidence_quote", "quote_verified", "corroborating_pages", "interpretation", "value_kind", "exceptions",
    "discretion", "effective_period", "ambiguous", "validation_issues", "confidence", "extraction_method",
    "provider", "model")


def provisional_name(doc: Document) -> str:
    stem = Path(doc.original_filename).stem.replace("_", " ").replace("-", " ").strip()
    return f"{stem[:180]} (backfilled - confirm name)"


def fund_type_for(db: Session, doc: Document) -> str:
    kinds = Counter(db.scalars(select(ExtractedConstraint.asset_key).where(
        ExtractedConstraint.document_id == doc.id)).all())
    for asset_key, _ in kinds.most_common():
        if asset_key in ASSET_TO_FUND_TYPE:
            return ASSET_TO_FUND_TYPE[asset_key]
    return "interval_fund" if doc.category == "interval_fund" else "other"


def candidates(db: Session, include_demo: bool) -> dict[tuple, list[tuple[Document, Household]]]:
    stmt = (select(Document, Household).join(Household, Household.id == Document.household_id)
            .where(Document.household_id.is_not(None), Document.category.in_(FUND_DOC_CATEGORIES),
                   Document.status == "extracted", Document.deleted_at.is_(None), Document.sha256.is_not(None),
                   Document.storage_path.is_not(None))
            .order_by(Document.created_at))
    if not include_demo:
        stmt = stmt.where(Document.is_demo_fixture.is_(False))
    groups: dict[tuple, list[tuple[Document, Household]]] = defaultdict(list)
    for doc, hh in db.execute(stmt).all():
        groups[(hh.firm_id, doc.sha256)].append((doc, hh))
    return groups


def backfill(db: Session, apply: bool, include_demo: bool) -> list[str]:
    storage = get_storage()
    report: list[str] = []
    for (firm_id, sha), docs in candidates(db, include_demo).items():
        src, _ = docs[0]
        existing = db.scalar(select(Document).join(Fund, Fund.id == Document.fund_id).where(
            Fund.firm_id == firm_id, Document.sha256 == sha, Document.deleted_at.is_(None)))
        households = sorted({hh.name for _, hh in docs})
        if existing is not None:
            report.append(f"SKIP  {src.original_filename}: already in firm {firm_id} library (document {existing.id})")
            continue
        ftype = fund_type_for(db, src)
        name = provisional_name(src)
        n_terms = db.scalar(select(func.count()).select_from(ExtractedConstraint)
                            .where(ExtractedConstraint.document_id == src.id)) or 0
        holding_kind = FUND_TYPE_TO_HOLDING[ftype]
        holdings = db.execute(select(Asset.name, Household.name).join(Household, Household.id == Asset.household_id)
                              .where(Asset.household_id.in_([hh.id for _, hh in docs]), Asset.kind == holding_kind,
                                     Asset.fund_id.is_(None))).all()
        report.append(f"{'COPY' if apply else 'PLAN'}  {src.original_filename} -> fund '{name}' ({ftype}) in firm "
                      f"{firm_id}: {src.page_count} pages, {n_terms} terms as needs_review; "
                      f"uploaded in {len(docs)} household(s): {', '.join(households)}")
        for asset_name, hh_name in holdings:
            report.append(f"      candidate holding to link manually: '{asset_name}' in '{hh_name}'")
        if not apply:
            continue

        fund = db.scalar(select(Fund).where(Fund.firm_id == firm_id, func.lower(Fund.name) == name.lower(),
                                            Fund.share_class.is_(None)))
        if fund is None:
            fund = Fund(firm_id=firm_id, name=name, fund_type=ftype, metadata_status="needs_review",
                        created_by=src.uploaded_by,
                        description=f"Created by the library backfill from household document {src.id}. "
                                    "Confirm the fund name, issuer and identifiers.")
            db.add(fund)
            db.flush()
        data = storage.get(src.storage_path)  # type: ignore[arg-type]
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit(f"Stored bytes of document {src.id} do not match its SHA-256; aborting (nothing written "
                             "for this file).")
        doc = Document(fund_id=fund.id, uploaded_by=src.uploaded_by, category=src.category,
                       original_filename=src.original_filename, safe_filename=src.safe_filename,
                       storage_bucket=src.storage_bucket, content_type=src.content_type, size_bytes=src.size_bytes,
                       sha256=sha, page_count=src.page_count, pages_without_text=src.pages_without_text,
                       ocr_pages=src.ocr_pages, status="extracted")
        db.add(doc)
        db.flush()
        doc.storage_path = storage_path_for(doc)
        storage.put(doc.storage_path, data, src.content_type)
        for p in db.scalars(select(DocumentPage).where(DocumentPage.document_id == src.id)):
            db.add(DocumentPage(document_id=doc.id, fund_id=fund.id, pdf_page=p.pdf_page,
                                printed_page=p.printed_page, section=p.section, text=p.text, ocr=p.ocr))
        for c in db.scalars(select(ExtractedConstraint).where(ExtractedConstraint.document_id == src.id)):
            copy = ExtractedConstraint(fund_id=fund.id, document_id=doc.id, revision=1, review_status="needs_review",
                                       source_type="source_backed" if c.source_type == "user_confirmed"
                                       else c.source_type,
                                       **{f: getattr(c, f) for f in COPIED_TERM_FIELDS})
            db.add(copy)
            db.flush()
            db.add(ConstraintRevision(
                constraint_id=copy.id, fund_id=fund.id, revision=1, changed_by=None,
                change={"backfilled_from": {"from": None, "to": str(c.id)}},
                snapshot={"review_status": "needs_review", "source_constraint": str(c.id)},
                note=f"Backfilled from household document {src.id}; household review status was "
                     f"'{c.review_status}'. Requires library review."))
        audit(db, actor_id=None, action="fund.backfilled", entity_type="document", entity_id=doc.id,
              firm_id=firm_id, fund_id=fund.id,
              details={"source_document": str(src.id), "households": len(docs), "terms": n_terms})
        db.commit()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--include-demo", action="store_true", help="also copy synthetic demo fixtures")
    args = ap.parse_args()
    with get_sessionmaker()() as db:
        lines = backfill(db, args.apply, args.include_demo)
        if not args.apply:
            db.rollback()
    print("\n".join(lines) if lines else "Nothing to backfill.")
    if not args.apply and lines:
        print("\nDry run only. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
