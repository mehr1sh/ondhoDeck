"""Household-level authorization. Every household-scoped route resolves access through here."""
from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import CurrentUser
from .errors import ApiError
from .models import Household, HouseholdMember

ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}
T = TypeVar("T")


def require_household(db: Session, user: CurrentUser, household_id: uuid.UUID, min_role: str = "viewer") -> Household:
    """Return the household if `user` is a member with at least `min_role`.

    Non-members get 404 (not 403) so household ids cannot be probed.
    """
    row = db.execute(
        select(Household, HouseholdMember.role)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(Household.id == household_id, HouseholdMember.user_id == user.id)
    ).first()
    if row is None:
        raise ApiError(404, "not_found", "Household not found.")
    household, role = row
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise ApiError(403, "forbidden", f"This action requires the '{min_role}' role on the household.")
    return household


def require_owned(db: Session, user: CurrentUser, model: type[T], obj_id: uuid.UUID, min_role: str = "viewer",
                  label: str = "Record") -> T:
    """Load a household-scoped row by id and check membership of its household."""
    obj = db.get(model, obj_id)
    if obj is None:
        raise ApiError(404, "not_found", f"{label} not found.")
    require_household(db, user, obj.household_id, min_role)  # type: ignore[attr-defined]
    return obj
