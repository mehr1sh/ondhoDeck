"""Shared fund library: canonical fund records, their public offering documents and reviewed terms.

Readable by every member of the fund's firm. Advisors may add funds and upload documents; reviewers/admins
edit metadata, set document effective dates and supersession, and review terms. Household data never appears
here except holdings in households the caller is already a member of.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api_schemas import (
    AuditOut,
    DocumentInitiateOut,
    DocumentOut,
    FundDetail,
    FundDocumentInitiate,
    FundDocumentUpdate,
    FundHoldingOut,
    FundIn,
    FundOut,
    FundTermsOut,
    FundUpdate,
    Page,
)
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import firm_role, require_firm, require_fund, require_owned
from ..config import Settings, get_settings
from ..db import get_db
from ..errors import ApiError
from ..models import Asset, AuditEvent, Document, ExtractedConstraint, FirmMember, Fund, Household, HouseholdMember
from ..services.firms import default_firm_id
from ..services.term_resolution import in_force
from .common import Pagination, apply_updates, paginate
from .constraints import constraint_out
from .documents import document_out, initiate_document

router = APIRouter(tags=["fund library"])


def _counts(db: Session, fund_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    out: dict[uuid.UUID, dict[str, int]] = {f: {"document_count": 0, "approved_term_count": 0,
                                                "pending_term_count": 0} for f in fund_ids}
    if not fund_ids:
        return out
    for fid, n in db.execute(select(Document.fund_id, func.count()).where(
            Document.fund_id.in_(fund_ids), Document.status != "deleted").group_by(Document.fund_id)):
        out[fid]["document_count"] = n  # type: ignore[index]  # filtered to non-null fund ids
    for fid, status, n in db.execute(
            select(ExtractedConstraint.fund_id, ExtractedConstraint.review_status, func.count())
            .join(Document, Document.id == ExtractedConstraint.document_id)
            .where(ExtractedConstraint.fund_id.in_(fund_ids), Document.status != "deleted")
            .group_by(ExtractedConstraint.fund_id, ExtractedConstraint.review_status)):
        key = "approved_term_count" if status in ("confirmed", "edited") else (
            "pending_term_count" if status == "needs_review" else None)
        if key and fid is not None:
            out[fid][key] += n
    return out


def _fund_out(f: Fund, counts: dict[str, int]) -> FundOut:
    return FundOut.model_validate(f).model_copy(update=counts)


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/funds", response_model=Page[FundOut])
def search_funds(q: Optional[str] = Query(None, max_length=120), fund_type: Optional[str] = None,
                 firm_id: Optional[uuid.UUID] = None, include_archived: bool = False, p: Pagination = Depends(),
                 user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Search funds in the caller's firms by name, issuer, ticker, SEC CIK or alias (case-insensitive)."""
    firms = select(FirmMember.firm_id).where(FirmMember.user_id == user.id)
    stmt = select(Fund).where(Fund.firm_id.in_(firms))
    if firm_id is not None:
        stmt = stmt.where(Fund.firm_id == firm_id)
    if fund_type:
        stmt = stmt.where(Fund.fund_type == fund_type)
    if not include_archived:
        stmt = stmt.where(Fund.status == "active")
    if q and q.strip():
        pat = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(or_(Fund.name.ilike(pat, escape="\\"), Fund.issuer.ilike(pat, escape="\\"),
                              Fund.ticker.ilike(pat, escape="\\"), Fund.sec_cik.ilike(pat, escape="\\"),
                              cast(Fund.aliases, String).ilike(pat, escape="\\")))
    rows, total = paginate(db, stmt.order_by(func.lower(Fund.name), Fund.share_class), p)
    funds = [r[0] for r in rows]
    counts = _counts(db, [f.id for f in funds])
    return Page(items=[_fund_out(f, counts[f.id]) for f in funds], total=total, limit=p.limit, offset=p.offset)


@router.post("/funds", response_model=FundOut, status_code=201)
def create_fund(body: FundIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    firm_id = require_firm(db, user, body.firm_id).id if body.firm_id else default_firm_id(db, user.id)
    fund = Fund(firm_id=firm_id, created_by=user.id, **body.model_dump(exclude={"firm_id"}))
    if fund.ticker:
        fund.ticker = fund.ticker.upper()
    db.add(fund)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "conflict", "This firm's library already has a fund with that name and share class. "
                                        "Search for it instead of creating a duplicate.") from None
    audit(db, actor_id=user.id, action="fund.created", entity_type="fund", entity_id=fund.id, firm_id=firm_id,
          fund_id=fund.id, details={"name": fund.name, "fund_type": fund.fund_type})
    db.commit()
    return _fund_out(fund, _counts(db, [fund.id])[fund.id])


@router.get("/funds/{fund_id}", response_model=FundDetail)
def get_fund(fund_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    fund = require_fund(db, user, fund_id)
    docs = db.scalars(select(Document).where(Document.fund_id == fund.id, Document.status != "deleted")
                      .order_by(Document.effective_date.desc().nulls_last(), Document.created_at.desc())).all()
    total = db.scalar(select(func.count()).select_from(Asset).where(Asset.fund_id == fund.id)) or 0
    visible = db.execute(
        select(Asset.id, Asset.name, Household.id, Household.name)
        .join(Household, Household.id == Asset.household_id)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(Asset.fund_id == fund.id, HouseholdMember.user_id == user.id).order_by(Household.name)).all()
    base = _fund_out(fund, _counts(db, [fund.id])[fund.id])
    return FundDetail(**base.model_dump(), your_role=firm_role(db, user.id, fund.firm_id),  # type: ignore[arg-type]
                      documents=[document_out(db, d) for d in docs], linked_holdings_total=total,
                      linked_holdings=[FundHoldingOut(asset_id=a, asset_name=an, household_id=h, household_name=hn)
                                       for a, an, h, hn in visible])


@router.patch("/funds/{fund_id}", response_model=FundOut)
def update_fund(fund_id: uuid.UUID, body: FundUpdate, user: CurrentUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    fund = require_fund(db, user, fund_id, "reviewer")
    data = body.model_dump(exclude_unset=True)
    if "fund_type" in data and data["fund_type"] != fund.fund_type and db.scalar(
            select(func.count()).select_from(Asset).where(Asset.fund_id == fund.id)):
        raise ApiError(409, "conflict", "Holdings are linked to this fund; unlink them before changing its type.")
    if data.get("ticker"):
        data["ticker"] = data["ticker"].upper()
    changes = apply_updates(fund, data)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "conflict", "Another fund in this library has that name and share class.") from None
    if changes:
        audit(db, actor_id=user.id, action="fund.updated", entity_type="fund", entity_id=fund.id,
              firm_id=fund.firm_id, fund_id=fund.id, details={"fields": sorted(changes)})
    db.commit()
    return _fund_out(fund, _counts(db, [fund.id])[fund.id])


@router.get("/funds/{fund_id}/documents", response_model=list[DocumentOut])
def list_fund_documents(fund_id: uuid.UUID, include_deleted: bool = False,
                        user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_fund(db, user, fund_id)
    stmt = select(Document).where(Document.fund_id == fund_id)
    if not include_deleted:
        stmt = stmt.where(Document.status != "deleted")
    docs = db.scalars(stmt.order_by(Document.effective_date.desc().nulls_last(), Document.created_at.desc())).all()
    return [document_out(db, d) for d in docs]


def _check_supersedes(db: Session, fund_id: uuid.UUID, doc_id: Optional[uuid.UUID],
                      supersedes: Optional[uuid.UUID]) -> None:
    if supersedes is None:
        return
    if supersedes == doc_id:
        raise ApiError(422, "validation_error", "A document cannot supersede itself.")
    target = db.get(Document, supersedes)
    if target is None or target.fund_id != fund_id or target.status == "deleted":
        raise ApiError(422, "validation_error", "The superseded document must be a live document of the same fund.")
    seen: set[uuid.UUID] = set()
    cur: Optional[Document] = target  # reject cycles (A supersedes B supersedes A)
    while cur is not None and cur.supersedes_document_id is not None:
        if cur.supersedes_document_id == doc_id or cur.supersedes_document_id in seen:
            raise ApiError(422, "validation_error", "That would create a supersession cycle.")
        seen.add(cur.supersedes_document_id)
        cur = db.get(Document, cur.supersedes_document_id)


@router.post("/funds/{fund_id}/documents", response_model=DocumentInitiateOut, status_code=201)
def initiate_fund_upload(fund_id: uuid.UUID, body: FundDocumentInitiate, user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Start uploading a public offering document (stored once per fund; identical files are deduplicated)."""
    fund = require_fund(db, user, fund_id)
    if fund.status != "active":
        raise ApiError(422, "validation_error", "This fund is archived.")
    _check_supersedes(db, fund.id, None, body.supersedes_document_id)
    return initiate_document(db, user, settings, filename=body.filename, category=body.category,
                             size_bytes=body.size_bytes, sha256=body.sha256, fund_id=fund.id,
                             effective_date=body.effective_date, supersedes_document_id=body.supersedes_document_id)


@router.patch("/documents/{document_id}/library-metadata", response_model=DocumentOut)
def update_fund_document(document_id: uuid.UUID, body: FundDocumentUpdate,
                         user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = require_owned(db, user, Document, document_id, label="Document")
    if doc.fund_id is None:
        raise ApiError(422, "validation_error", "Only shared library documents have effective dates and versions.")
    require_fund(db, user, doc.fund_id, "reviewer")
    data = body.model_dump(exclude_unset=True)
    if "supersedes_document_id" in data:
        _check_supersedes(db, doc.fund_id, doc.id, data["supersedes_document_id"])
    changes = apply_updates(doc, data)
    if changes:
        audit(db, actor_id=user.id, action="document.library_metadata_updated", entity_type="document",
              entity_id=doc.id, fund_id=doc.fund_id,
              details={k: (str(v) if v is not None else None) for k, v in data.items()})
    db.commit()
    return document_out(db, doc)


@router.get("/funds/{fund_id}/terms", response_model=FundTermsOut)
def fund_terms(fund_id: uuid.UUID, as_of: Optional[date] = None, review_status: Optional[str] = None,
               user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """All terms of the fund's live documents, plus which approved ones are in force on `as_of` (default today)."""
    require_fund(db, user, fund_id)
    when = as_of or date.today()
    stmt = (select(ExtractedConstraint, Document.safe_filename)
            .join(Document, Document.id == ExtractedConstraint.document_id)
            .where(ExtractedConstraint.fund_id == fund_id, Document.status != "deleted"))
    if review_status:
        stmt = stmt.where(ExtractedConstraint.review_status == review_status)
    rows = db.execute(stmt.order_by(ExtractedConstraint.constraint_type, ExtractedConstraint.effective_from,
                                    Document.safe_filename, ExtractedConstraint.pdf_page)).all()
    return FundTermsOut(as_of=when, terms=[constraint_out(c, n) for c, n in rows],
                        applicable_ids=[c.id for c, _ in rows if in_force(c, when)])


@router.get("/funds/{fund_id}/audit-events", response_model=Page[AuditOut])
def fund_audit(fund_id: uuid.UUID, p: Pagination = Depends(), user: CurrentUser = Depends(get_current_user),
               db: Session = Depends(get_db)):
    require_fund(db, user, fund_id)
    stmt = select(AuditEvent).where(AuditEvent.fund_id == fund_id).order_by(AuditEvent.created_at.desc())
    rows, total = paginate(db, stmt, p)
    return Page(items=[AuditOut.model_validate(r[0]) for r in rows], total=total, limit=p.limit, offset=p.offset)
