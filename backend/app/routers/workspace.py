"""Cross-household workspace views for the signed-in advisor: review queue and scenario list.

Only rows the caller could already open individually are returned: household terms where the caller is an
editor or owner, library terms where the caller is a reviewer or admin of the fund's firm.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import (
    ExportOut,
    ReportBlindSpotItem,
    ReportExportItem,
    ReportsOut,
    ReviewItem,
    ReviewQueueOut,
    ScenarioListItem,
)
from ..auth import CurrentUser, get_current_user
from ..db import get_db
from ..models import (
    BlindSpotReport,
    Document,
    ExportRecord,
    ExtractedConstraint,
    FirmMember,
    Fund,
    Household,
    HouseholdMember,
    ScenarioDefinition,
    SimulationRun,
)
from .constraints import constraint_out

router = APIRouter(tags=["workspace"])


@router.get("/me/review-queue", response_model=ReviewQueueOut)
def review_queue(limit: int = Query(200, ge=1, le=500), user: CurrentUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    household_rows = db.execute(
        select(ExtractedConstraint, Document.safe_filename, Household.id, Household.name)
        .join(Document, Document.id == ExtractedConstraint.document_id)
        .join(Household, Household.id == ExtractedConstraint.household_id)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(HouseholdMember.user_id == user.id, HouseholdMember.role.in_(("editor", "owner")),
               ExtractedConstraint.review_status == "needs_review", Document.status != "deleted")
        .order_by(ExtractedConstraint.created_at)).all()
    library_rows = db.execute(
        select(ExtractedConstraint, Document.safe_filename, Fund.id, Fund.name)
        .join(Document, Document.id == ExtractedConstraint.document_id)
        .join(Fund, Fund.id == ExtractedConstraint.fund_id)
        .join(FirmMember, FirmMember.firm_id == Fund.firm_id)
        .where(FirmMember.user_id == user.id, FirmMember.role.in_(("reviewer", "admin")),
               ExtractedConstraint.review_status == "needs_review", Document.status != "deleted")
        .order_by(ExtractedConstraint.created_at)).all()
    items = ([ReviewItem(constraint=constraint_out(c, doc), owner_type="household", owner_id=oid, owner_name=name)
              for c, doc, oid, name in household_rows]
             + [ReviewItem(constraint=constraint_out(c, doc), owner_type="fund", owner_id=oid, owner_name=name)
                for c, doc, oid, name in library_rows])
    return ReviewQueueOut(items=items[:limit], total=len(items), household_items=len(household_rows),
                          library_items=len(library_rows))


@router.get("/me/scenarios", response_model=list[ScenarioListItem])
def my_scenarios(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(ScenarioDefinition, Household.name)
        .join(Household, Household.id == ScenarioDefinition.household_id)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(HouseholdMember.user_id == user.id, ScenarioDefinition.archived_at.is_(None))
        .order_by(ScenarioDefinition.updated_at.desc())).all()
    latest: dict = {}
    if rows:
        for r in db.scalars(select(SimulationRun).where(
                SimulationRun.scenario_id.in_([s.id for s, _ in rows])).order_by(SimulationRun.created_at)):
            latest[r.scenario_id] = r
    out = []
    for s, hname in rows:
        run = latest.get(s.id)
        summary = run.aware_summary if run else {}
        out.append(ScenarioListItem(
            id=s.id, name=s.name, household_id=s.household_id, household_name=hname, updated_at=s.updated_at,
            latest_run_id=run.id if run else None, latest_run_at=run.created_at if run else None,
            latest_first_shortfall_month=summary.get("first_shortfall_month"),
            latest_peak_shortfall=Decimal(str(summary["peak_shortfall"])) if "peak_shortfall" in summary else None))
    return out


@router.get("/me/reports", response_model=ReportsOut)
def my_reports(limit: int = Query(100, ge=1, le=500), user: CurrentUser = Depends(get_current_user),
               db: Session = Depends(get_db)):
    member = select(HouseholdMember.household_id).where(HouseholdMember.user_id == user.id)
    exports = db.execute(
        select(ExportRecord, Household.name).join(Household, Household.id == ExportRecord.household_id)
        .where(ExportRecord.household_id.in_(member)).order_by(ExportRecord.created_at.desc()).limit(limit)).all()
    reports = db.execute(
        select(BlindSpotReport, Household.name, ScenarioDefinition.name)
        .join(Household, Household.id == BlindSpotReport.household_id)
        .join(ScenarioDefinition, ScenarioDefinition.id == BlindSpotReport.scenario_id)
        .where(BlindSpotReport.household_id.in_(member)).order_by(BlindSpotReport.created_at.desc()).limit(limit)).all()
    return ReportsOut(
        exports=[ReportExportItem(**ExportOut.model_validate(e).model_dump(), household_name=h) for e, h in exports],
        blind_spot_reports=[ReportBlindSpotItem(**ReportBlindSpotItem.model_validate(
            {**{c: getattr(r, c) for c in ("id", "household_id", "scenario_id", "engine_version", "as_of_date",
                                           "risk_count", "blind_spot_count", "created_at")},
             "household_name": h, "scenario_name": sn}).model_dump()) for r, h, sn in reports])
