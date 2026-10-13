"""CRUD for assets, liabilities, recurring cash flows and scheduled events."""
# mypy: disable-error-code="valid-type,attr-defined"
# (route signatures are generated per model by register(); FastAPI needs the concrete classes)

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import (
    AssetIn,
    AssetOut,
    AssetUpdate,
    CashFlowIn,
    CashFlowOut,
    CashFlowUpdate,
    EventIn,
    EventOut,
    EventUpdate,
    LiabilityIn,
    LiabilityOut,
    LiabilityUpdate,
)
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import require_household, require_owned
from ..db import get_db
from ..errors import ApiError
from ..models import Asset, CashFlow, Liability, ScheduledEvent
from .common import apply_updates

router = APIRouter(tags=["financial profile"])


def _validate_event(data: dict[str, Any]) -> None:
    if data.get("kind") == "rsu_vest" and data.get("tax_due_month") is not None \
            and data["tax_due_month"] < data.get("month", 1):
        raise ApiError(422, "validation_error", "The RSU tax due month cannot be before the vest month.")


def register(model: type, path: str, entity: str, In: type[BaseModel], Update: type[BaseModel],
             Out: type[BaseModel], order_by: Any, validate=None) -> None:
    label = entity.replace("_", " ").capitalize()

    @router.get(f"/households/{{household_id}}/{path}", response_model=list[Out], name=f"list_{entity}s")
    def list_items(household_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
        require_household(db, user, household_id)
        return db.scalars(select(model).where(model.household_id == household_id).order_by(*order_by)).all()

    @router.post(f"/households/{{household_id}}/{path}", response_model=Out, status_code=201, name=f"create_{entity}")
    def create_item(household_id: uuid.UUID, body: In, user: CurrentUser = Depends(get_current_user),  # type: ignore[valid-type]
                    db: Session = Depends(get_db)):
        require_household(db, user, household_id, "editor")
        data = body.model_dump()
        if validate:
            validate(data)
        obj = model(household_id=household_id, **data)
        db.add(obj)
        db.flush()
        audit(db, actor_id=user.id, action=f"{entity}.created", entity_type=entity, entity_id=obj.id,
              household_id=household_id, details={"kind": data.get("kind")})
        db.commit()
        return obj

    @router.patch(f"/{path}/{{item_id}}", response_model=Out, name=f"update_{entity}")
    def update_item(item_id: uuid.UUID, body: Update, user: CurrentUser = Depends(get_current_user),  # type: ignore[valid-type]
                    db: Session = Depends(get_db)):
        obj: Any = require_owned(db, user, model, item_id, "editor", label)
        data = body.model_dump(exclude_unset=True)
        if validate:
            validate({**{k: getattr(obj, k) for k in ("kind", "month", "tax_due_month") if hasattr(obj, k)}, **data})
        changes = apply_updates(obj, data)
        if changes:
            audit(db, actor_id=user.id, action=f"{entity}.updated", entity_type=entity, entity_id=obj.id,
                  household_id=obj.household_id, details={"fields": sorted(changes)})
        db.commit()
        return obj

    @router.delete(f"/{path}/{{item_id}}", status_code=204, name=f"delete_{entity}")
    def delete_item(item_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
        obj: Any = require_owned(db, user, model, item_id, "editor", label)
        audit(db, actor_id=user.id, action=f"{entity}.deleted", entity_type=entity, entity_id=obj.id,
              household_id=obj.household_id)
        db.delete(obj)
        db.commit()


register(Asset, "assets", "asset", AssetIn, AssetUpdate, AssetOut, (Asset.kind, Asset.name))
register(Liability, "liabilities", "liability", LiabilityIn, LiabilityUpdate, LiabilityOut,
         (Liability.kind, Liability.name))
register(CashFlow, "cash-flows", "cash_flow", CashFlowIn, CashFlowUpdate, CashFlowOut, (CashFlow.kind, CashFlow.name))
register(ScheduledEvent, "events", "scheduled_event", EventIn, EventUpdate, EventOut,
         (ScheduledEvent.month, ScheduledEvent.kind), validate=_validate_event)
