"""Copy public fund offering documents uploaded to households into their firm's shared fund library.

Runs automatically after a household document is processed: once the same file (by SHA-256) has been uploaded
to MIN_HOUSEHOLDS or more households of a firm, it becomes one library document under a library fund. The
backfill script (scripts/backfill_fund_library.py) uses the same copy for files already uploaded.

Only fund offering categories (FUND_DOC_CATEGORIES) are eligible; private agreements never leave the household.
Nothing is deleted or modified: household documents, their pages, terms and approvals stay exactly as they are.

- the fund gets a provisional name from the file name and `metadata_status = needs_review` (a reviewer
  must confirm the name, issuer and identifiers); its type comes from the asset type of the document's terms;
- the PDF is copied to library storage (the household copy is untouched) and its SHA-256 re-verified;
- page text and terms are copied; every copied term is `needs_review`, because household approvals were
  not made by the firm's library reviewers. Each copy records its source in a revision note;
- holdings are NOT linked automatically (see link_candidates).
"""
from __future__ import annotations

import hashlib
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import session_scope
from ..models import (
    FUND_DOC_CATEGORIES,
    Asset,
    ConstraintRevision,
    Document,
    DocumentPage,
    ExtractedConstraint,
    Fund,
    Household,
)
from ..storage import Storage, get_storage
from .documents import storage_path_for

MIN_HOUSEHOLDS = 2  # the same file in this many households of a firm puts it in the firm's library

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

Origin = Literal["shared", "backfill"]
Group = list[tuple[Document, Household]]


class LibraryCopyError(RuntimeError):
    pass


def provisional_name(doc: Document) -> str:
    stem = Path(doc.original_filename).stem.replace("_", " ").replace("-", " ").strip()
    return f"{stem[:185]} (confirm name)"


def fund_type_for(db: Session, doc: Document) -> str:
    kinds = Counter(db.scalars(select(ExtractedConstraint.asset_key).where(
        ExtractedConstraint.document_id == doc.id)).all())
    for asset_key, _ in kinds.most_common():
        if asset_key in ASSET_TO_FUND_TYPE:
            return ASSET_TO_FUND_TYPE[asset_key]
    return "interval_fund" if doc.category == "interval_fund" else "other"


def candidates(db: Session, *, include_demo: bool, firm_id: Optional[uuid.UUID] = None,
               sha256: Optional[str] = None) -> dict[tuple[uuid.UUID, str], Group]:
    """Processed household fund documents grouped by (firm, file), oldest upload first."""
    stmt = (select(Document, Household).join(Household, Household.id == Document.household_id)
            .where(Document.household_id.is_not(None), Document.category.in_(FUND_DOC_CATEGORIES),
                   Document.status == "extracted", Document.deleted_at.is_(None), Document.sha256.is_not(None),
                   Document.storage_path.is_not(None), Household.firm_id.is_not(None))
            .order_by(Document.created_at))
    if not include_demo:
        stmt = stmt.where(Document.is_demo_fixture.is_(False))
    if firm_id is not None:
        stmt = stmt.where(Household.firm_id == firm_id)
    if sha256 is not None:
        stmt = stmt.where(Document.sha256 == sha256)
    groups: dict[tuple[uuid.UUID, str], Group] = defaultdict(list)
    for doc, hh in db.execute(stmt).all():
        groups[(hh.firm_id, doc.sha256)].append((doc, hh))  # type: ignore[index]
    return groups


def library_document(db: Session, firm_id: uuid.UUID, sha256: str) -> Optional[Document]:
    return db.scalar(select(Document).join(Fund, Fund.id == Document.fund_id).where(
        Fund.firm_id == firm_id, Document.sha256 == sha256, Document.deleted_at.is_(None)))


def link_candidates(db: Session, docs: Group, fund_type: str) -> list[tuple[str, str]]:
    """(holding name, household name) of unlinked holdings that could be linked to the library fund."""
    return [(a, h) for a, h in db.execute(
        select(Asset.name, Household.name).join(Household, Household.id == Asset.household_id)
        .where(Asset.household_id.in_([hh.id for _, hh in docs]), Asset.kind == FUND_TYPE_TO_HOLDING[fund_type],
               Asset.fund_id.is_(None))).all()]


def copy_to_library(db: Session, storage: Storage, firm_id: uuid.UUID, sha256: str, docs: Group, *,
                    origin: Origin) -> Fund:
    """Copy the oldest upload of a file into the firm's library. Flushes; the caller commits."""
    src = docs[0][0]
    households = len({hh.id for _, hh in docs})
    name = provisional_name(src)
    fund = db.scalar(select(Fund).where(Fund.firm_id == firm_id, func.lower(Fund.name) == name.lower(),
                                        Fund.share_class.is_(None)))
    if fund is None:
        how = ("Added automatically because the same file was uploaded to "
               f"{households} households" if origin == "shared" else "Created by the library backfill")
        fund = Fund(firm_id=firm_id, name=name, fund_type=fund_type_for(db, src), metadata_status="needs_review",
                    created_by=src.uploaded_by,
                    description=f"{how} (from household document {src.id}). "
                                "Confirm the fund name, issuer and identifiers.")
        db.add(fund)
        db.flush()
    data = storage.get(src.storage_path)  # type: ignore[arg-type]
    if hashlib.sha256(data).hexdigest() != sha256:
        raise LibraryCopyError(f"Stored bytes of document {src.id} do not match its SHA-256; nothing was copied.")
    doc = Document(fund_id=fund.id, uploaded_by=src.uploaded_by, category=src.category,
                   original_filename=src.original_filename, safe_filename=src.safe_filename,
                   storage_bucket=src.storage_bucket, content_type=src.content_type, size_bytes=src.size_bytes,
                   sha256=sha256, page_count=src.page_count, pages_without_text=src.pages_without_text,
                   ocr_pages=src.ocr_pages, is_demo_fixture=src.is_demo_fixture, status="extracted")
    db.add(doc)
    db.flush()
    doc.storage_path = storage_path_for(doc)
    storage.put(doc.storage_path, data, src.content_type)
    for p in db.scalars(select(DocumentPage).where(DocumentPage.document_id == src.id)):
        db.add(DocumentPage(document_id=doc.id, fund_id=fund.id, pdf_page=p.pdf_page,
                            printed_page=p.printed_page, section=p.section, text=p.text, ocr=p.ocr))
    n_terms = 0
    copied_from = "Shared from" if origin == "shared" else "Backfilled from"
    for c in db.scalars(select(ExtractedConstraint).where(ExtractedConstraint.document_id == src.id)):
        copy = ExtractedConstraint(fund_id=fund.id, document_id=doc.id, revision=1, review_status="needs_review",
                                   source_type="source_backed" if c.source_type == "user_confirmed"
                                   else c.source_type,
                                   **{f: getattr(c, f) for f in COPIED_TERM_FIELDS})
        db.add(copy)
        db.flush()
        db.add(ConstraintRevision(
            constraint_id=copy.id, fund_id=fund.id, revision=1, changed_by=None,
            change={"backfilled_from" if origin == "backfill" else "shared_from": {"from": None, "to": str(c.id)}},
            snapshot={"review_status": "needs_review", "source_constraint": str(c.id)},
            note=f"{copied_from} household document {src.id}; household review status was "
                 f"'{c.review_status}'. Requires library review."))
        n_terms += 1
    audit(db, actor_id=None, action="fund.backfilled" if origin == "backfill" else "fund.shared_from_households",
          entity_type="document", entity_id=doc.id, firm_id=firm_id, fund_id=fund.id,
          details={"source_document": str(src.id), "households": households, "terms": n_terms})
    return fund


def share_if_repeated(document_id: uuid.UUID, storage: Optional[Storage] = None) -> Optional[uuid.UUID]:
    """After a household document is processed, copy its file into the firm's library once it is in
    MIN_HOUSEHOLDS households of the firm. Returns the library fund id when a copy was made."""
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None or doc.household_id is None or doc.category not in FUND_DOC_CATEGORIES or not doc.sha256:
            return None
        firm_id = db.scalar(select(Household.firm_id).where(Household.id == doc.household_id))
        if firm_id is None:
            return None
        # Two households finishing the same file at once must not both copy it.
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"fund-library:{firm_id}:{doc.sha256}"))))
        if library_document(db, firm_id, doc.sha256) is not None:
            return None
        docs = candidates(db, include_demo=True, firm_id=firm_id, sha256=doc.sha256).get((firm_id, doc.sha256), [])
        if len({hh.id for _, hh in docs}) < MIN_HOUSEHOLDS:
            return None
        return copy_to_library(db, storage or get_storage(), firm_id, doc.sha256, docs, origin="shared").id
