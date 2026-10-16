"""Firm provisioning: every profile belongs to at least one firm (its library access boundary)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Firm, FirmMember


def create_personal_firm(db: Session, user_id: uuid.UUID) -> uuid.UUID:
    firm = Firm(name="My firm", created_by=user_id)
    db.add(firm)
    db.flush()
    db.add(FirmMember(firm_id=firm.id, user_id=user_id, role="admin"))
    db.flush()
    return firm.id


def default_firm_id(db: Session, user_id: uuid.UUID) -> uuid.UUID:
    """The user's earliest firm membership; creates a personal firm if the user has none."""
    fid = db.scalar(select(FirmMember.firm_id).where(FirmMember.user_id == user_id)
                    .order_by(FirmMember.created_at, FirmMember.firm_id).limit(1))
    return fid if fid is not None else create_personal_firm(db, user_id)
