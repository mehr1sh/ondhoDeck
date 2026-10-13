"""Deterministic 24-month household liquidity simulator.

No LLM is involved here. Inputs are:

* `Scenario` - the synthetic household, its scheduled obligations, the market
  stress path and every modelling assumption (all editable, all labelled).
* `ContractTerms` - numeric contract rules, built from reviewed
  `ContractConstraint`s with a provenance note for every field.

Two models are provided:

* `simulate_contract_aware` - applies fund gates (monthly + remaining quarterly
  capacity, pro-rata fills, settlement lags), interval-fund offer windows, SBL
  collateral calls, RSU trading windows and the RSU withholding gap.
* `simulate_naive` - a deliberately simplified comparator: treats a fixed
  fraction of each asset as instantly liquid, ignores fund gates, collateral
  calls and the RSU withholding gap. It is NOT a model of any commercial tool.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from .schemas import AssetKey, ConstraintType, ContractConstraint, ReviewStatus

HORIZON_MONTHS = 24          # default projection length; Scenario.horizon_months can extend it
MAX_HORIZON_MONTHS = 120
ENGINE_VERSION = "1.1.0"     # bump when simulation logic changes (persisted with every run)
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

class CapitalCall(BaseModel):
    month: int = Field(ge=1, le=MAX_HORIZON_MONTHS)
    amount: float = Field(ge=0)


class RsuVest(BaseModel):
    """A scheduled RSU vest; tax above the withholding rate is paid in cash at tax_due_month."""
    month: int = Field(ge=1, le=MAX_HORIZON_MONTHS)
    value_prestress: float = Field(ge=0)
    tax_due_month: int = Field(ge=1, le=MAX_HORIZON_MONTHS)


class ScheduledFlow(BaseModel):
    """A one-off cash flow: 'tax' and 'outflow' reduce cash, 'inflow' adds cash."""
    month: int = Field(ge=1, le=MAX_HORIZON_MONTHS)
    amount: float = Field(ge=0)
    category: str = Field(pattern="^(tax|outflow|inflow)$")
    label: str = ""


class Scenario(BaseModel):
    """All values are synthetic/illustrative unless sourced from a document."""
    horizon_months: int = Field(HORIZON_MONTHS, ge=12, le=MAX_HORIZON_MONTHS)

    # Holdings at month 0 (pre-stress market values)
    cash: float = 250_000
    brokerage: float = 600_000          # taxable brokerage, fully pledged to the SBL
    reit: float = 500_000               # non-traded REIT (BREIT-style share repurchase plan)
    interval_fund: float = 300_000
    rsu_vested: float = 150_000         # vested employer shares (subject to trading windows)

    # Household cash flows (monthly, after payroll withholding)
    monthly_income: float = 35_000
    monthly_core_expenses: float = 30_000
    monthly_discretionary: float = 15_000
    other_debt_service_monthly: float = 0.0   # payments on non-SBL liabilities (e.g. mortgage)
    scheduled_flows: list[ScheduledFlow] = Field(default_factory=list)

    # Market stress path
    equity_drawdown: float = Field(0.25, ge=0, le=0.95)
    months_to_trough: int = Field(3, ge=1, le=12)
    trough_hold_months: int = Field(9, ge=0, le=18)
    recovery_share: float = Field(0.5, ge=0, le=1)  # share of drawdown recovered by month 24
    beta_brokerage: float = 1.0
    beta_rsu: float = 1.3
    beta_reit_nav: float = 0.3
    beta_interval_nav: float = 0.4

    # Securities-backed line
    sbl_loan_balance: float = 300_000      # fully drawn to the 50% advance rate pre-stress

    # Private fund (unfunded commitment called on an assumed schedule)
    capital_calls: list[CapitalCall] = Field(default_factory=lambda: [CapitalCall(month=4, amount=250_000)])

    # RSU vests and tax (the demo vest is $300K in month 2, tax true-up due in April)
    rsu_vests: list[RsuVest] = Field(default_factory=lambda: [RsuVest(month=2, value_prestress=300_000, tax_due_month=4)])
    rsu_effective_tax_rate: float = 0.47   # combined marginal federal+state (assumption)
    rsu_window_months: list[int] = Field(default_factory=lambda: [2, 5, 8, 11, 14, 17, 20, 23])
    # Household policy (assumption): in each open window, sell vested RSUs to keep cash >= N months of net spending
    rsu_window_cash_floor_months: float = Field(3.0, ge=0, le=24)

    # Household redemption plan (requests are resubmitted until filled)
    reit_redemption_target: float = 100_000
    reit_request_start_month: int = 1
    reit_shares_held_over_one_year: bool = True
    interval_redemption_target: float = 150_000

    # Stress assumptions for fund-level redemption demand (NOT disclosed by any document)
    reit_base_demand_pct: float = 1.5          # aggregate requests, % of NAV per month, no stress
    reit_demand_sensitivity: float = 50.0      # extra % of NAV per month per 100% equity drawdown
    reit_board_fill_factor: float = 1.0        # share of the permitted cap the board actually fills
    interval_base_demand_pct: float = 3.0      # aggregate tenders, % of shares per offer
    interval_demand_sensitivity: float = 40.0

    # Naive comparator: fraction of each asset's value treated as instantly liquid
    naive_liquid_fraction: dict[str, float] = Field(default_factory=lambda: {
        "brokerage": 0.90, "reit": 0.70, "interval_fund": 0.70, "rsu_vested": 0.85})

    # Prevention levers (actions taken at month 0, before the stress begins)
    lever_reserve_prefund: float = 0.0        # sell brokerage now, hold proceeds as cash
    lever_sbl_paydown: float = 0.0            # sell brokerage now, repay SBL
    lever_rsu_extra_withholding: float = 0.0  # extra withholding rate (e.g. 0.15 = +15 pts)
    lever_rsu_window_presale: float = 0.0     # sell vested RSUs in the first open window
    lever_discretionary_cut: float = 0.0      # $/month cut in months 1-6
    lever_reit_prestress_request: float = 0.0 # REIT repurchase requested at month 0 (pre-stress)
    sale_tax_drag: float = 0.08               # tax + cost per $ of securities sold (assumption)

    start_calendar_month: int = Field(1, ge=1, le=12)  # Month 1 = January

    @model_validator(mode="after")
    def _months_within_horizon(self) -> Scenario:
        months = ([c.month for c in self.capital_calls] + [v.month for v in self.rsu_vests]
                  + [f.month for f in self.scheduled_flows] + [self.reit_request_start_month])
        if any(m > self.horizon_months for m in months):
            raise ValueError(f"scheduled month beyond the {self.horizon_months}-month horizon")
        return self

    @property
    def total_paper_assets(self) -> float:
        return self.cash + self.brokerage + self.reit + self.interval_fund + self.rsu_vested

    @property
    def total_rsu_vest_value(self) -> float:
        return sum(v.value_prestress for v in self.rsu_vests)


@dataclass
class ContractTerms:
    """Numeric rules used by the contract-aware model, with provenance per field."""
    reit_monthly_cap_pct: float = 2.0
    reit_quarterly_cap_pct: float = 5.0
    reit_pro_rata: bool = True
    reit_early_deduction_pct: float = 2.0
    reit_settlement_lag_months: int = 1
    interval_offer_pct: float = 5.0
    interval_offer_calendar_months: tuple[int, ...] = (3, 6, 9, 12)
    interval_fee_pct: float = 2.0
    interval_payment_lag_months: int = 1
    sbl_advance_rate: float = 0.50
    sbl_maintenance_ltv: float = 0.60
    sbl_interest_rate: float = 0.0725
    rsu_withholding_rate: float = 0.22
    rsu_max_withholding_rate: float = 0.37
    provenance: dict[str, str] = field(default_factory=dict)
    # Counterfactual switches used for attribution ("what if this rule didn't exist?")
    relax: frozenset[str] = frozenset()


RELAXATIONS = {
    "reit_gate": "BREIT repurchase caps (2%/5%) and settlement lag",
    "interval_gate": "Interval fund offer windows and proration",
    "collateral_call": "SBL maintenance call",
    "trading_window": "RSU trading windows",
    "withholding_gap": "RSU under-withholding (22% vs effective rate)",
}


_TERM_MAP: dict[tuple[ConstraintType, AssetKey], tuple[str, float]] = {
    # (type, asset) -> (ContractTerms field, multiplier from constraint units)
    (ConstraintType.REDEMPTION_MONTHLY_CAP, AssetKey.NON_TRADED_REIT): ("reit_monthly_cap_pct", 1.0),
    (ConstraintType.REDEMPTION_QUARTERLY_CAP, AssetKey.NON_TRADED_REIT): ("reit_quarterly_cap_pct", 1.0),
    (ConstraintType.EARLY_REDEMPTION_DEDUCTION, AssetKey.NON_TRADED_REIT): ("reit_early_deduction_pct", 1.0),
    (ConstraintType.REPURCHASE_OFFER_SIZE, AssetKey.INTERVAL_FUND): ("interval_offer_pct", 1.0),
    (ConstraintType.REPURCHASE_FEE, AssetKey.INTERVAL_FUND): ("interval_fee_pct", 1.0),
    (ConstraintType.SBL_ADVANCE_RATE, AssetKey.SBL): ("sbl_advance_rate", 0.01),
    (ConstraintType.SBL_MAINTENANCE_THRESHOLD, AssetKey.SBL): ("sbl_maintenance_ltv", 0.01),
    (ConstraintType.SBL_INTEREST_RATE, AssetKey.SBL): ("sbl_interest_rate", 0.01),
    (ConstraintType.RSU_WITHHOLDING_RATE, AssetKey.RSU): ("rsu_withholding_rate", 0.01),
    (ConstraintType.RSU_MAX_WITHHOLDING_RATE, AssetKey.RSU): ("rsu_max_withholding_rate", 0.01),
}


def terms_from_constraints(constraints: Iterable[ContractConstraint]) -> ContractTerms:
    """Build ContractTerms from non-rejected constraints; unmapped fields keep labelled defaults."""
    terms = ContractTerms()
    prov = {f: "default modelling assumption (no reviewed source clause)" for f in (
        "reit_monthly_cap_pct", "reit_quarterly_cap_pct", "reit_pro_rata", "reit_early_deduction_pct",
        "reit_settlement_lag_months", "interval_offer_pct", "interval_fee_pct", "sbl_advance_rate",
        "sbl_maintenance_ltv", "sbl_interest_rate", "rsu_withholding_rate", "rsu_max_withholding_rate")}
    for c in constraints:
        if c.review_status == ReviewStatus.REJECTED:
            continue
        cite = f"{c.document_name} p.{c.pdf_page} ({c.review_status.value})"
        key = (c.constraint_type, c.asset_key)
        if key in _TERM_MAP and c.value is not None:
            fname, mult = _TERM_MAP[key]
            setattr(terms, fname, float(c.value) * mult)
            prov[fname] = cite
        elif key == (ConstraintType.PRO_RATA_FULFILLMENT, AssetKey.NON_TRADED_REIT):
            terms.reit_pro_rata = True
            prov["reit_pro_rata"] = cite
        elif key == (ConstraintType.SETTLEMENT_TIMING, AssetKey.NON_TRADED_REIT):
            prov["reit_settlement_lag_months"] = f"{cite}; month-end repurchase + settlement -> 1-month lag (interpretation)"
    terms.provenance = prov
    return terms


# --------------------------------------------------------------------------- #
# Market path
# --------------------------------------------------------------------------- #

def _scheduled(s: Scenario, m: int) -> tuple[float, float, float]:
    """(tax, other outflow, inflow) from one-off scheduled flows in month m."""
    tax = sum(f.amount for f in s.scheduled_flows if f.month == m and f.category == "tax")
    out = sum(f.amount for f in s.scheduled_flows if f.month == m and f.category == "outflow")
    inc = sum(f.amount for f in s.scheduled_flows if f.month == m and f.category == "inflow")
    return tax, out, inc


def drawdown_at(s: Scenario, m: int) -> float:
    """Equity drawdown (fraction) at month m; month 0 is pre-stress."""
    D, T, H = s.equity_drawdown, s.months_to_trough, s.trough_hold_months
    if m <= 0:
        return 0.0
    if m <= T:
        return D * m / T
    if m <= T + H:
        return D
    span = max(1, s.horizon_months - T - H)
    return D * (1 - s.recovery_share * min(1.0, (m - T - H) / span))


def price_factor(s: Scenario, m: int, beta: float) -> float:
    return max(0.05, 1.0 - beta * drawdown_at(s, m))


def calendar_month(s: Scenario, m: int) -> int:
    return (s.start_calendar_month - 1 + m - 1) % 12 + 1


def month_label(s: Scenario, m: int) -> str:
    return f"M{m} ({MONTH_NAMES[calendar_month(s, m) - 1]})"


def quarter_index(s: Scenario, m: int) -> int:
    return (s.start_calendar_month - 1 + m - 1) // 3


# --------------------------------------------------------------------------- #
# Fund gate mechanics (unit-tested directly)
# --------------------------------------------------------------------------- #

def reit_fund_capacity_pct(monthly_cap: float, quarterly_cap: float, quarter_used: float) -> float:
    """Fund-level repurchase capacity this month (% of NAV): min(monthly cap, remaining quarterly cap)."""
    return max(0.0, min(monthly_cap, quarterly_cap - quarter_used))


def pro_rata_fill(demand_pct: float, capacity_pct: float) -> float:
    """Fraction of every request filled when aggregate demand meets capacity pro rata."""
    if demand_pct <= 0:
        return 1.0
    return min(1.0, capacity_pct / demand_pct)


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #

@dataclass
class SimulationResult:
    model: str
    rows: list[dict]
    first_shortfall_month: Optional[int]
    shortfall_amount: float           # deficit at the end of the first shortfall month
    peak_shortfall: float             # largest deficit over the horizon
    min_cash: float

    @property
    def has_shortfall(self) -> bool:
        return self.first_shortfall_month is not None

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def binding_in(self, month: int) -> list[str]:
        return self.rows[month - 1]["binding_constraints"] if 1 <= month <= len(self.rows) else []


def _finalize(model: str, rows: list[dict]) -> SimulationResult:
    first = next((r["month"] for r in rows if r["ending_cash"] < -0.5), None)
    min_cash = min(r["ending_cash"] for r in rows)
    return SimulationResult(
        model=model, rows=rows, first_shortfall_month=first,
        shortfall_amount=-rows[first - 1]["ending_cash"] if first else 0.0,
        peak_shortfall=max(0.0, -min_cash), min_cash=min_cash)


def _apply_month0_levers(s: Scenario, t: ContractTerms) -> dict:
    """Pre-stress actions: returns starting state."""
    brokerage = s.brokerage
    cash = s.cash
    loan = s.sbl_loan_balance
    sell_res = min(s.lever_reserve_prefund, brokerage)
    brokerage -= sell_res
    cash += sell_res * (1 - s.sale_tax_drag)
    sell_pay = min(s.lever_sbl_paydown, brokerage, loan / max(1e-9, 1 - s.sale_tax_drag))
    brokerage -= sell_pay
    loan = max(0.0, loan - sell_pay * (1 - s.sale_tax_drag))
    return {"cash": cash, "brokerage_units": brokerage, "loan": loan}


# --------------------------------------------------------------------------- #
# Contract-aware model
# --------------------------------------------------------------------------- #

def simulate_contract_aware(s: Scenario, t: ContractTerms | None = None) -> SimulationResult:
    t = t or ContractTerms()
    relax = t.relax
    st = _apply_month0_levers(s, t)
    cash, broker_u, loan = st["cash"], st["brokerage_units"], st["loan"]
    reit_u, if_u, rsu_u = s.reit, s.interval_fund, s.rsu_vested
    pending: dict[int, dict[str, float]] = {}  # month -> {"reit": $, "interval": $}

    def schedule(month: int, key: str, amount: float) -> None:
        pending.setdefault(month, {}).setdefault(key, 0.0)
        pending[month][key] += amount

    reit_lag = 0 if "reit_gate" in relax else t.reit_settlement_lag_months
    if_lag = 0 if "interval_gate" in relax else t.interval_payment_lag_months

    # Month-0 REIT request (pre-stress lever): normal-market demand, quarter of month 1
    reit_remaining = s.reit_redemption_target
    q_used = 0.0
    if s.lever_reit_prestress_request > 0:
        req = min(s.lever_reit_prestress_request, reit_u)
        cap = reit_fund_capacity_pct(t.reit_monthly_cap_pct, t.reit_quarterly_cap_pct, 0.0)
        fill = 1.0 if "reit_gate" in relax else pro_rata_fill(s.reit_base_demand_pct, cap * s.reit_board_fill_factor)
        filled = req * fill
        reit_u -= filled
        reit_remaining = max(0.0, reit_remaining - filled)
        ded = 0.0 if s.reit_shares_held_over_one_year else t.reit_early_deduction_pct / 100
        schedule(max(1, reit_lag), "reit", filled * (1 - ded))

    withholding = min(t.rsu_max_withholding_rate, t.rsu_withholding_rate + s.lever_rsu_extra_withholding)
    if "withholding_gap" in relax:
        withholding = s.rsu_effective_tax_rate
    tax_due: dict[int, float] = {}
    if_remaining = s.interval_redemption_target
    presale_left = s.lever_rsu_window_presale
    current_q = quarter_index(s, 1)
    rows: list[dict] = []

    for m in range(1, s.horizon_months + 1):
        dd = drawdown_at(s, m)
        f_b = price_factor(s, m, s.beta_brokerage)
        f_rsu = price_factor(s, m, s.beta_rsu)
        f_reit = price_factor(s, m, s.beta_reit_nav)
        f_if = price_factor(s, m, s.beta_interval_nav)
        binding: list[str] = []
        begin = cash

        income = s.monthly_income
        discretionary = s.monthly_discretionary - (min(s.lever_discretionary_cut, s.monthly_discretionary) if m <= 6 else 0.0)
        expenses = s.monthly_core_expenses + discretionary
        interest = loan * t.sbl_interest_rate / 12 + s.other_debt_service_monthly
        cap_call = sum(c.amount for c in s.capital_calls if c.month == m)
        if cap_call:
            binding.append(f"Capital call ${cap_call:,.0f} due (GP discretion; not deferred for markets)")

        # RSU vest: shares withheld at the withholding rate, gap due later in cash
        for vest in s.rsu_vests:
            if m != vest.month:
                continue
            vest_value = vest.value_prestress * f_rsu
            rsu_u += vest.value_prestress * (1 - withholding)
            gap = max(0.0, (s.rsu_effective_tax_rate - withholding) * vest_value)
            if gap > 0:
                due = max(m, vest.tax_due_month)
                tax_due[due] = tax_due.get(due, 0.0) + gap
        rsu_tax = tax_due.get(m, 0.0)
        if rsu_tax:
            binding.append(f"RSU tax true-up ${rsu_tax:,.0f} (withheld {withholding:.0%} vs {s.rsu_effective_tax_rate:.0%} effective)")
        other_tax, other_out, other_in = _scheduled(s, m)
        taxes = rsu_tax + other_tax
        expenses += other_out
        income += other_in
        if other_tax or other_out:
            binding.append(f"Scheduled outflows ${other_tax + other_out:,.0f}")

        # SBL maintenance check on pledged brokerage
        collateral = broker_u * f_b
        collateral_call = 0.0
        if "collateral_call" not in relax and collateral > 0 and loan > t.sbl_maintenance_ltv * collateral:
            collateral_call = loan - t.sbl_advance_rate * collateral
            loan -= collateral_call
            binding.append(f"SBL collateral call ${collateral_call:,.0f} (LTV above {t.sbl_maintenance_ltv:.0%})")

        # REIT repurchase request this month
        q = quarter_index(s, m)
        if q != current_q:
            current_q, q_used = q, 0.0
        reit_fill = None
        reit_requested = 0.0
        if m >= s.reit_request_start_month and reit_remaining > 1 and reit_u > 1:
            reit_requested = min(reit_remaining, reit_u * f_reit)
            if "reit_gate" in relax:
                reit_fill = 1.0
            else:
                demand = s.reit_base_demand_pct + s.reit_demand_sensitivity * dd
                capacity = reit_fund_capacity_pct(t.reit_monthly_cap_pct, t.reit_quarterly_cap_pct, q_used)
                executed = min(demand, capacity * s.reit_board_fill_factor)
                q_used += executed
                reit_fill = pro_rata_fill(demand, executed) if t.reit_pro_rata else (1.0 if demand <= executed else 0.0)
                if reit_fill < 0.999:
                    limiting = "quarterly 5% remaining" if capacity < t.reit_monthly_cap_pct - 1e-9 else "monthly 2%"
                    binding.append(f"BREIT-style gate: {reit_fill:.0%} pro-rata fill ({limiting} cap; "
                                   f"demand {demand:.1f}% of NAV)")
            filled = reit_requested * reit_fill
            reit_u -= filled / f_reit
            reit_remaining -= filled
            ded = 0.0 if s.reit_shares_held_over_one_year else t.reit_early_deduction_pct / 100
            schedule(m + reit_lag, "reit", filled * (1 - ded))
            if reit_lag and filled > 0:
                binding.append(f"REIT proceeds ${filled * (1 - ded):,.0f} settle next month")

        # Interval fund quarterly offer
        if_fill = None
        if if_remaining > 1 and if_u > 1:
            offer_month = calendar_month(s, m) in t.interval_offer_calendar_months or "interval_gate" in relax
            if offer_month:
                req = min(if_remaining, if_u * f_if)
                demand = s.interval_base_demand_pct + s.interval_demand_sensitivity * dd
                if_fill = 1.0 if "interval_gate" in relax else pro_rata_fill(demand, t.interval_offer_pct)
                filled = req * if_fill
                if_u -= filled / f_if
                if_remaining -= filled
                schedule(m + if_lag, "interval", filled * (1 - t.interval_fee_pct / 100))
                if if_fill < 0.999:
                    binding.append(f"Interval fund offer: {if_fill:.0%} pro-rata fill")

        # Proceeds settling this month (collected after this month's requests so a zero lag works)
        receipts = pending.pop(m, {})
        reit_proceeds = receipts.get("reit", 0.0)
        if_proceeds = receipts.get("interval", 0.0)

        cash = (begin + income - expenses - interest - cap_call - taxes - collateral_call
                + reit_proceeds + if_proceeds)

        # Pre-planned RSU sale in the first open window (lever)
        window_open = (m in s.rsu_window_months) or ("trading_window" in relax)
        rsu_sale = 0.0
        if presale_left > 0 and window_open:
            sale = min(presale_left, rsu_u * f_rsu)
            rsu_u -= sale / f_rsu
            presale_left -= sale
            rsu_sale += sale * (1 - s.sale_tax_drag)
            cash += sale * (1 - s.sale_tax_drag)

        # Household policy: top cash up to N months of net spending while the window is open
        net_burn = max(0.0, expenses + interest - income)
        floor = s.rsu_window_cash_floor_months * net_burn
        if window_open and cash < floor and rsu_u > 1:
            sale = min((floor - cash) / (1 - s.sale_tax_drag), rsu_u * f_rsu)
            rsu_u -= sale / f_rsu
            rsu_sale += sale * (1 - s.sale_tax_drag)
            cash += sale * (1 - s.sale_tax_drag)

        # Funding waterfall for any remaining deficit (only contract-permitted sources)
        broker_sale = sbl_draw = 0.0
        if cash < 0:
            need = -cash
            if window_open and rsu_u > 0:
                sale = min(need / (1 - s.sale_tax_drag), rsu_u * f_rsu)
                rsu_u -= sale / f_rsu
                rsu_sale += sale * (1 - s.sale_tax_drag)
                need -= sale * (1 - s.sale_tax_drag)
            elif rsu_u > 1:
                binding.append("RSU trading window closed: vested shares unsellable")
            collateral = broker_u * f_b
            free_equity = max(0.0, collateral - loan / t.sbl_advance_rate) if t.sbl_advance_rate > 0 else collateral
            if need > 0 and free_equity > 0:
                sale = min(need / (1 - s.sale_tax_drag), free_equity)
                broker_u -= sale / f_b
                broker_sale = sale * (1 - s.sale_tax_drag)
                need -= broker_sale
            if need > 0:
                capacity = max(0.0, t.sbl_advance_rate * broker_u * f_b - loan)
                sbl_draw = min(need, capacity)
                loan += sbl_draw
                need -= sbl_draw
                if capacity < 1:
                    binding.append("No SBL capacity: pledged brokerage fully encumbered")
            cash = -need

        rows.append({
            "month": m, "label": month_label(s, m), "equity_drawdown": dd,
            "beginning_cash": begin, "income": income, "expenses": expenses, "taxes": taxes,
            "debt_service": interest, "collateral_call": collateral_call, "capital_call": cap_call,
            "reit_requested": reit_requested, "reit_fill_rate": reit_fill, "reit_proceeds": reit_proceeds,
            "interval_fill_rate": if_fill, "interval_proceeds": if_proceeds,
            "rsu_sale_proceeds": rsu_sale, "brokerage_sale_proceeds": broker_sale, "sbl_draw": sbl_draw,
            "ending_cash": cash, "shortfall": max(0.0, -cash),
            "sbl_balance": loan, "brokerage_value": broker_u * f_b, "reit_value": reit_u * f_reit,
            "interval_value": if_u * f_if, "rsu_value": rsu_u * f_rsu,
            "binding_constraints": binding,
        })
    return _finalize("contract_aware", rows)


# --------------------------------------------------------------------------- #
# Naive comparator
# --------------------------------------------------------------------------- #

def simulate_naive(s: Scenario, t: ContractTerms | None = None) -> SimulationResult:
    """Simplified reference: fixed liquid fractions, no gates, no collateral calls, no withholding gap."""
    t = t or ContractTerms()
    st = _apply_month0_levers(s, t)
    cash, loan = st["cash"], st["loan"]
    units = {"brokerage": st["brokerage_units"], "reit": s.reit, "interval_fund": s.interval_fund,
             "rsu_vested": s.rsu_vested}
    betas = {"brokerage": s.beta_brokerage, "reit": s.beta_reit_nav, "interval_fund": s.beta_interval_nav,
             "rsu_vested": s.beta_rsu}
    rows = []
    for m in range(1, s.horizon_months + 1):
        begin = cash
        discretionary = s.monthly_discretionary - (min(s.lever_discretionary_cut, s.monthly_discretionary) if m <= 6 else 0.0)
        expenses = s.monthly_core_expenses + discretionary
        interest = loan * t.sbl_interest_rate / 12 + s.other_debt_service_monthly
        cap_call = sum(c.amount for c in s.capital_calls if c.month == m)
        other_tax, other_out, other_in = _scheduled(s, m)
        expenses += other_out
        income = s.monthly_income + other_in
        cash = begin + income - expenses - interest - cap_call - other_tax
        sold = 0.0
        if cash < 0:
            need = -cash
            for k in ("brokerage", "rsu_vested", "interval_fund", "reit"):
                value = units[k] * price_factor(s, m, betas[k])
                allowance = max(0.0, s.naive_liquid_fraction.get(k, 0.0) * value)
                take = min(need, allowance)
                units[k] -= take / price_factor(s, m, betas[k])
                need -= take
                sold += take
                if need <= 0:
                    break
            cash = -need
        values = {k: units[k] * price_factor(s, m, betas[k]) for k in units}
        rows.append({
            "month": m, "label": month_label(s, m), "equity_drawdown": drawdown_at(s, m),
            "beginning_cash": begin, "income": income, "expenses": expenses, "taxes": other_tax,
            "debt_service": interest, "collateral_call": 0.0, "capital_call": cap_call,
            "asset_sales": sold, "ending_cash": cash, "shortfall": max(0.0, -cash),
            "naive_liquid_reserve": cash + sum(s.naive_liquid_fraction.get(k, 0) * v for k, v in values.items()),
            "binding_constraints": [],
        })
    return _finalize("naive", rows)


# --------------------------------------------------------------------------- #
# Stress-usable liquidity
# --------------------------------------------------------------------------- #

def stress_usable_liquidity(s: Scenario, t: ContractTerms | None = None, window: int = 3) -> dict:
    """Cash the household could actually raise in the first `window` months of stress.

    Computed by the contract-aware simulator with the household requesting its
    full REIT and interval positions from month 1:
      starting cash
      + REIT and interval proceeds that settle within the window
      + vested RSUs if a trading window opens within the window (valued at that month)
      + brokerage equity above the SBL advance-rate requirement at the window end
      - SBL collateral calls due within the window
    """
    t = t or ContractTerms()
    probe = s.model_copy(update={
        "reit_redemption_target": s.reit, "interval_redemption_target": s.interval_fund,
        "reit_request_start_month": 1,
        "capital_calls": [], "rsu_vests": [], "scheduled_flows": [], "other_debt_service_monthly": 0.0,
        "monthly_income": 0.0, "monthly_core_expenses": 0.0, "monthly_discretionary": 0.0,
    })
    res = simulate_contract_aware(probe, t)
    rows = res.rows[:window]
    reit = sum(r["reit_proceeds"] for r in rows)
    interval = sum(r["interval_proceeds"] for r in rows)
    calls = sum(r["collateral_call"] for r in rows)
    open_m = next((m for m in s.rsu_window_months if m <= window), None)
    rsu = s.rsu_vested * price_factor(s, open_m, s.beta_rsu) if open_m else 0.0
    last = rows[-1]
    loan = last["sbl_balance"]
    free = max(0.0, last["brokerage_value"] - loan / t.sbl_advance_rate) if t.sbl_advance_rate else last["brokerage_value"]
    start_cash = _apply_month0_levers(s, t)["cash"]
    total = start_cash + reit + interval + rsu + free - calls
    naive = start_cash + sum(
        s.naive_liquid_fraction.get(k, 0) * v * price_factor(s, window, b) for k, v, b in [
            ("brokerage", s.brokerage, s.beta_brokerage), ("reit", s.reit, s.beta_reit_nav),
            ("interval_fund", s.interval_fund, s.beta_interval_nav), ("rsu_vested", s.rsu_vested, s.beta_rsu)])
    return {"window_months": window, "total": total, "cash": start_cash, "reit_proceeds": reit,
            "interval_proceeds": interval, "rsu_sellable": rsu, "brokerage_free_equity": free,
            "collateral_calls": -calls, "naive_total": naive}
