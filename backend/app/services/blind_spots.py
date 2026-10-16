"""Liquidity blind-spot detection (deterministic; no LLM, no randomness).

A fixed, documented set of stress variants is applied to the scenario. Each variant changes named inputs
only (listed in `changes`); every change is a modelling assumption, not a forecast or a contract term. For
each variant both models are run:

- contract-aware: approved contract terms (redemption caps, proration, settlement lags, collateral calls,
  trading windows, withholding) and the scenario path;
- paper-wealth (naive): the same path, but illiquid holdings are treated as sellable at a haircut.

A **risk** is a variant in which month-end cash falls below zero in the contract-aware model. It is a
**blind spot** when the paper-wealth view shows no shortfall, or a later one: the household looks liquid on
paper but contractual restrictions stop the money arriving in time.

Ranking (transparent, applied in order):
1. severity class - critical: shortfall within 6 months AND peak deficit >= 1 month of spending;
   high: shortfall within 12 months OR peak deficit >= 3 months of spending; otherwise moderate;
2. blind spots before shortfalls the paper-wealth view also shows;
3. earlier first shortfall month;
4. larger peak deficit;
5. variant order (milder assumptions first).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from ..engine.simulator import (
    ContractTerms,
    Scenario,
    ScheduledFlow,
    SimulationResult,
    simulate_contract_aware,
    simulate_naive,
)
from .explanation import build_explanation

DISCLAIMER = ("Deterministic what-if analysis under stated assumptions. It is not a forecast, does not estimate "
              "probabilities and does not guarantee any outcome. Contract terms used are advisor-approved clauses; "
              "everything else is an assumption listed with each variant.")
SEVERITY_ORDER = {"critical": 0, "high": 1, "moderate": 2}


def monthly_spending(s: Scenario) -> float:
    return s.monthly_core_expenses + s.monthly_discretionary + s.other_debt_service_monthly


@dataclass(frozen=True)
class Variant:
    id: str
    label: str
    tier: int  # 0 baseline, 1 single shock, 2 combined
    apply: Callable[[Scenario, ContractTerms], tuple[Scenario, ContractTerms, list[str]]]


def _baseline(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    return s, t, ["No change: the scenario as defined."]


def _income_stop(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    months = [m for m in range(2, 8) if m <= s.horizon_months]
    if s.monthly_income <= 0 or not months:
        return s, t, ["No earned income recorded, so there is nothing to interrupt."]
    flows = [*s.scheduled_flows, *(ScheduledFlow(month=m, amount=s.monthly_income, category="outflow",
                                                 label="Assumed income interruption") for m in months)]
    return (s.model_copy(update={"scheduled_flows": flows}), t,
            [f"Earned income ({s.monthly_income:,.0f}/month) stops in months {months[0]}-{months[-1]}."])


def _expense_shock(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    amount = 3 * monthly_spending(s)
    month = min(3, s.horizon_months)
    flows = [*s.scheduled_flows, ScheduledFlow(month=month, amount=amount, category="outflow",
                                               label="Assumed unplanned expense")]
    return (s.model_copy(update={"scheduled_flows": flows}), t,
            [f"Unplanned expense of {amount:,.0f} (3 months of spending) in month {month}."])


def _reit_suspended(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    return (s.model_copy(update={"reit_board_fill_factor": 0.0}), t,
            ["The REIT board fills none of the repurchase requests (the prospectus allows fewer or none)."])


def _interval_oversubscribed(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    demand = max(s.interval_base_demand_pct, 25.0)
    return (s.model_copy(update={"interval_base_demand_pct": demand}), t,
            [f"Interval fund tenders are oversubscribed: other investors tender {demand:g}% of shares, so each "
             "request is prorated."])


def _payment_delay(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    t2 = replace(t, reit_settlement_lag_months=t.reit_settlement_lag_months + 1,
                 interval_payment_lag_months=t.interval_payment_lag_months + 1)
    return (s, t2, ["Redemption and tender proceeds arrive one month later than the approved contract timing "
                    "(operational delay assumption)."])


def _severe_market(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    dd = max(s.equity_drawdown, 0.40)
    return (s.model_copy(update={"equity_drawdown": dd}), t,
            [f"Equity drawdown of {dd:.0%} (scenario: {s.equity_drawdown:.0%}), reaching the trough in "
             f"{s.months_to_trough} months."])


def _combined(s: Scenario, t: ContractTerms) -> tuple[Scenario, ContractTerms, list[str]]:
    changes: list[str] = []
    for fn in (_income_stop, _severe_market, _reit_suspended):
        s, t, c = fn(s, t)
        changes += c
    return s, t, changes


VARIANTS = [
    Variant("baseline", "Scenario as defined", 0, _baseline),
    Variant("income_interruption", "Income interruption (6 months)", 1, _income_stop),
    Variant("expense_shock", "Unplanned expense (3 months of spending)", 1, _expense_shock),
    Variant("reit_suspended", "REIT repurchases suspended", 1, _reit_suspended),
    Variant("interval_oversubscribed", "Interval fund oversubscribed", 1, _interval_oversubscribed),
    Variant("payment_delay", "Proceeds delayed one month", 1, _payment_delay),
    Variant("severe_market", "Severe market drawdown", 1, _severe_market),
    Variant("combined", "Income stops + severe drawdown + REIT suspended", 2, _combined),
]


def _summary(r: SimulationResult) -> dict[str, Any]:
    return {"first_shortfall_month": r.first_shortfall_month, "shortfall_amount": round(r.shortfall_amount, 2),
            "peak_shortfall": round(r.peak_shortfall, 2), "min_cash": round(r.min_cash, 2)}


def severity(first_month: int, peak: float, spend: float) -> str:
    months_of_spend = peak / spend if spend > 0 else float("inf")
    if first_month <= 6 and months_of_spend >= 1:
        return "critical"
    if first_month <= 12 or months_of_spend >= 3:
        return "high"
    return "moderate"


def detect(scenario: Scenario, terms: ContractTerms, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    spend = monthly_spending(scenario)
    comparison, risks = [], []
    for v in VARIANTS:
        s2, t2, changes = v.apply(scenario, terms)
        aware, naive = simulate_contract_aware(s2, t2), simulate_naive(s2, t2)
        row = {"variant": v.id, "label": v.label, "tier": v.tier, "changes": changes,
               "contract_aware": _summary(aware), "paper_wealth": _summary(naive),
               "monthly_cash": [round(r["ending_cash"], 2) for r in aware.rows],
               "monthly_cash_paper_wealth": [round(r["ending_cash"], 2) for r in naive.rows]}
        comparison.append(row)
        if not aware.has_shortfall:
            continue
        first = aware.first_shortfall_month or 0
        hidden = not naive.has_shortfall or (naive.first_shortfall_month or 0) > first
        exp = build_explanation(s2, t2, aware, evidence)
        risks.append({
            "variant": v.id, "label": v.label, "tier": v.tier, "changes": changes,
            "severity": severity(first, aware.peak_shortfall, spend),
            "blind_spot": hidden,
            "first_shortfall_month": first, "shortfall_amount": round(aware.shortfall_amount, 2),
            "peak_shortfall": round(aware.peak_shortfall, 2),
            "peak_in_months_of_spending": round(aware.peak_shortfall / spend, 2) if spend > 0 else None,
            "paper_wealth_first_shortfall_month": naive.first_shortfall_month,
            "binding_in_first_shortfall_month": exp["binding_in_first_shortfall_month"],
            "contributing_rules": [r for r in exp["contributing_rules"] if r["peak_shortfall_reduction"] > 0][:4],
        })
    risks.sort(key=lambda r: (SEVERITY_ORDER[r["severity"]], not r["blind_spot"], r["first_shortfall_month"],
                              -r["peak_shortfall"], r["tier"]))
    for i, r in enumerate(risks, 1):
        r["rank"] = i
    return {"method": __doc__.strip(), "disclaimer": DISCLAIMER, "monthly_spending": round(spend, 2),
            "risks": risks, "comparison": comparison,
            "summary": {"variants": len(VARIANTS), "risks": len(risks),
                        "blind_spots": sum(r["blind_spot"] for r in risks),
                        "critical": sum(r["severity"] == "critical" for r in risks)}}
