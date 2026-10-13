"""Shared route helpers."""
from __future__ import annotations

from typing import Any

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from ..errors import ApiError


class Pagination:
    def __init__(self, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        self.limit, self.offset = limit, offset


def paginate(db: Session, stmt: Select, p: Pagination) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.execute(stmt.limit(p.limit).offset(p.offset)).all())
    return items, total


def apply_updates(obj: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update; return {field: {"from", "to"}} for the audit trail (no values for free text)."""
    changes: dict[str, Any] = {}
    table = getattr(obj, "__table__", None)
    for k, v in data.items():
        if v is None and table is not None and k in table.columns and not table.columns[k].nullable:
            raise ApiError(422, "validation_error", f"'{k}' cannot be empty.",
                           details=[{"loc": [k], "msg": "required"}])
    for k, v in data.items():
        old = getattr(obj, k)
        if old != v:
            setattr(obj, k, v)
            changes[k] = {"from": str(old) if old is not None else None, "to": str(v) if v is not None else None}
    return changes
