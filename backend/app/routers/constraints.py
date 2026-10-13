"""Extracted constraint review: edit, approve, reject, with revision history."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import ConstraintDecision, ConstraintDetail, ConstraintOut, ConstraintUpdate, RevisionOut
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import require_household, require_owned
from ..db import get_db
from ..engine.constraint_extractor import QUALITATIVE_TYPES
from ..errors import ApiError
from ..models import ConstraintRevision, Document, ExtractedConstraint

router = APIRouter(tags=["constraints"])
QUALITATIVE = {t.value for t in QUALITATIVE_TYPES}
EDITABLE = ("value", "lower_bound", "upper_bound", "unit", "timing", "conditions", "interpretation", "review_status")


def _is_qualitative(c: ExtractedConstraint) -> bool:
    return c.constraint_type in QUALITATIVE or (c.value is None and c.lower_bound is None and c.upper_bound is None
                                                and c.original_value is None)


def constraint_out(c: ExtractedConstraint, doc_name: str) -> ConstraintOut:
    return ConstraintOut.model_validate(c).model_copy(update={"document_name": doc_name,
                                                              "is_qualitative": _is_qualitative(c)})


def _snapshot(c: ExtractedConstraint) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in
            ((f, getattr(c, f)) for f in (*EDITABLE, "source_type", "revision"))}


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
    change: dict[str, Any] = {}
    for k, v in data.items():
        old = getattr(c, k)
        if (Decimal(str(old)) if isinstance(old, Decimal) and v is not None else old) != (
                Decimal(str(v)) if isinstance(old, Decimal) and v is not None else v):
            change[k] = {"from": None if old is None else str(old), "to": None if v is None else str(v)}
            setattr(c, k, v)
    if not change:
        return c
    values_changed = bool(set(change) & {"value", "lower_bound", "upper_bound", "unit", "timing", "conditions"})
    if values_changed and c.review_status != "rejected" and "review_status" not in data:
        c.review_status = "edited"
        change.setdefault("review_status", {"from": None, "to": "edited"})
    if c.review_status == "edited" or (c.review_status == "confirmed" and values_changed):
        c.source_type = "user_confirmed"
    if c.review_status in ("confirmed", "edited", "rejected"):
        c.reviewed_by, c.reviewed_at = user.id, datetime.now(UTC)
    c.revision += 1
    db.add(ConstraintRevision(constraint_id=c.id, household_id=c.household_id, revision=c.revision,
                              changed_by=user.id, change=change, snapshot=_snapshot(c), note=note))
    audit(db, actor_id=user.id, action="constraint.reviewed", entity_type="constraint", entity_id=c.id,
          household_id=c.household_id, details={"fields": sorted(change), "status": c.review_status,
                                                "revision": c.revision})
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
    c = db.execute(select(ExtractedConstraint).where(ExtractedConstraint.id == constraint_id).with_for_update()
                   ).scalar_one_or_none()
    if c is None:
        raise ApiError(404, "not_found", "Constraint not found.")
    require_household(db, user, c.household_id, "editor")
    data = body.model_dump(exclude_unset=True, exclude={"expected_revision", "note"})
    _apply(db, c, user, body.expected_revision, data, body.note)
    db.commit()
    return constraint_out(c, _doc_name(db, c))


def _decide(constraint_id: uuid.UUID, status: str, body: ConstraintDecision, user: CurrentUser, db: Session):
    c = db.execute(select(ExtractedConstraint).where(ExtractedConstraint.id == constraint_id).with_for_update()
                   ).scalar_one_or_none()
    if c is None:
        raise ApiError(404, "not_found", "Constraint not found.")
    require_household(db, user, c.household_id, "editor")
    if status == "confirmed" and c.review_status == "edited":
        status = "edited"  # approving an edited value keeps its user-confirmed provenance
    _apply(db, c, user, body.expected_revision, {"review_status": status}, body.note)
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
