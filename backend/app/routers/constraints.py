"""Extracted constraint review: edit, approve, reject, supersede, with revision history.

Household terms are reviewed by household editors. Shared library (fund) terms are reviewed only by firm
reviewers/admins; advisors can read them. Supersession is an explicit reviewer action, never inferred.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import (
    ConstraintDecision,
    ConstraintDetail,
    ConstraintOut,
    ConstraintSupersede,
    ConstraintUpdate,
    RevisionOut,
)
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import require_fund, require_household, require_owned
from ..db import get_db
from ..engine.constraint_extractor import QUALITATIVE_TYPES, verify_quote
from ..errors import ApiError
from ..models import ConstraintRevision, Document, DocumentPage, ExtractedConstraint

router = APIRouter(tags=["constraints"])
QUALITATIVE = {t.value for t in QUALITATIVE_TYPES}
EDITABLE = ("value", "lower_bound", "upper_bound", "unit", "timing", "conditions", "interpretation",
            "value_kind", "exceptions", "discretion", "effective_period", "effective_from", "effective_to",
            "review_status")
APPROVED = ("confirmed", "edited")
VALUE_FIELDS = {"value", "lower_bound", "upper_bound", "unit", "timing", "conditions", "value_kind", "exceptions",
                "discretion", "effective_period"}


def _is_qualitative(c: ExtractedConstraint) -> bool:
    return c.constraint_type in QUALITATIVE or (c.value is None and c.lower_bound is None and c.upper_bound is None
                                                and c.original_value is None)


def constraint_out(c: ExtractedConstraint, doc_name: str) -> ConstraintOut:
    return ConstraintOut.model_validate(c).model_copy(update={"document_name": doc_name,
                                                              "is_qualitative": _is_qualitative(c)})


def _jsonable(v: Any) -> Any:
    return str(v) if isinstance(v, (Decimal, uuid.UUID)) else v.isoformat() if isinstance(v, date) else v


def _snapshot(c: ExtractedConstraint) -> dict[str, Any]:
    return {k: _jsonable(getattr(c, k)) for k in (*EDITABLE, "superseded_by_id", "source_type", "revision")}


def _authorize_review(db: Session, user: CurrentUser, c: ExtractedConstraint) -> None:
    if c.fund_id is not None:
        require_fund(db, user, c.fund_id, "reviewer")
    else:
        assert c.household_id is not None
        require_household(db, user, c.household_id, "editor")


def _evidence_problems(db: Session, c: ExtractedConstraint, as_extracted: bool) -> list[str]:
    """Why this term cannot be approved. The quote is re-checked against the stored text of the cited page (never
    another page); approving the extracted value as source-backed also requires no evidence errors. A reviewer edit
    replaces the extracted value, so only the citation check applies to it."""
    text = db.scalar(select(DocumentPage.text).where(DocumentPage.document_id == c.document_id,
                                                     DocumentPage.pdf_page == c.pdf_page))
    problems = []
    if not text or not verify_quote(c.evidence_quote, text):
        problems.append(f"The evidence quote is not on the cited page (PDF page {c.pdf_page}).")
    if as_extracted:
        problems += [i.get("message", i.get("code", "")) for i in (c.validation_issues or [])
                     if i.get("severity") == "error" and i.get("code") not in ("quote_not_found",
                                                                              "quote_not_on_cited_page")]
    return problems


def _require_supported(db: Session, c: ExtractedConstraint, as_extracted: bool) -> None:
    problems = _evidence_problems(db, c, as_extracted)
    if problems:
        citation_missing = problems[0].startswith("The evidence quote")
        hint = ("Reject it: the cited page does not contain this evidence." if citation_missing else
                "Edit the value with a review note (it becomes a reviewer-confirmed value), or reject it.")
        raise ApiError(422, "unsupported_evidence", "This term cannot be approved: " + " ".join(problems) + " " + hint,
                       details={"problems": problems})
    c.quote_verified = True  # re-verified on the cited page just now


def _locked(db: Session, constraint_id: uuid.UUID) -> ExtractedConstraint:
    c = db.execute(select(ExtractedConstraint).where(ExtractedConstraint.id == constraint_id).with_for_update()
                   ).scalar_one_or_none()
    if c is None:
        raise ApiError(404, "not_found", "Constraint not found.")
    return c


def _apply(db: Session, c: ExtractedConstraint, user: CurrentUser, expected: int, data: dict[str, Any],
           note: Optional[str]) -> ExtractedConstraint:
    if c.revision != expected:
        raise ApiError(409, "conflict", "This constraint was changed by someone else. Reload and try again.",
                       details={"current_revision": c.revision})
    numeric = {k for k in ("value", "lower_bound", "upper_bound") if k in data}
    if _is_qualitative(c) and any(data[k] is not None for k in numeric):
        raise ApiError(422, "validation_error", "This is a qualitative clause; it cannot be given a numeric value. "
                                                "Model its effect as a scenario assumption instead.")
    lo = data.get("lower_bound", c.lower_bound)
    hi = data.get("upper_bound", c.upper_bound)
    if lo is not None and hi is not None and Decimal(str(lo)) > Decimal(str(hi)):
        raise ApiError(422, "validation_error", "Lower bound cannot exceed upper bound.")
    start, end = data.get("effective_from", c.effective_from), data.get("effective_to", c.effective_to)
    if start is not None and end is not None and end <= start:
        raise ApiError(422, "validation_error", "effective_to must be after effective_from.")
    change: dict[str, Any] = {}
    for k, v in data.items():
        old = getattr(c, k)
        if (Decimal(str(old)) if isinstance(old, Decimal) and v is not None else old) != (
                Decimal(str(v)) if isinstance(old, Decimal) and v is not None else v):
            change[k] = {"from": None if old is None else str(_jsonable(old)),
                         "to": None if v is None else str(_jsonable(v))}
            setattr(c, k, v)
    if not change:
        return c
    values_changed = bool(set(change) & {"value", "lower_bound", "upper_bound", "unit", "timing", "conditions",
                                         "value_kind", "exceptions", "discretion", "effective_period"})
    if values_changed and c.review_status != "rejected" and "review_status" not in data:
        c.review_status = "edited"
        change.setdefault("review_status", {"from": None, "to": "edited"})
    if c.review_status == "edited" or (c.review_status == "confirmed" and values_changed):
        c.source_type = "user_confirmed"
    if c.review_status in ("confirmed", "edited", "rejected"):
        c.reviewed_by, c.reviewed_at = user.id, datetime.now(UTC)
    c.revision += 1
    db.add(ConstraintRevision(constraint_id=c.id, household_id=c.household_id, fund_id=c.fund_id,
                              revision=c.revision, changed_by=user.id, change=change, snapshot=_snapshot(c),
                              note=note))
    audit(db, actor_id=user.id, action="constraint.reviewed", entity_type="constraint", entity_id=c.id,
          household_id=c.household_id, fund_id=c.fund_id,
          details={"fields": sorted(change), "status": c.review_status, "revision": c.revision})
    return c


def _doc_name(db: Session, c: ExtractedConstraint) -> str:
    return db.scalar(select(Document.safe_filename).where(Document.id == c.document_id)) or ""


@router.get("/households/{household_id}/constraints", response_model=list[ConstraintOut])
def list_constraints(household_id: uuid.UUID, document_id: Optional[uuid.UUID] = None,
                     review_status: Optional[str] = None, user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    require_household(db, user, household_id)
    stmt = (select(ExtractedConstraint, Document.safe_filename)
            .join(Document, Document.id == ExtractedConstraint.document_id)
            .where(ExtractedConstraint.household_id == household_id, Document.status != "deleted"))
    if document_id:
        stmt = stmt.where(ExtractedConstraint.document_id == document_id)
    if review_status:
        stmt = stmt.where(ExtractedConstraint.review_status == review_status)
    rows = db.execute(stmt.order_by(Document.safe_filename, ExtractedConstraint.pdf_page,
                                    ExtractedConstraint.constraint_type)).all()
    return [constraint_out(c, name) for c, name in rows]


@router.get("/constraints/{constraint_id}", response_model=ConstraintDetail)
def get_constraint(constraint_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    c = require_owned(db, user, ExtractedConstraint, constraint_id, label="Constraint")
    revisions = db.scalars(select(ConstraintRevision).where(ConstraintRevision.constraint_id == c.id)
                           .order_by(ConstraintRevision.revision.desc())).all()
    base = constraint_out(c, _doc_name(db, c))
    return ConstraintDetail(**base.model_dump(), revisions=[RevisionOut.model_validate(r) for r in revisions])


@router.patch("/constraints/{constraint_id}", response_model=ConstraintOut)
def update_constraint(constraint_id: uuid.UUID, body: ConstraintUpdate, user: CurrentUser = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    c = _locked(db, constraint_id)
    _authorize_review(db, user, c)
    data = body.model_dump(exclude_unset=True, exclude={"expected_revision", "note"})
    edits_values = bool(set(data) & VALUE_FIELDS)
    becomes = data.get("review_status") or ("edited" if edits_values and c.review_status != "rejected" else None)
    if becomes in APPROVED and c.revision == body.expected_revision:
        _require_supported(db, c, as_extracted=becomes == "confirmed" and not edits_values)
    _apply(db, c, user, body.expected_revision, data, body.note)
    db.commit()
    return constraint_out(c, _doc_name(db, c))


def _decide(constraint_id: uuid.UUID, status: str, body: ConstraintDecision, user: CurrentUser, db: Session):
    c = _locked(db, constraint_id)
    _authorize_review(db, user, c)
    if status == "confirmed" and c.review_status == "edited":
        status = "edited"  # approving an edited value keeps its user-confirmed provenance
    if status in APPROVED and c.revision == body.expected_revision:
        _require_supported(db, c, as_extracted=status == "confirmed")
    data: dict[str, Any] = {"review_status": status}
    if status in APPROVED and c.fund_id is not None and c.effective_from is None:
        # Library terms default to their document's effective date (recorded in the revision).
        doc_date = db.scalar(select(Document.effective_date).where(Document.id == c.document_id))
        if doc_date is not None:
            data["effective_from"] = doc_date
    _apply(db, c, user, body.expected_revision, data, body.note)
    db.commit()
    return constraint_out(c, _doc_name(db, c))


@router.post("/constraints/{constraint_id}/approve", response_model=ConstraintOut)
def approve_constraint(constraint_id: uuid.UUID, body: ConstraintDecision,
                       user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _decide(constraint_id, "confirmed", body, user, db)


@router.post("/constraints/{constraint_id}/reject", response_model=ConstraintOut)
def reject_constraint(constraint_id: uuid.UUID, body: ConstraintDecision,
                      user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _decide(constraint_id, "rejected", body, user, db)


@router.post("/constraints/{constraint_id}/supersede", response_model=list[ConstraintOut])
def supersede_constraint(constraint_id: uuid.UUID, body: ConstraintSupersede,
                         user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """`constraint_id` (newer, approved) replaces `superseded_id` (older, approved, same owner and type) from
    `effective_date`. The older term keeps its history and still applies before that date."""
    if body.superseded_id == constraint_id:
        raise ApiError(422, "validation_error", "A term cannot supersede itself.")
    # Lock both rows in a stable order to avoid deadlocks between concurrent reviewers.
    ids = sorted([constraint_id, body.superseded_id])
    rows = {r.id: r for r in db.scalars(select(ExtractedConstraint).where(ExtractedConstraint.id.in_(ids))
                                         .order_by(ExtractedConstraint.id).with_for_update())}
    new, old = rows.get(constraint_id), rows.get(body.superseded_id)
    if new is None or old is None:
        raise ApiError(404, "not_found", "Constraint not found.")
    _authorize_review(db, user, new)
    if (new.fund_id, new.household_id) != (old.fund_id, old.household_id):
        raise ApiError(422, "validation_error", "Both terms must belong to the same fund (or household).")
    if (new.constraint_type, new.asset_key) != (old.constraint_type, old.asset_key):
        raise ApiError(422, "validation_error", "Only a term of the same type can be superseded "
                                                f"({new.constraint_type} vs {old.constraint_type}).")
    if new.review_status not in APPROVED or old.review_status not in APPROVED:
        raise ApiError(422, "validation_error", "Approve both terms before recording that one supersedes the other.")
    if old.superseded_by_id is not None:
        raise ApiError(409, "conflict", "That term is already superseded.",
                       details={"superseded_by_id": str(old.superseded_by_id)})
    if new.superseded_by_id is not None:
        raise ApiError(422, "validation_error", "The newer term is itself superseded.")
    when = body.effective_date or new.effective_from or db.scalar(
        select(Document.effective_date).where(Document.id == new.document_id))
    if when is None:
        raise ApiError(422, "validation_error", "An effective date is required: set it here, on the newer term, or "
                                                "on its document.")
    if new.effective_from is not None and new.effective_from != when:
        raise ApiError(422, "validation_error", f"The newer term already starts on {new.effective_from}; "
                                                "use that date or edit the term first.")
    if old.effective_from is not None and when <= old.effective_from:
        raise ApiError(422, "validation_error", f"The superseding date must be after the older term's start "
                                                f"({old.effective_from}).")
    _apply(db, new, user, body.expected_revision, {"effective_from": when},
           body.note or f"Supersedes term {old.id}")
    _apply(db, old, user, body.superseded_expected_revision, {"effective_to": when, "superseded_by_id": new.id},
           body.note or f"Superseded by term {new.id} from {when}")
    audit(db, actor_id=user.id, action="constraint.superseded", entity_type="constraint", entity_id=old.id,
          household_id=old.household_id, fund_id=old.fund_id,
          details={"superseded_by": str(new.id), "effective_date": when.isoformat()})
    db.commit()
    return [constraint_out(new, _doc_name(db, new)), constraint_out(old, _doc_name(db, old))]
