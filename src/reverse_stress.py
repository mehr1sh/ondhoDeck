"""Reverse stress test: the mildest equity drawdown that makes household cash negative.

Method (stated in the UI): evaluate the deterministic simulator on a uniform
drawdown grid, take the first grid point that fails, then bisect between it and
the last passing point. Because fund demand, collateral values and RSU prices
all move with the drawdown, the pass/fail outcome is usually - but not provably -
monotone in severity; we report whether the grid itself was monotone. If not,
the result is "the first failing grid point", not a mathematically exact boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from .simulator import (
    RELAXATIONS, ContractTerms, Scenario, SimulationResult, simulate_contract_aware,
)


@dataclass
class ReverseStressResult:
    found: bool
    method: str
    boundary_drawdown: Optional[float] = None   # least severe failing drawdown found
    last_safe_drawdown: Optional[float] = None
    first_shortfall_month: Optional[int] = None
    shortfall_amount: float = 0.0
    binding_constraints: list[str] = field(default_factory=list)
    attribution: list[dict] = field(default_factory=list)
    key_events: list[dict] = field(default_factory=list)
    grid: list[dict] = field(default_factory=list)
    grid_monotone: bool = True
    boundary_result: Optional[SimulationResult] = None


def _run(s: Scenario, t: ContractTerms, d: float) -> SimulationResult:
    return simulate_contract_aware(s.model_copy(update={"equity_drawdown": d}), t)


def attribute_shortfall(s: Scenario, t: ContractTerms) -> list[dict]:
    """Counterfactual attribution: re-run with each contractual rule relaxed in turn."""
    base = simulate_contract_aware(s, t)
    out = []
    for key, label in RELAXATIONS.items():
        alt = simulate_contract_aware(s, replace(t, relax=frozenset({key})))
        out.append({
            "constraint": label, "relaxation": key,
            "peak_shortfall_with_rule": base.peak_shortfall,
            "peak_shortfall_without_rule": alt.peak_shortfall,
            "shortfall_reduction": base.peak_shortfall - alt.peak_shortfall,
            "first_shortfall_month_without_rule": alt.first_shortfall_month,
            "removes_shortfall": base.has_shortfall and not alt.has_shortfall,
        })
    out.sort(key=lambda r: -r["shortfall_reduction"])
    return out


def key_events(res: SimulationResult, up_to: int) -> list[dict]:
    events = []
    for r in res.rows[:up_to]:
        events.append({
            "month": r["label"], "beginning_cash": r["beginning_cash"],
            "net_household_flow": r["income"] - r["expenses"] - r["debt_service"],
            "capital_call": -r["capital_call"], "taxes": -r["taxes"],
            "collateral_call": -r["collateral_call"],
            "fund_proceeds": r["reit_proceeds"] + r["interval_proceeds"],
            "other_sales_and_draws": r["rsu_sale_proceeds"] + r["brokerage_sale_proceeds"] + r["sbl_draw"],
            "ending_cash": r["ending_cash"],
            "binding": "; ".join(r["binding_constraints"]),
        })
    return events


def reverse_stress(s: Scenario, t: ContractTerms, max_drawdown: float = 0.60,
                   step: float = 0.01, tol: float = 0.0005) -> ReverseStressResult:
    n = int(round(max_drawdown / step))
    grid = []
    for i in range(n + 1):
        d = round(i * step, 6)
        r = _run(s, t, d)
        grid.append({"equity_drawdown": d, "min_cash": r.min_cash, "fails": r.has_shortfall,
                     "first_shortfall_month": r.first_shortfall_month})
    fails = [g["fails"] for g in grid]
    first_fail = next((i for i, f in enumerate(fails) if f), None)
    monotone = first_fail is None or all(fails[first_fail:])
    method = (f"Grid search over equity drawdown 0-{max_drawdown:.0%} in {step:.0%} steps, then bisection "
              f"to {tol:.2%} between the last passing and first failing grid points.")
    if not monotone:
        method += (" Pass/fail was NOT monotone on the grid, so this is the first failing point "
                   "found, not a guaranteed exact boundary.")
    if first_fail is None:
        return ReverseStressResult(found=False, method=method, grid=grid, grid_monotone=monotone,
                                   last_safe_drawdown=max_drawdown)
    if first_fail == 0:
        lo, hi = None, 0.0
    else:
        lo, hi = grid[first_fail - 1]["equity_drawdown"], grid[first_fail]["equity_drawdown"]
        while hi - lo > tol:
            mid = (lo + hi) / 2
            if _run(s, t, mid).has_shortfall:
                hi = mid
            else:
                lo = mid
    res = _run(s, t, hi)
    at_boundary = s.model_copy(update={"equity_drawdown": hi})
    fm = res.first_shortfall_month
    return ReverseStressResult(
        found=True, method=method, boundary_drawdown=hi, last_safe_drawdown=lo,
        first_shortfall_month=fm, shortfall_amount=res.shortfall_amount,
        binding_constraints=res.binding_in(fm), attribution=attribute_shortfall(at_boundary, t),
        key_events=key_events(res, fm), grid=grid, grid_monotone=monotone, boundary_result=res)
