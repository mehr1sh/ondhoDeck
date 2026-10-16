"""Audit trail helper. Callers pass only non-sensitive metadata (ids, field names, statuses)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditEvent


def audit(db: Session, *, actor_id: uuid.UUID | None, action: str, entity_type: str,
          entity_id: uuid.UUID | None = None, household_id: uuid.UUID | None = None,
          fund_id: uuid.UUID | None = None, firm_id: uuid.UUID | None = None,
          details: dict[str, Any] | None = None) -> None:
    """Add an audit event to the current transaction (committed with the change it describes)."""
    db.add(AuditEvent(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                      household_id=household_id, fund_id=fund_id, firm_id=firm_id, details=details or {}))
