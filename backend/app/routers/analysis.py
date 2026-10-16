"""Scenarios, simulation runs, reverse stress, prevention planning and recommendation decisions."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import (
    ApplyOut,
    AssumptionField,
    BlindSpotOut,
    BlindSpotSummary,
    MonthOut,
    Page,
    PreventionOut,
    PreventionRequest,
    RecommendationDecision,
    RecommendationOut,
    RunDetail,
    RunSummary,
    ScenarioAssumptions,
    ScenarioDefaults,
    ScenarioIn,
    ScenarioOut,
    ScenarioUpdate,
    StressOut,
    StressRequest,
)
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import require_household, require_owned
from ..config import Settings, get_settings
from ..db import get_db
from ..engine.optimizer import CostAssumptions
from ..errors import ApiError
from ..models import (
    BlindSpotReport,
    Household,
    PreventionPlan,
    PreventionRecommendation,
    ScenarioDefinition,
    SimulationMonth,
    SimulationRun,
    StressResult,
)
from ..ratelimit import check_rate
from ..services.analysis import run_blind_spots, run_prevention, run_simulation, run_stress
from ..services.engine_adapter import term_rows
from .common import Pagination, apply_updates, paginate

router = APIRouter(tags=["analysis"])

FIELDS: list[tuple[str, str, str, str, str]] = [
    ("horizon_months", "Projection length", "Horizon", "months", "Months simulated (24 by default)."),
    ("equity_drawdown", "Equity drawdown at trough", "Market stress", "percent", "Peak-to-trough fall of equities."),
    ("months_to_trough", "Months to trough", "Market stress", "months", "Linear decline over this many months."),
    ("trough_hold_months", "Months held at trough", "Market stress", "months", "Months the trough persists."),
    ("recovery_share", "Drawdown recovered by end", "Market stress", "percent",
     "Share of the drawdown recovered by the final month."),
    ("beta_brokerage", "Brokerage beta", "Asset sensitivity", "number", "Sensitivity to the equity drawdown."),
    ("beta_rsu", "Employer stock beta", "Asset sensitivity", "number", "Sensitivity of vested/vesting RSUs."),
    ("beta_reit_nav", "REIT NAV beta", "Asset sensitivity", "number", "Sensitivity of the REIT's reported NAV."),
    ("beta_interval_nav", "Interval fund NAV beta", "Asset sensitivity", "number", "Sensitivity of interval fund NAV."),
    ("reit_base_demand_pct", "REIT redemption demand (no stress)", "Fund demand", "number",
     "Aggregate repurchase requests from all investors, % of NAV per month. Not disclosed by the prospectus."),
    ("reit_demand_sensitivity", "REIT demand per 100% drawdown", "Fund demand", "number",
     "Extra % of NAV requested per month for each 100% of equity drawdown (assumption)."),
    ("reit_board_fill_factor", "Share of cap the board fills", "Fund demand", "percent",
     "The board may repurchase fewer shares than the caps or none; 100% means it fills up to the caps."),
    ("interval_base_demand_pct", "Interval tender demand (no stress)", "Fund demand", "number",
     "Aggregate tenders as % of shares per offer."),
    ("interval_demand_sensitivity", "Interval demand per 100% drawdown", "Fund demand", "number",
     "Extra % of shares tendered per 100% equity drawdown."),
    ("reit_shares_held_over_one_year", "REIT shares held over one year", "Fund demand", "boolean",
     "If not, the early repurchase deduction applies."),
    ("rsu_effective_tax_rate", "Effective tax rate on RSU income", "Tax", "percent",
     "Combined marginal rate; the gap above withholding is paid in cash at the tax due month."),
    ("rsu_window_months", "RSU trading-window months", "Household behaviour", "list",
     "Projection months when vested shares may be sold."),
    ("rsu_window_cash_floor_months", "Cash floor kept via RSU sales", "Household behaviour", "months",
     "In an open window, sell vested RSUs to hold this many months of net spending in cash."),
    ("sale_tax_drag", "Tax and trading cost per $ sold", "Costs", "percent", "Applied to securities sales."),
    ("naive_liquid_fraction", "Naive baseline liquid fractions", "Naive baseline", "percent",
     "Fixed share of each asset the simplified comparator treats as instantly saleable."),
    ("lever_reserve_prefund", "Pre-fund cash from brokerage", "Prevention levers", "money", "Sold before the stress."),
    ("lever_sbl_paydown", "SBL paydown from brokerage sale", "Prevention levers", "money", "Sold to repay the line."),
    ("lever_rsu_extra_withholding", "Extra RSU withholding", "Prevention levers", "percent",
     "Added to the default withholding rate, capped at the maximum election."),
    ("lever_rsu_window_presale", "RSUs sold in first window", "Prevention levers", "money", "Planned sale."),
    ("lever_discretionary_cut", "Discretionary cut (months 1-6)", "Prevention levers", "money", "Per month."),
    ("lever_reit_prestress_request", "REIT request before stress", "Prevention levers", "money",
     "Submitted at month 0 under normal demand; still subject to the fund caps."),
]


def _scenario(db: Session, user: CurrentUser, scenario_id: uuid.UUID, role: str = "viewer"
              ) -> tuple[ScenarioDefinition, Household]:
    s = require_owned(db, user, ScenarioDefinition, scenario_id, role, "Scenario")
    household = db.get(Household, s.household_id)
    if household is None:
        raise ApiError(404, "not_found", "Household not found.")
    return s, household


@router.get("/scenario-defaults", response_model=ScenarioDefaults)
def scenario_defaults(user: CurrentUser = Depends(get_current_user)):
    return ScenarioDefaults(assumptions=ScenarioAssumptions(),
                            fields=[AssumptionField(key=k, label=lb, group=g, kind=kd, help=h)  # type: ignore[arg-type]
                                    for k, lb, g, kd, h in FIELDS])


PRESETS: list[dict] = [
    {"id": "mild_correction", "name": "Mild correction (10% drawdown)",
     "description": "Equities fall 10% over 3 months; REIT board fills up to the caps.",
     "overrides": {"equity_drawdown": 0.10}},
    {"id": "drawdown_2022", "name": "2022-style drawdown (25%)",
     "description": "Equities fall 25% over 3 months and stay low for 9 months; REIT board fills up to the caps.",
     "overrides": {"equity_drawdown": 0.25}},
    {"id": "severe", "name": "Severe drawdown (40%)",
     "description": "Equities fall 40% over 3 months with elevated redemption demand.",
     "overrides": {"equity_drawdown": 0.40, "reit_demand_sensitivity": 70.0}},
    {"id": "reit_board_halves", "name": "25% drawdown, REIT board repurchases half the cap",
     "description": "Uses the board's documented discretion to repurchase fewer shares than the limits allow.",
     "overrides": {"equity_drawdown": 0.25, "reit_board_fill_factor": 0.5}},
    {"id": "reit_suspended", "name": "25% drawdown, REIT repurchases suspended",
     "description": "The board exercises its discretion to repurchase none; interval-fund offers continue.",
     "overrides": {"equity_drawdown": 0.25, "reit_board_fill_factor": 0.0}},
]


@router.get("/scenario-presets")
def scenario_presets(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """Named stress scenarios. Every value is a modelling assumption; redemption fulfilment is never guaranteed."""
    base = ScenarioAssumptions().model_dump(mode="json")
    return [{**p, "assumptions": ScenarioAssumptions.model_validate({**base, **p["overrides"]}).model_dump(),
             "label": "Scenario assumption - not a contract term or forecast"} for p in PRESETS]


@router.get("/households/{household_id}/scenarios", response_model=list[ScenarioOut])
def list_scenarios(household_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    require_household(db, user, household_id)
    return db.scalars(select(ScenarioDefinition).where(ScenarioDefinition.household_id == household_id,
                                                       ScenarioDefinition.archived_at.is_(None))
                      .order_by(ScenarioDefinition.created_at.desc())).all()


@router.post("/households/{household_id}/scenarios", response_model=ScenarioOut, status_code=201)
def create_scenario(household_id: uuid.UUID, body: ScenarioIn, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    require_household(db, user, household_id, "editor")
    s = ScenarioDefinition(household_id=household_id, name=body.name, description=body.description,
                           assumptions=body.assumptions.model_dump(mode="json"), created_by=user.id)
    db.add(s)
    db.flush()
    audit(db, actor_id=user.id, action="scenario.created", entity_type="scenario", entity_id=s.id,
          household_id=household_id)
    db.commit()
    return s


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
def get_scenario(scenario_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _scenario(db, user, scenario_id)[0]


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioOut)
def update_scenario(scenario_id: uuid.UUID, body: ScenarioUpdate, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    s, _ = _scenario(db, user, scenario_id, "editor")
    data = body.model_dump(exclude_unset=True)
    if "assumptions" in data and data["assumptions"] is not None:
        data["assumptions"] = body.assumptions.model_dump(mode="json")  # type: ignore[union-attr]
    changes = apply_updates(s, data)
    if changes:
        audit(db, actor_id=user.id, action="scenario.updated", entity_type="scenario", entity_id=s.id,
              household_id=s.household_id, details={"fields": sorted(changes)})
    db.commit()
    return s


@router.delete("/scenarios/{scenario_id}", status_code=204)
def archive_scenario(scenario_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Scenarios are archived (not hard-deleted) so saved runs remain reproducible."""
    s, _ = _scenario(db, user, scenario_id, "editor")
    s.archived_at = datetime.now(UTC)
    audit(db, actor_id=user.id, action="scenario.archived", entity_type="scenario", entity_id=s.id,
          household_id=s.household_id)
    db.commit()


# ----------------------------------------------------------------------------- runs

def run_summary(run: SimulationRun, name: str) -> RunSummary:
    return RunSummary.model_validate(run).model_copy(update={"scenario_name": name})


def run_detail(db: Session, run: SimulationRun) -> RunDetail:
    name = db.scalar(select(ScenarioDefinition.name).where(ScenarioDefinition.id == run.scenario_id)) or ""
    months = db.scalars(select(SimulationMonth).where(SimulationMonth.run_id == run.id)
                        .order_by(SimulationMonth.model, SimulationMonth.month)).all()
    return RunDetail(**run_summary(run, name).model_dump(), explanation=run.explanation or {},
                     inputs_snapshot=run.inputs_snapshot,
                     household_snapshot=run.household_snapshot, terms=term_rows(run.terms_snapshot),
                     constraint_versions=run.constraint_versions,
                     months=[MonthOut.model_validate(m) for m in months])


@router.post("/scenarios/{scenario_id}/runs", response_model=RunDetail, status_code=201)
def create_run(scenario_id: uuid.UUID, idempotency_key: Optional[str] = Header(None, max_length=100),
               user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)):
    s, h = _scenario(db, user, scenario_id, "editor")
    if idempotency_key:
        prior = db.scalar(select(SimulationRun).where(SimulationRun.household_id == h.id,
                                                      SimulationRun.idempotency_key == idempotency_key))
        if prior is not None:
            return run_detail(db, prior)
    check_rate(str(user.id), "compute", settings.rate_limit_compute_per_minute, 60)
    run = run_simulation(db, h, s, user.id)
    run.idempotency_key = idempotency_key
    audit(db, actor_id=user.id, action="simulation.run", entity_type="simulation_run", entity_id=run.id,
          household_id=h.id, details={"scenario_id": str(s.id), "engine_version": run.engine_version})
    db.commit()
    return run_detail(db, run)


@router.get("/households/{household_id}/runs", response_model=Page[RunSummary])
def list_runs(household_id: uuid.UUID, scenario_id: Optional[uuid.UUID] = None, p: Pagination = Depends(),
              user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_household(db, user, household_id)
    stmt = (select(SimulationRun, ScenarioDefinition.name)
            .join(ScenarioDefinition, ScenarioDefinition.id == SimulationRun.scenario_id)
            .where(SimulationRun.household_id == household_id))
    if scenario_id:
        stmt = stmt.where(SimulationRun.scenario_id == scenario_id)
    rows, total = paginate(db, stmt.order_by(SimulationRun.created_at.desc()), p)
    return Page(items=[run_summary(r, n) for r, n in rows], total=total, limit=p.limit, offset=p.offset)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return run_detail(db, require_owned(db, user, SimulationRun, run_id, label="Simulation run"))


# ----------------------------------------------------------------------------- reverse stress

@router.post("/scenarios/{scenario_id}/stress", response_model=StressOut, status_code=201)
def create_stress(scenario_id: uuid.UUID, body: StressRequest, user: CurrentUser = Depends(get_current_user),
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    s, h = _scenario(db, user, scenario_id, "editor")
    check_rate(str(user.id), "compute", settings.rate_limit_compute_per_minute, 60)
    res = run_stress(db, h, s, user.id, body.max_drawdown, body.step, body.tolerance)
    db.flush()
    audit(db, actor_id=user.id, action="stress.run", entity_type="stress_result", entity_id=res.id,
          household_id=h.id, details={"found": res.found})
    db.commit()
    return res


@router.get("/households/{household_id}/stress-results", response_model=Page[StressOut])
def list_stress(household_id: uuid.UUID, scenario_id: Optional[uuid.UUID] = None, p: Pagination = Depends(),
                user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_household(db, user, household_id)
    stmt = select(StressResult).where(StressResult.household_id == household_id)
    if scenario_id:
        stmt = stmt.where(StressResult.scenario_id == scenario_id)
    rows, total = paginate(db, stmt.order_by(StressResult.created_at.desc()), p)
    return Page(items=[StressOut.model_validate(r[0]) for r in rows], total=total, limit=p.limit, offset=p.offset)


@router.get("/stress-results/{result_id}", response_model=StressOut)
def get_stress(result_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return require_owned(db, user, StressResult, result_id, label="Stress result")


# ----------------------------------------------------------------------------- blind spots

@router.post("/scenarios/{scenario_id}/blind-spots", response_model=BlindSpotOut, status_code=201)
def create_blind_spots(scenario_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Run the fixed, deterministic stress battery and rank liquidity risks (see services/blind_spots)."""
    s, h = _scenario(db, user, scenario_id, "editor")
    check_rate(str(user.id), "compute", settings.rate_limit_compute_per_minute, 60)
    rep = run_blind_spots(db, h, s, user.id)
    db.flush()
    audit(db, actor_id=user.id, action="blind_spots.run", entity_type="blind_spot_report", entity_id=rep.id,
          household_id=h.id, details={"risks": rep.risk_count, "blind_spots": rep.blind_spot_count})
    db.commit()
    return rep


@router.get("/households/{household_id}/blind-spot-reports", response_model=Page[BlindSpotSummary])
def list_blind_spots(household_id: uuid.UUID, scenario_id: Optional[uuid.UUID] = None, p: Pagination = Depends(),
                     user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_household(db, user, household_id)
    stmt = select(BlindSpotReport).where(BlindSpotReport.household_id == household_id)
    if scenario_id:
        stmt = stmt.where(BlindSpotReport.scenario_id == scenario_id)
    rows, total = paginate(db, stmt.order_by(BlindSpotReport.created_at.desc()), p)
    return Page(items=[BlindSpotSummary.model_validate(r[0]) for r in rows], total=total, limit=p.limit,
                offset=p.offset)


@router.get("/blind-spot-reports/{report_id}", response_model=BlindSpotOut)
def get_blind_spots(report_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return require_owned(db, user, BlindSpotReport, report_id, label="Blind-spot report")


# ----------------------------------------------------------------------------- prevention

def plan_out(plan: PreventionPlan) -> PreventionOut:
    return PreventionOut.model_validate(plan)


@router.post("/scenarios/{scenario_id}/prevention", response_model=PreventionOut, status_code=201)
def create_prevention(scenario_id: uuid.UUID, body: PreventionRequest, user: CurrentUser = Depends(get_current_user),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    s, h = _scenario(db, user, scenario_id, "editor")
    check_rate(str(user.id), "compute", settings.rate_limit_compute_per_minute, 60)
    plan = run_prevention(db, h, s, user.id, CostAssumptions(**body.costs.model_dump()), body.cash_buffer)
    audit(db, actor_id=user.id, action="prevention.run", entity_type="prevention_plan", entity_id=plan.id,
          household_id=h.id, details={"verified": plan.combined_verified})
    db.commit()
    db.refresh(plan)
    return plan_out(plan)


@router.get("/households/{household_id}/prevention-plans", response_model=Page[PreventionOut])
def list_plans(household_id: uuid.UUID, scenario_id: Optional[uuid.UUID] = None, p: Pagination = Depends(),
               user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_household(db, user, household_id)
    stmt = select(PreventionPlan).where(PreventionPlan.household_id == household_id)
    if scenario_id:
        stmt = stmt.where(PreventionPlan.scenario_id == scenario_id)
    rows, total = paginate(db, stmt.order_by(PreventionPlan.created_at.desc()), p)
    return Page(items=[plan_out(r[0]) for r in rows], total=total, limit=p.limit, offset=p.offset)


@router.get("/prevention-plans/{plan_id}", response_model=PreventionOut)
def get_plan(plan_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return plan_out(require_owned(db, user, PreventionPlan, plan_id, label="Prevention plan"))


@router.post("/recommendations/{rec_id}/decision", response_model=RecommendationOut)
def decide_recommendation(rec_id: uuid.UUID, body: RecommendationDecision,
                          user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = require_owned(db, user, PreventionRecommendation, rec_id, "editor", "Recommendation")
    rec.status, rec.decided_by, rec.decided_at = body.decision, user.id, datetime.now(UTC)
    audit(db, actor_id=user.id, action=f"recommendation.{body.decision}", entity_type="recommendation",
          entity_id=rec.id, household_id=rec.household_id, details={"lever": rec.lever})
    db.commit()
    return rec


@router.post("/recommendations/{rec_id}/apply", response_model=ApplyOut, status_code=201)
def apply_recommendation(rec_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Create a new scenario with an approved recommendation applied (combined plans apply all their levers)."""
    rec = require_owned(db, user, PreventionRecommendation, rec_id, "editor", "Recommendation")
    if rec.status != "approved":
        raise ApiError(409, "conflict", "Approve the recommendation before applying it.")
    plan = db.get(PreventionPlan, rec.plan_id)
    base = db.get(ScenarioDefinition, plan.scenario_id) if plan else None
    if plan is None or base is None:
        raise ApiError(404, "not_found", "The originating scenario no longer exists.")
    assumptions = dict(base.assumptions)
    levers = ([r for r in plan.recommendations if r.kind == "combined"] if rec.kind == "combined" else [rec])
    for r in levers:
        assumptions[r.lever] = float(r.amount)
    validated = ScenarioAssumptions.model_validate(assumptions).model_dump(mode="json")
    suffix = "optimised plan" if rec.kind == "combined" else rec.name
    s = ScenarioDefinition(household_id=base.household_id, name=f"{base.name} + {suffix}"[:160],
                           description=f"Created from prevention plan {plan.id} (approved by user).",
                           assumptions=validated, created_by=user.id)
    db.add(s)
    db.flush()
    audit(db, actor_id=user.id, action="recommendation.applied", entity_type="scenario", entity_id=s.id,
          household_id=s.household_id, details={"recommendation_id": str(rec.id)})
    db.commit()
    return ApplyOut(scenario=ScenarioOut.model_validate(s))
