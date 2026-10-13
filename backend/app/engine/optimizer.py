"""Prevention planner: ranked, costed options plus a linear-programme combination.

Method (stated in the UI):
1. Single-lever options - for each lever, bisection on the deterministic
   simulator finds the smallest amount that removes the shortfall on its own
   (or reports the best it can do at its cap).
2. Combined plan - `scipy.optimize.linprog` minimises total assumed cost subject
   to "ending cash >= buffer in every month". The simulator is not linear
   (gates, waterfalls, collateral calls), so per-month cash sensitivities to
   each lever are *measured* by finite differences on the simulator, the LP is
   solved on that linearisation, and the result is re-simulated. This repeats
   (sequential LP, max 5 rounds) until the re-simulated plan has no shortfall,
   then each lever is pruned to the smallest amount that still holds. Because
   the LP only sees a local linearisation, the cheapest verified single action
   is reported instead if it beats the LP combination (and labelled as such).
   The plan reported is always the re-simulated one.

Costs are explicit, editable assumptions - not market quotes.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import linprog

from .simulator import (
    ContractTerms,
    Scenario,
    price_factor,
    simulate_contract_aware,
)


@dataclass
class Lever:
    field: str
    name: str
    unit: str
    cap: Callable[[Scenario, ContractTerms], float]
    cost_per_unit: Callable[[Scenario, CostAssumptions], float]
    cost_basis: str
    constraints: str
    step: float  # finite-difference step


@dataclass
class CostAssumptions:
    """Assumed cost per $ of each action. Editable; shown in the UI."""
    sale_tax_drag: float = 0.08          # capital-gains tax + trading cost per $ sold
    cash_drag: float = 0.04              # forgone return on $ held as cash for the stress period
    reit_forgone_return: float = 0.03    # forgone REIT return vs cash, per $ redeemed early
    withholding_time_value: float = 0.01 # cost of prepaying tax via extra withholding, per $
    discretionary_weight: float = 0.25   # advisor/client preference weight per $ of spending cut


LEVERS: list[Lever] = [
    Lever("lever_rsu_extra_withholding", "Raise RSU withholding at vest", "rate pts",
          lambda s, t: max(0.0, t.rsu_max_withholding_rate - t.rsu_withholding_rate),
          lambda s, c: c.withholding_time_value * s.total_rsu_vest_value,
          "time value of prepaying tax (per $ withheld)",
          ("Capped at the maximum statutory rate (IRS Pub. 15). Needs the employer to withhold above the 22% flat "
           "rate: Meta's RSU agreement allows it at the Committee's discretion"), 0.01),
    Lever("lever_discretionary_cut", "Retime discretionary spending (months 1-6)", "$ / month",
          lambda s, t: s.monthly_discretionary,
          lambda s, c: 6 * c.discretionary_weight,
          "preference weight per $ deferred (not a market cost)",
          "Household budget only; no contractual restriction", 500.0),
    Lever("lever_rsu_window_presale", "Sell vested RSUs in the first open window", "$ sold",
          lambda s, t: s.rsu_vested,
          lambda s, c: c.sale_tax_drag,
          "tax + trading cost per $ sold",
          "Only possible while the trading window is open (insider trading policy)", 5_000.0),
    Lever("lever_reit_prestress_request", "Submit REIT repurchase request before stress", "$ requested",
          lambda s, t: s.reit,
          lambda s, c: c.reit_forgone_return,
          "forgone REIT return per $ redeemed",
          "Subject to 2% monthly / 5% quarterly caps; fills fully only while aggregate demand is below the cap",
          5_000.0),
    Lever("lever_reserve_prefund", "Pre-fund cash reserve from brokerage", "$ sold",
          lambda s, t: s.brokerage * 0.5,
          lambda s, c: c.sale_tax_drag + c.cash_drag,
          "tax + trading cost + cash drag per $ sold",
          "Selling pledged collateral raises SBL LTV - interaction captured by the simulator", 5_000.0),
    Lever("lever_sbl_paydown", "Reduce SBL balance (sell brokerage, repay loan)", "$ sold",
          lambda s, t: min(s.sbl_loan_balance, s.brokerage * 0.5),
          lambda s, c: c.sale_tax_drag,
          "tax + trading cost per $ sold (interest saved assumed ~= forgone return)",
          "Lowers LTV, reducing collateral-call size under the maintenance threshold", 5_000.0),
]


@dataclass
class PlanOption:
    name: str
    lever: str
    amount: float
    unit: str
    cost: float
    cost_basis: str
    feasible_alone: bool
    min_cash_after: float
    first_shortfall_after: Optional[int]
    liquidity_benefit: float  # improvement in minimum cash vs baseline
    constraints: str


@dataclass
class PreventionPlan:
    baseline_first_shortfall: Optional[int]
    baseline_peak_shortfall: float
    forced_liquidation_cost: float
    forced_liquidation_note: str
    options: list[PlanOption] = field(default_factory=list)
    combined: list[dict] = field(default_factory=list)
    combined_cost: float = 0.0
    combined_verified: bool = False
    combined_first_shortfall: Optional[int] = None
    combined_min_cash: float = 0.0
    combined_source: str = ""
    lp_status: str = ""
    method: str = __doc__ or ""


def _with(s: Scenario, updates: dict) -> Scenario:
    return s.model_copy(update=updates)


def _cash_path(s: Scenario, t: ContractTerms) -> np.ndarray:
    return np.array([r["ending_cash"] for r in simulate_contract_aware(s, t).rows])


def forced_liquidation_cost(s: Scenario, peak_shortfall: float) -> tuple[float, str]:
    """Cost of meeting the shortfall by selling brokerage at the trough instead of recovering."""
    trough = price_factor(s, s.months_to_trough, s.beta_brokerage)
    end = price_factor(s, s.horizon_months, s.beta_brokerage)
    locked_in = max(0.0, end / trough - 1)
    rate = locked_in + s.sale_tax_drag
    note = (f"Selling at the trough forgoes the modelled recovery to month {s.horizon_months} ({locked_in:.1%}) plus "
            f"{s.sale_tax_drag:.0%} tax/trading drag - and an unmet collateral call lets the lender choose "
            f"what to sell.")
    return peak_shortfall * rate, note


def _single_lever(s: Scenario, t: ContractTerms, lever: Lever, costs: CostAssumptions,
                  base_min: float, buffer: float) -> PlanOption:
    cap = lever.cap(s, t)
    unit_cost = lever.cost_per_unit(s, costs)

    def run(x: float):
        return simulate_contract_aware(_with(s, {lever.field: x}), t)

    at_cap = run(cap)
    feasible = at_cap.min_cash >= buffer
    if feasible:
        lo, hi = 0.0, cap
        for _ in range(30):
            mid = (lo + hi) / 2
            if run(mid).min_cash >= buffer:
                hi = mid
            else:
                lo = mid
        amount = hi
        res = run(amount)
    else:
        amount, res = cap, at_cap
    return PlanOption(
        name=lever.name, lever=lever.field, amount=amount, unit=lever.unit, cost=amount * unit_cost,
        cost_basis=lever.cost_basis, feasible_alone=feasible, min_cash_after=res.min_cash,
        first_shortfall_after=res.first_shortfall_month, liquidity_benefit=res.min_cash - base_min,
        constraints=lever.constraints)


def plan_prevention(s: Scenario, t: ContractTerms, costs: CostAssumptions | None = None,
                    buffer: float = 0.0, levers: list[Lever] | None = None) -> PreventionPlan:
    costs = costs or CostAssumptions()
    s = _with(s, {"sale_tax_drag": costs.sale_tax_drag})
    levers = levers or LEVERS
    base = simulate_contract_aware(s, t)
    flc, note = forced_liquidation_cost(s, base.peak_shortfall)
    plan = PreventionPlan(baseline_first_shortfall=base.first_shortfall_month,
                          baseline_peak_shortfall=base.peak_shortfall,
                          forced_liquidation_cost=flc, forced_liquidation_note=note)
    if base.min_cash >= buffer:
        plan.lp_status = "No shortfall in this scenario - no prevention needed."
        plan.combined_verified = True
        plan.combined_min_cash = base.min_cash
        return plan

    plan.options = sorted(
        (_single_lever(s, t, lv, costs, base.min_cash, buffer) for lv in levers),
        key=lambda o: (not o.feasible_alone, o.cost if o.feasible_alone else -o.liquidity_benefit))

    # Sequential LP on simulator-measured sensitivities
    caps = np.array([lv.cap(s, t) for lv in levers])
    unit_costs = np.array([lv.cost_per_unit(s, costs) for lv in levers])
    x = np.zeros(len(levers))
    status = "not run"
    for _ in range(5):
        cur = _with(s, {lv.field: float(v) for lv, v in zip(levers, x)})
        base_path = _cash_path(cur, t)
        if base_path.min() >= buffer - 0.5:
            break
        S = np.zeros((s.horizon_months, len(levers)))
        for j, lv in enumerate(levers):
            # Wide secant (10% of the lever's range) so threshold effects such as a collateral
            # call shifting by a month do not produce spurious local slopes.
            width = max(lv.step, 0.10 * caps[j])
            h = min(width, max(caps[j] - x[j], 0.0))
            if h <= 0:  # at cap: measure backwards
                h = -min(width, x[j]) if x[j] > 0 else 0.0
            if h == 0:
                continue
            path = _cash_path(_with(cur, {lv.field: float(x[j] + h)}), t)
            S[:, j] = (path - base_path) / h
        # cash_t + S (dx) >= buffer  ->  -S dx <= cash_t - buffer ; dx bounded by caps
        A_ub = -S
        # Same $0.50 tolerance as the shortfall detector: months already at ~$0 whose cash cannot
        # move (sensitivity ~0) must not make the LP infeasible.
        b_ub = base_path - buffer + 0.25
        bounds = [(-x[j], caps[j] - x[j]) for j in range(len(levers))]
        lp = linprog(unit_costs, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
        status = lp.message
        if not lp.success:
            break
        x = np.clip(x + lp.x, 0, caps)
    def min_cash(vec: np.ndarray) -> float:
        return simulate_contract_aware(_with(s, {lv.field: float(v) for lv, v in zip(levers, vec)}), t).min_cash

    # Prune: shrink each active lever (most expensive first) while the plan still holds.
    if min_cash(x) >= buffer - 0.5:
        for j in sorted(range(len(levers)), key=lambda j: -x[j] * unit_costs[j]):
            if x[j] <= 0:
                continue
            lo, hi = 0.0, x[j]
            for _ in range(25):
                mid = (lo + hi) / 2
                trial = x.copy()
                trial[j] = mid
                if min_cash(trial) >= buffer:
                    hi = mid
                else:
                    lo = mid
            x[j] = hi
    # The LP works on a local linearisation, so compare it with the verified single actions
    # and report the cheapest plan that actually passes re-simulation.
    plan.combined_source = "sequential linear programme (pruned)"
    lp_cost = float(x @ unit_costs) if min_cash(x) >= buffer - 0.5 else float("inf")
    best_single = min((o for o in plan.options if o.feasible_alone), key=lambda o: o.cost, default=None)
    if best_single is not None and best_single.cost < lp_cost:
        x = np.array([best_single.amount if lv.field == best_single.lever else 0.0 for lv in levers])
        plan.combined_source = (f"single action '{best_single.name}' - cheaper than the LP combination "
                                f"({'did not pass re-simulation' if lp_cost == float('inf') else f'${lp_cost:,.0f}'})")
    final_s = _with(s, {lv.field: float(v) for lv, v in zip(levers, x)})
    final = simulate_contract_aware(final_s, t)
    plan.lp_status = status
    plan.combined_verified = final.min_cash >= buffer - 1.0
    plan.combined_first_shortfall = final.first_shortfall_month
    plan.combined_min_cash = final.min_cash
    plan.combined = [
        {"lever": lv.name, "field": lv.field, "amount": float(v), "unit": lv.unit,
         "cost": float(v * c), "cost_basis": lv.cost_basis, "constraints": lv.constraints}
        for lv, v, c in zip(levers, x, unit_costs) if v > 1e-6]
    plan.combined_cost = float(sum(r["cost"] for r in plan.combined))
    return plan
