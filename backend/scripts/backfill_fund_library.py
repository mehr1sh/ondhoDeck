"""Copy public fund offering documents that were uploaded to households into the shared fund library.

Dry run by default; pass --apply to write. New uploads are shared automatically once the same file is in
several households of a firm (app/services/library_sharing.py, which also describes exactly what is copied);
this script applies the same copy to files uploaded earlier. Nothing is deleted or modified: household
documents, their pages, terms and approvals stay exactly as they are. For each firm, every distinct file
(by SHA-256) of a fund-type category in at least --min-households households (default 1) becomes one library
document under a library fund with a provisional name; every copied term is `needs_review`. Holdings are NOT
linked automatically; candidate holdings are listed for the advisor to link.

Demo fixtures (synthetic documents) are skipped unless --include-demo. Re-running is safe: files already in
the firm's library are skipped.

    cd backend && .venv/bin/python scripts/backfill_fund_library.py [--apply] [--include-demo] [--min-households N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import get_sessionmaker  # noqa: E402
from app.models import ExtractedConstraint  # noqa: E402
from app.services.library_sharing import (  # noqa: E402
    LibraryCopyError,
    candidates,
    copy_to_library,
    fund_type_for,
    library_document,
    link_candidates,
    provisional_name,
)
from app.storage import get_storage  # noqa: E402


def backfill(db: Session, apply: bool, include_demo: bool, min_households: int = 1) -> list[str]:
    storage = get_storage()
    report: list[str] = []
    for (firm_id, sha), docs in candidates(db, include_demo=include_demo).items():
        src, _ = docs[0]
        households = sorted({hh.name for _, hh in docs})
        n_households = len({hh.id for _, hh in docs})
        if n_households < min_households:
            continue
        existing = library_document(db, firm_id, sha)
        if existing is not None:
            report.append(f"SKIP  {src.original_filename}: already in firm {firm_id} library (document {existing.id})")
            continue
        ftype = fund_type_for(db, src)
        n_terms = db.scalar(select(func.count()).select_from(ExtractedConstraint)
                            .where(ExtractedConstraint.document_id == src.id)) or 0
        report.append(f"{'COPY' if apply else 'PLAN'}  {src.original_filename} -> fund '{provisional_name(src)}' "
                      f"({ftype}) in firm {firm_id}: {src.page_count} pages, {n_terms} terms as needs_review; "
                      f"uploaded in {n_households} household(s): {', '.join(households)}")
        for asset_name, hh_name in link_candidates(db, docs, ftype):
            report.append(f"      candidate holding to link manually: '{asset_name}' in '{hh_name}'")
        if not apply:
            continue
        try:
            copy_to_library(db, storage, firm_id, sha, docs, origin="backfill")
        except LibraryCopyError as exc:
            raise SystemExit(f"{exc} Aborting.") from None
        db.commit()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--include-demo", action="store_true", help="also copy synthetic demo fixtures")
    ap.add_argument("--min-households", type=int, default=1,
                    help="only copy files uploaded to at least this many households of a firm (default 1)")
    args = ap.parse_args()
    with get_sessionmaker()() as db:
        lines = backfill(db, args.apply, args.include_demo, args.min_households)
        if not args.apply:
            db.rollback()
    print("\n".join(lines) if lines else "Nothing to backfill.")
    if not args.apply and lines:
        print("\nDry run only. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
