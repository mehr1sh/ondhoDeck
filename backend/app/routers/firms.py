"""Firms: the access boundary of the shared fund library, and their members' roles."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..api_schemas import FirmMemberIn, FirmMemberOut, FirmMemberUpdate, FirmOut, FirmUpdate
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import require_firm
from ..db import get_db
from ..errors import ApiError
from ..models import Firm, FirmMember, Profile

router = APIRouter(tags=["firms"])


def _members(db: Session, firm_id: uuid.UUID) -> list[FirmMemberOut]:
    rows = db.execute(select(FirmMember, Profile).join(Profile, Profile.id == FirmMember.user_id)
                      .where(FirmMember.firm_id == firm_id).order_by(FirmMember.created_at)).all()
    return [FirmMemberOut(user_id=m.user_id, email=p.email, display_name=p.display_name, role=m.role,  # type: ignore[arg-type]
                          created_at=m.created_at) for m, p in rows]


def _admin_count(db: Session, firm_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(FirmMember)
                     .where(FirmMember.firm_id == firm_id, FirmMember.role == "admin")) or 0


def _member(db: Session, firm_id: uuid.UUID, user_id: uuid.UUID) -> FirmMember:
    m = db.scalar(select(FirmMember).where(FirmMember.firm_id == firm_id, FirmMember.user_id == user_id)
                  .with_for_update())
    if m is None:
        raise ApiError(404, "not_found", "Member not found.")
    return m


@router.get("/me/firms", response_model=list[FirmOut])
def my_firms(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Firm, FirmMember.role).join(FirmMember, FirmMember.firm_id == Firm.id)
                      .where(FirmMember.user_id == user.id).order_by(FirmMember.created_at)).all()
    return [FirmOut(id=f.id, name=f.name, role=r, created_at=f.created_at) for f, r in rows]


@router.patch("/firms/{firm_id}", response_model=FirmOut)
def rename_firm(firm_id: uuid.UUID, body: FirmUpdate, user: CurrentUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    firm = require_firm(db, user, firm_id, "admin")
    firm.name = body.name
    audit(db, actor_id=user.id, action="firm.renamed", entity_type="firm", entity_id=firm.id, firm_id=firm.id)
    db.commit()
    return FirmOut(id=firm.id, name=firm.name, role="admin", created_at=firm.created_at)


@router.get("/firms/{firm_id}/members", response_model=list[FirmMemberOut])
def list_members(firm_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_firm(db, user, firm_id)
    return _members(db, firm_id)


@router.post("/firms/{firm_id}/members", response_model=list[FirmMemberOut], status_code=201)
def add_member(firm_id: uuid.UUID, body: FirmMemberIn, user: CurrentUser = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Add an existing account (it must have signed in at least once) to the firm."""
    require_firm(db, user, firm_id, "admin")
    profile = db.scalar(select(Profile).where(func.lower(Profile.email) == body.email.strip().lower()))
    if profile is None:
        raise ApiError(404, "not_found", "No account with that email has signed in yet. Ask them to sign up first.")
    if db.scalar(select(FirmMember).where(FirmMember.firm_id == firm_id, FirmMember.user_id == profile.id)):
        raise ApiError(409, "conflict", "That person is already a member of this firm.")
    db.add(FirmMember(firm_id=firm_id, user_id=profile.id, role=body.role))
    audit(db, actor_id=user.id, action="firm.member_added", entity_type="firm_member", entity_id=profile.id,
          firm_id=firm_id, details={"role": body.role})
    db.commit()
    return _members(db, firm_id)


@router.patch("/firms/{firm_id}/members/{user_id}", response_model=list[FirmMemberOut])
def change_role(firm_id: uuid.UUID, user_id: uuid.UUID, body: FirmMemberUpdate,
                user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_firm(db, user, firm_id, "admin")
    m = _member(db, firm_id, user_id)
    if m.role == "admin" and body.role != "admin" and _admin_count(db, firm_id) <= 1:
        raise ApiError(409, "conflict", "A firm needs at least one admin. Promote someone else first.")
    old, m.role = m.role, body.role
    audit(db, actor_id=user.id, action="firm.member_role_changed", entity_type="firm_member", entity_id=user_id,
          firm_id=firm_id, details={"from": old, "to": body.role})
    db.commit()
    return _members(db, firm_id)


@router.delete("/firms/{firm_id}/members/{user_id}", status_code=204)
def remove_member(firm_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Admins remove anyone; members may leave. The last admin cannot be removed."""
    require_firm(db, user, firm_id, "advisor" if user_id == user.id else "admin")
    m = _member(db, firm_id, user_id)
    if m.role == "admin" and _admin_count(db, firm_id) <= 1:
        raise ApiError(409, "conflict", "A firm needs at least one admin. Promote someone else first.")
    db.delete(m)
    audit(db, actor_id=user.id, action="firm.member_removed", entity_type="firm_member", entity_id=user_id,
          firm_id=firm_id)
    db.commit()
