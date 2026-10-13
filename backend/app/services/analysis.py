"""Simulation, reverse-stress and prevention runs, persisted with everything needed to reproduce them."""
from __future__ import annotations

import uuid
from dataclasses import asdict
from decimal import Decimal

from sqlalchemy.orm import Session

from ..engine.optimizer import CostAssumptions, plan_prevention
from ..engine.reverse_stress import reverse_stress
from ..engine.simulator import (
    ENGINE_VERSION,
    SimulationResult,
    simulate_contract_aware,
    simulate_naive,
    stress_usable_liquidity,
)
from ..models import (
    Household,
    PreventionPlan,
    PreventionRecommendation,
    ScenarioDefinition,
    SimulationMonth,
    SimulationRun,
    StressResult,
)
from .engine_adapter import build_inputs, terms_snapshot


def D(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(float(x), 2)))


def _summary(r: SimulationResult) -> dict:
    return {"model": r.model, "first_shortfall_month": r.first_shortfall_month,
            "shortfall_amount": round(r.shortfall_amount, 2), "peak_shortfall": round(r.peak_shortfall, 2),
            "min_cash": round(r.min_cash, 2)}


def _month_rows(run_id: uuid.UUID, r: SimulationResult) -> list[SimulationMonth]:
    out = []
    for row in r.rows:
        if r.model == "contract_aware":
            requested = row["reit_requested"]
            redemption = row["reit_proceeds"] + row["interval_proceeds"]
            other = row["rsu_sale_proceeds"] + row["brokerage_sale_proceeds"] + row["sbl_draw"]
            fill = row["reit_fill_rate"]
        else:
            requested, redemption, other, fill = 0.0, 0.0, row.get("asset_sales", 0.0), None
        out.append(SimulationMonth(
            run_id=run_id, model=r.model, month=row["month"], label=row["label"],
            beginning_cash=D(row["beginning_cash"]), income=D(row["income"]), expenses=D(row["expenses"]),
            taxes=D(row["taxes"]), debt_service=D(row["debt_service"]), collateral_call=D(row["collateral_call"]),
            capital_call=D(row["capital_call"]), redemption_requested=D(requested),
            redemption_proceeds=D(redemption), other_proceeds=D(other), ending_cash=D(row["ending_cash"]),
            shortfall=D(row["shortfall"]), reit_fill_rate=None if fill is None else Decimal(str(round(fill, 6))),
            binding_constraints=list(row["binding_constraints"])))
    return out


def run_simulation(db: Session, household: Household, scenario: ScenarioDefinition,
                   user_id: uuid.UUID) -> SimulationRun:
    inputs = build_inputs(db, household, scenario)
    naive = simulate_naive(inputs.scenario, inputs.terms)
    aware = simulate_contract_aware(inputs.scenario, inputs.terms)
    liq = stress_usable_liquidity(inputs.scenario, inputs.terms, 3)
    run = SimulationRun(
        id=uuid.uuid4(), household_id=household.id, scenario_id=scenario.id, created_by=user_id,
        engine_version=ENGINE_VERSION, reporting_currency=household.reporting_currency,
        horizon_months=inputs.scenario.horizon_months, inputs_snapshot=inputs.assumptions.model_dump(),
        household_snapshot=inputs.household_snapshot, terms_snapshot=terms_snapshot(inputs.terms),
        constraint_versions=inputs.constraint_versions, naive_summary=_summary(naive), aware_summary=_summary(aware),
        liquidity={k: (round(v, 2) if isinstance(v, float) else v) for k, v in liq.items()},
        warnings=inputs.warnings)
    db.add(run)
    db.add_all(_month_rows(run.id, naive) + _month_rows(run.id, aware))
    return run


def run_stress(db: Session, household: Household, scenario: ScenarioDefinition, user_id: uuid.UUID,
               max_drawdown: float, step: float, tolerance: float) -> StressResult:
    inputs = build_inputs(db, household, scenario)
    r = reverse_stress(inputs.scenario, inputs.terms, max_drawdown=max_drawdown, step=step, tol=tolerance)
    res = StressResult(
        household_id=household.id, scenario_id=scenario.id, created_by=user_id, engine_version=ENGINE_VERSION,
        inputs_snapshot=inputs.assumptions.model_dump(), terms_snapshot=terms_snapshot(inputs.terms),
        search={"parameter": "equity_drawdown", "max_drawdown": max_drawdown, "step": step, "tolerance": tolerance,
                "grid": [{**g, "min_cash": round(g["min_cash"], 2)} for g in r.grid],
                "evaluations": len(r.grid), "warnings": inputs.warnings},
        found=r.found,
        boundary_drawdown=None if r.boundary_drawdown is None else Decimal(str(round(r.boundary_drawdown, 6))),
        last_safe_drawdown=None if r.last_safe_drawdown is None else Decimal(str(round(r.last_safe_drawdown, 6))),
        first_shortfall_month=r.first_shortfall_month, shortfall_amount=D(r.shortfall_amount),
        grid_monotone=r.grid_monotone, method=r.method, binding_constraints=list(r.binding_constraints),
        attribution=[{k: (round(v, 2) if isinstance(v, float) else v) for k, v in a.items()} for a in r.attribution],
        key_events=[{k: (round(v, 2) if isinstance(v, float) else v) for k, v in e.items()} for e in r.key_events])
    db.add(res)
    return res


def run_prevention(db: Session, household: Household, scenario: ScenarioDefinition, user_id: uuid.UUID,
                   costs: CostAssumptions, buffer: float) -> PreventionPlan:
    inputs = build_inputs(db, household, scenario)
    p = plan_prevention(inputs.scenario, inputs.terms, costs, buffer=buffer)
    plan = PreventionPlan(
        id=uuid.uuid4(), household_id=household.id, scenario_id=scenario.id, created_by=user_id,
        engine_version=ENGINE_VERSION, inputs_snapshot=inputs.assumptions.model_dump(),
        terms_snapshot=terms_snapshot(inputs.terms), cost_assumptions=asdict(costs),
        baseline_first_shortfall=p.baseline_first_shortfall, baseline_peak_shortfall=D(p.baseline_peak_shortfall),
        forced_liquidation_cost=D(p.forced_liquidation_cost), forced_liquidation_note=p.forced_liquidation_note,
        combined_cost=D(p.combined_cost), combined_verified=p.combined_verified,
        combined_source=p.combined_source or "not needed", combined_min_cash=D(p.combined_min_cash),
        combined_first_shortfall=p.combined_first_shortfall, lp_status=p.lp_status, method=p.method)
    db.add(plan)
    recs = [PreventionRecommendation(
        plan_id=plan.id, household_id=household.id, rank=i + 1, kind="single", lever=o.lever, name=o.name,
        amount=Decimal(str(round(o.amount, 6))), unit=o.unit, cost=D(o.cost), cost_basis=o.cost_basis,
        liquidity_benefit=D(o.liquidity_benefit), min_cash_after=D(o.min_cash_after),
        first_shortfall_after=o.first_shortfall_after, feasible_alone=o.feasible_alone,
        constraints_note=o.constraints) for i, o in enumerate(p.options)]
    recs += [PreventionRecommendation(
        plan_id=plan.id, household_id=household.id, rank=i + 1, kind="combined", lever=c["field"], name=c["lever"],
        amount=Decimal(str(round(c["amount"], 6))), unit=c["unit"], cost=D(c["cost"]), cost_basis=c["cost_basis"],
        liquidity_benefit=None, min_cash_after=D(p.combined_min_cash), first_shortfall_after=p.combined_first_shortfall,
        feasible_alone=None, constraints_note=c["constraints"]) for i, c in enumerate(p.combined)]
    db.add_all(recs)
    return plan
