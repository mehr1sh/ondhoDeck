"""Households, membership, summary, demo onboarding, profile/account."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api_schemas import (
    AccountDelete,
    AuditOut,
    DocumentOut,
    HouseholdIn,
    HouseholdOut,
    HouseholdSummary,
    HouseholdUpdate,
    Page,
    ProfileOut,
    ProfileUpdate,
    RunSummary,
)
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import require_household
from ..config import Settings, get_settings
from ..db import get_db
from ..engine.synthetic_docs import SYNTHETIC_DOCS, ensure_synthetic_docs
from ..errors import ApiError
from ..models import (
    Asset,
    AuditEvent,
    CashFlow,
    Document,
    ExtractedConstraint,
    Household,
    HouseholdMember,
    Liability,
    Profile,
    ScenarioDefinition,
    ScheduledEvent,
    SimulationRun,
)
from ..storage import get_storage, safe_filename
from .common import Pagination, apply_updates, paginate

log = logging.getLogger("slipslopes.households")
router = APIRouter(tags=["households"])
FIXTURES = Path(__file__).resolve().parent.parent / "engine" / "fixtures"
DEMO_CATEGORIES = {
    "SYNTHETIC_Interval_Fund_Repurchase_Policy.pdf": "interval_fund",
    "SYNTHETIC_Securities_Backed_Line_Agreement.pdf": "sbl_agreement",
    "SYNTHETIC_Private_Fund_LPA_Capital_Calls.pdf": "private_fund_agreement",
    "SYNTHETIC_RSU_Grant_and_Trading_Policy.pdf": "rsu_grant",
}


def member_role(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> str:
    role = db.scalar(select(HouseholdMember.role).where(HouseholdMember.household_id == household_id,
                                                        HouseholdMember.user_id == user_id))
    if role is None:
        raise ApiError(404, "not_found", "Household not found.")
    return role


def household_out(h: Household, role: str) -> HouseholdOut:
    return HouseholdOut.model_validate({**{c: getattr(h, c) for c in HouseholdOut.model_fields if c != "role"},
                                        "role": role})


# ----------------------------------------------------------------------------- profile

@router.get("/me", response_model=ProfileOut)
def get_me(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.get(Profile, user.id)


@router.patch("/me", response_model=ProfileOut)
def update_me(body: ProfileUpdate, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.get(Profile, user.id)
    changes = apply_updates(profile, body.model_dump(exclude_unset=True))
    if changes:
        audit(db, actor_id=user.id, action="profile.updated", entity_type="profile", entity_id=user.id,
              details={"fields": sorted(changes)})
    db.commit()
    return profile


@router.get("/me/documents", response_model=Page[DocumentOut])
def my_documents(p: Pagination = Depends(), user: CurrentUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    stmt = (select(Document).join(HouseholdMember, HouseholdMember.household_id == Document.household_id)
            .where(HouseholdMember.user_id == user.id, Document.status != "deleted")
            .order_by(Document.created_at.desc()))
    rows, total = paginate(db, stmt, p)
    return Page(items=[DocumentOut.model_validate(r[0]) for r in rows], total=total, limit=p.limit, offset=p.offset)


@router.delete("/me", status_code=status.HTTP_200_OK)
def delete_account(body: AccountDelete, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)):
    """Delete households the user solely owns (with their files), memberships, profile and auth identity."""
    from ..services.documents import purge_household_files

    storage = get_storage()
    memberships = db.scalars(select(HouseholdMember).where(HouseholdMember.user_id == user.id)).all()
    deleted_households = 0
    for m in memberships:
        owners = db.scalar(select(func.count()).where(HouseholdMember.household_id == m.household_id,
                                                      HouseholdMember.role == "owner")) or 0
        if m.role == "owner" and owners == 1:
            purge_household_files(db, storage, m.household_id)
            db.delete(db.get(Household, m.household_id))
            deleted_households += 1
        else:
            db.delete(m)
    audit(db, actor_id=None, action="account.deleted", entity_type="profile", entity_id=None,
          details={"households_deleted": deleted_households})
    db.flush()
    profile = db.get(Profile, user.id)
    try:
        with db.begin_nested():
            db.delete(profile)
    except IntegrityError:
        # The user authored records in households shared with others: keep an anonymised profile row.
        anonymised = db.get(Profile, user.id)
        if anonymised is not None:
            anonymised.email, anonymised.display_name = None, "Deleted user"
    db.commit()
    identity_deleted = False
    if settings.supabase_url and settings.supabase_service_role_key:
        try:
            r = httpx.delete(f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user.id}", timeout=10,
                             headers={"Authorization": f"Bearer {settings.supabase_service_role_key}",
                                      "apikey": settings.supabase_service_role_key})
            identity_deleted = r.status_code in (200, 204)
        except httpx.HTTPError:
            identity_deleted = False
    return {"households_deleted": deleted_households, "auth_identity_deleted": identity_deleted}


# ----------------------------------------------------------------------------- households

@router.get("/households", response_model=Page[HouseholdOut])
def list_households(p: Pagination = Depends(), user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    stmt = (select(Household, HouseholdMember.role).join(HouseholdMember, HouseholdMember.household_id == Household.id)
            .where(HouseholdMember.user_id == user.id).order_by(Household.created_at.desc()))
    rows, total = paginate(db, stmt, p)
    return Page(items=[household_out(h, role) for h, role in rows], total=total, limit=p.limit, offset=p.offset)


def _create_household(db: Session, user: CurrentUser, body: HouseholdIn, is_demo: bool = False) -> Household:
    h = Household(name=body.name, reporting_currency=body.reporting_currency,
                  start_calendar_month=body.start_calendar_month, notes=body.notes, created_by=user.id,
                  is_demo=is_demo)
    db.add(h)
    db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=user.id, role="owner"))
    audit(db, actor_id=user.id, action="household.created", entity_type="household", entity_id=h.id,
          household_id=h.id, details={"demo": is_demo})
    return h


@router.post("/households", response_model=HouseholdOut, status_code=201)
def create_household(body: HouseholdIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    h = _create_household(db, user, body)
    db.commit()
    return household_out(h, "owner")


@router.post("/households/demo", response_model=HouseholdOut, status_code=201)
def create_demo_household(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
                          settings: Settings = Depends(get_settings)):
    """Synthetic onboarding household. All figures and sample contracts are fictional and labelled as such."""
    from ..api_schemas import ScenarioAssumptions
    from ..services.documents import create_job, store_document
    from ..services.pdf_validation import validate_pdf
    from ..worker import enqueue_processing

    h = _create_household(db, user, HouseholdIn(
        name="Demo household (synthetic)", reporting_currency="USD", start_calendar_month=1,
        notes="SYNTHETIC DEMO DATA. All balances, flows and sample contracts are fictional."), is_demo=True)
    usd = "USD"
    db.add_all([
        Asset(household_id=h.id, kind="cash", name="Cash reserve", amount=Decimal("250000"), currency=usd),
        Asset(household_id=h.id, kind="brokerage", name="Taxable brokerage (pledged)", amount=Decimal("600000"),
              currency=usd, pledged_to_sbl=True),
        Asset(household_id=h.id, kind="non_traded_reit", name="Non-traded REIT", amount=Decimal("500000"),
              currency=usd),
        Asset(household_id=h.id, kind="interval_fund", name="Interval fund", amount=Decimal("300000"), currency=usd),
        Asset(household_id=h.id, kind="vested_rsu", name="Vested RSUs", amount=Decimal("150000"), currency=usd),
        Liability(household_id=h.id, kind="sbl", name="Securities-backed line", balance=Decimal("300000"),
                  currency=usd, annual_rate=Decimal("0.0725")),
        CashFlow(household_id=h.id, kind="income", name="Net salary", monthly_amount=Decimal("35000"), currency=usd),
        CashFlow(household_id=h.id, kind="core_expense", name="Core living costs", monthly_amount=Decimal("30000"),
                 currency=usd),
        CashFlow(household_id=h.id, kind="discretionary_expense", name="Discretionary spending",
                 monthly_amount=Decimal("15000"), currency=usd),
        ScheduledEvent(household_id=h.id, kind="capital_call", month=4, amount=Decimal("250000"), currency=usd,
                       label="Private fund capital call"),
        ScheduledEvent(household_id=h.id, kind="rsu_vest", month=2, amount=Decimal("300000"), currency=usd,
                       tax_due_month=4, label="RSU vest (tax true-up in April)"),
        ScheduledEvent(household_id=h.id, kind="reit_redemption_request", month=1, amount=Decimal("100000"),
                       currency=usd, label="REIT repurchase request"),
        ScheduledEvent(household_id=h.id, kind="interval_redemption_request", month=3, amount=Decimal("150000"),
                       currency=usd, label="Interval fund tender"),
        ScenarioDefinition(household_id=h.id, name="Demo: 25% equity drawdown", created_by=user.id,
                           description="Synthetic stress scenario. Every value is an editable assumption.",
                           assumptions=ScenarioAssumptions().model_dump()),
    ])
    db.flush()
    storage = get_storage()
    ensure_synthetic_docs(FIXTURES)
    jobs = []
    for name in SYNTHETIC_DOCS:
        data = (FIXTURES / name).read_bytes()
        doc = Document(household_id=h.id, uploaded_by=user.id, category=DEMO_CATEGORIES[name], original_filename=name,
                       safe_filename=safe_filename(name), storage_bucket=settings.storage_bucket,
                       is_demo_fixture=True, status="pending_upload")
        db.add(doc)
        db.flush()
        store_document(db, storage, doc, data, validate_pdf(data, settings))
        job, _ = create_job(db, doc, settings, f"{doc.id}:demo")
        jobs.append(job.id)
    db.commit()
    for job_id in jobs:
        enqueue_processing(job_id)
    return household_out(h, "owner")


@router.get("/households/{household_id}", response_model=HouseholdOut)
def get_household(household_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    h = require_household(db, user, household_id)
    role = member_role(db, h.id, user.id)
    return household_out(h, role)


@router.patch("/households/{household_id}", response_model=HouseholdOut)
def update_household(household_id: uuid.UUID, body: HouseholdUpdate, user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    h = require_household(db, user, household_id, "editor")
    changes = apply_updates(h, body.model_dump(exclude_unset=True))
    if changes:
        audit(db, actor_id=user.id, action="household.updated", entity_type="household", entity_id=h.id,
              household_id=h.id, details={"fields": sorted(changes)})
    db.commit()
    role = member_role(db, h.id, user.id)
    return household_out(h, role)


@router.delete("/households/{household_id}", status_code=204)
def delete_household(household_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)):

    from ..services.documents import purge_household_files
    h = require_household(db, user, household_id, "owner")
    purge_household_files(db, get_storage(), h.id)
    audit(db, actor_id=user.id, action="household.deleted", entity_type="household", entity_id=h.id)
    db.delete(h)
    db.commit()


@router.get("/households/{household_id}/summary", response_model=HouseholdSummary)
def household_summary(household_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    h = require_household(db, user, household_id)
    role = member_role(db, h.id, user.id)

    def grouped(model, kind_col, amount_col, extra=None) -> dict:
        stmt = select(kind_col, model.currency, func.sum(amount_col)).where(model.household_id == h.id)
        if extra is not None:
            stmt = stmt.where(extra)
        out: dict[str, dict[str, Decimal]] = {}
        for kind, ccy, total in db.execute(stmt.group_by(kind_col, model.currency)).all():
            out.setdefault(kind, {})[ccy] = total
        return out

    flows = grouped(CashFlow, CashFlow.kind, CashFlow.monthly_amount)
    income = flows.get("income", {})
    expenses: dict[str, Decimal] = {}
    for k in ("core_expense", "discretionary_expense"):
        for ccy, v in flows.get(k, {}).items():
            expenses[ccy] = expenses.get(ccy, Decimal(0)) + v
    count = lambda model, *where: db.scalar(select(func.count()).select_from(model).where(  # noqa: E731
        model.household_id == h.id, *where)) or 0
    latest = db.execute(select(SimulationRun, ScenarioDefinition.name)
                        .join(ScenarioDefinition, ScenarioDefinition.id == SimulationRun.scenario_id)
                        .where(SimulationRun.household_id == h.id)
                        .order_by(SimulationRun.created_at.desc()).limit(1)).first()
    latest_run = None
    if latest:
        latest_run = RunSummary.model_validate(latest[0]).model_copy(update={"scenario_name": latest[1]})
    return HouseholdSummary(
        household=household_out(h, role),
        totals_by_kind=grouped(Asset, Asset.kind, Asset.amount),
        liabilities_by_kind=grouped(Liability, Liability.kind, Liability.balance),
        monthly_income=income, monthly_expenses=expenses,
        counts={"assets": count(Asset), "liabilities": count(Liability), "cash_flows": count(CashFlow),
                "events": count(ScheduledEvent), "documents": count(Document, Document.status != "deleted"),
                "constraints_pending_review": count(ExtractedConstraint,
                                                    ExtractedConstraint.review_status == "needs_review"),
                "constraints_approved": count(ExtractedConstraint,
                                              ExtractedConstraint.review_status.in_(("confirmed", "edited"))),
                "scenarios": count(ScenarioDefinition), "runs": count(SimulationRun)},
        latest_run=latest_run)


@router.get("/households/{household_id}/audit-events", response_model=Page[AuditOut])
def audit_events(household_id: uuid.UUID, p: Pagination = Depends(), user: CurrentUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    h = require_household(db, user, household_id)
    stmt = select(AuditEvent).where(AuditEvent.household_id == h.id).order_by(AuditEvent.created_at.desc())
    rows, total = paginate(db, stmt, p)
    return Page(items=[AuditOut.model_validate(r[0]) for r in rows], total=total, limit=p.limit, offset=p.offset)
