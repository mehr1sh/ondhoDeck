"""Authorization. Household routes resolve access through household membership; shared fund library routes
resolve it through firm membership. Rows owned by a library fund (household_id NULL, fund_id set) are
checked against the fund's firm."""
from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import CurrentUser
from .errors import ApiError
from .models import Firm, FirmMember, Fund, Household, HouseholdMember

ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}
FIRM_ROLE_RANK = {"advisor": 0, "reviewer": 1, "admin": 2}
# Household role required by a route -> firm role required when the row belongs to a library fund.
# Advisors may read, upload and reprocess library documents; approving terms needs a reviewer (checked by the route).
FIRM_ROLE_FOR = {"viewer": "advisor", "editor": "advisor", "owner": "admin"}
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


def firm_role(db: Session, user_id: uuid.UUID, firm_id: uuid.UUID) -> str | None:
    return db.scalar(select(FirmMember.role).where(FirmMember.firm_id == firm_id, FirmMember.user_id == user_id))


def require_firm(db: Session, user: CurrentUser, firm_id: uuid.UUID, min_role: str = "advisor") -> Firm:
    """Return the firm if `user` is a member with at least `min_role` (404 for non-members)."""
    row = db.execute(select(Firm, FirmMember.role).join(FirmMember, FirmMember.firm_id == Firm.id)
                     .where(Firm.id == firm_id, FirmMember.user_id == user.id)).first()
    if row is None:
        raise ApiError(404, "not_found", "Firm not found.")
    firm, role = row
    if FIRM_ROLE_RANK[role] < FIRM_ROLE_RANK[min_role]:
        raise ApiError(403, "forbidden", f"This action requires the '{min_role}' role in the firm.")
    return firm


def require_fund(db: Session, user: CurrentUser, fund_id: uuid.UUID, min_role: str = "advisor") -> Fund:
    """Return the library fund if `user` belongs to its firm with at least `min_role` (404 otherwise)."""
    row = db.execute(select(Fund, FirmMember.role).join(FirmMember, FirmMember.firm_id == Fund.firm_id)
                     .where(Fund.id == fund_id, FirmMember.user_id == user.id)).first()
    if row is None:
        raise ApiError(404, "not_found", "Fund not found.")
    fund, role = row
    if FIRM_ROLE_RANK[role] < FIRM_ROLE_RANK[min_role]:
        raise ApiError(403, "forbidden", f"This action requires the '{min_role}' role in the fund's firm.")
    return fund


def require_owned(db: Session, user: CurrentUser, model: type[T], obj_id: uuid.UUID, min_role: str = "viewer",
                  label: str = "Record") -> T:
    """Load a household- or library-owned row by id and check the caller's access to its owner."""
    obj = db.get(model, obj_id)
    if obj is None:
        raise ApiError(404, "not_found", f"{label} not found.")
    authorize_owner(db, user, obj, min_role)
    return obj


def authorize_owner(db: Session, user: CurrentUser, obj: object, min_role: str = "viewer") -> None:
    hid = getattr(obj, "household_id", None)
    fid = getattr(obj, "fund_id", None)
    if hid is None and fid is not None:
        require_fund(db, user, fid, FIRM_ROLE_FOR[min_role])
    elif hid is not None:
        require_household(db, user, hid, min_role)
    else:
        raise ApiError(404, "not_found", "Record not found.")
