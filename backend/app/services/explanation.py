"""Deterministic explanation of a simulation result (no LLM).

1. First shortfall month, amount and the constraints binding in that month.
2. Counterfactual attribution: re-run with each contract rule relaxed; the reduction in peak shortfall
   is the rule's contribution. Each rule cites only the approved clauses the engine actually applied to it
   (document, page, quote; "derived" where the value is an interpretation of the clause), or is labelled as a
   default/assumption when no approved clause was applied.
3. Material assumptions: re-run with each key assumption perturbed; an assumption is material when the
   perturbation changes whether a shortfall occurs, its first month, or the peak by more than 10%.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..engine.reverse_stress import RELAXATIONS
from ..engine.simulator import ContractTerms, Scenario, SimulationResult, simulate_contract_aware

# Contract terms behind each relaxation, and the constraint types whose evidence supports them.
RELAXATION_TERMS: dict[str, dict[str, Any]] = {
    "reit_gate": {"terms": ["reit_monthly_cap_pct", "reit_quarterly_cap_pct", "reit_pro_rata",
                            "reit_settlement_lag_months"],
                  "types": ["redemption_monthly_cap", "redemption_quarterly_cap", "pro_rata_fulfillment",
                            "settlement_timing", "board_discretion"]},
    "interval_gate": {"terms": ["interval_offer_pct", "interval_fee_pct"],
                      "types": ["repurchase_offer_size", "repurchase_offer_frequency", "pro_rata_fulfillment",
                                "repurchase_fee", "payment_timing"]},
    "collateral_call": {"terms": ["sbl_advance_rate", "sbl_maintenance_ltv"],
                        "types": ["sbl_advance_rate", "sbl_maintenance_threshold", "sbl_cure_period"]},
    "trading_window": {"terms": [], "types": ["trading_window"]},
    "withholding_gap": {"terms": ["rsu_withholding_rate"],
                        "types": ["rsu_withholding_rate", "rsu_max_withholding_rate"]},
}
ASSET_FOR_RELAXATION = {"reit_gate": "non_traded_reit", "interval_gate": "interval_fund", "collateral_call": "sbl",
                        "trading_window": "rsu", "withholding_gap": "rsu"}

# (assumption key, label, low value fn, high value fn)
PERTURBATIONS = [
    ("equity_drawdown", "Equity drawdown", lambda v: max(0.0, v - 0.05), lambda v: min(0.95, v + 0.05)),
    ("reit_demand_sensitivity", "REIT redemption demand sensitivity", lambda v: v * 0.5, lambda v: v * 1.5),
    ("reit_board_fill_factor", "Share of REIT cap the board fills", lambda v: v * 0.5,
     lambda v: min(1.0, v * 1.5 or 0.5)),
    ("interval_demand_sensitivity", "Interval fund tender demand sensitivity", lambda v: v * 0.5, lambda v: v * 1.5),
    ("rsu_effective_tax_rate", "Effective tax rate on RSU income", lambda v: max(0.0, v - 0.05),
     lambda v: min(0.75, v + 0.05)),
    ("months_to_trough", "Months to market trough", lambda v: max(1, v - 1), lambda v: min(12, v + 1)),
    ("rsu_window_cash_floor_months", "Cash floor kept via RSU sales", lambda v: max(0.0, v - 1), lambda v: v + 1),
]


def _outcome(r: SimulationResult) -> dict[str, Any]:
    return {"first_shortfall_month": r.first_shortfall_month, "peak_shortfall": round(r.peak_shortfall, 2)}


def _material(base: SimulationResult, alt: SimulationResult) -> bool:
    if base.has_shortfall != alt.has_shortfall or base.first_shortfall_month != alt.first_shortfall_month:
        return True
    return base.peak_shortfall > 0 and abs(alt.peak_shortfall - base.peak_shortfall) > 0.10 * base.peak_shortfall


def build_explanation(scenario: Scenario, terms: ContractTerms, result: SimulationResult,
                      evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """`evidence` = approved constraints: {id, revision, type, asset_key, document, pdf_page, quote, value}."""
    out: dict[str, Any] = {"method": __doc__.strip(), "first_shortfall_month": result.first_shortfall_month,
                           "shortfall_amount": round(result.shortfall_amount, 2),
                           "peak_shortfall": round(result.peak_shortfall, 2), "binding_in_first_shortfall_month": [],
                           "contributing_rules": [], "material_assumptions": []}
    if result.first_shortfall_month:
        out["binding_in_first_shortfall_month"] = result.binding_in(result.first_shortfall_month)
        for key, label in RELAXATIONS.items():
            alt = simulate_contract_aware(scenario, replace(terms, relax=frozenset({key})))
            reduction = result.peak_shortfall - alt.peak_shortfall
            spec = RELAXATION_TERMS[key]
            applied_ids = {cid: t for t in spec["terms"] for cid in terms.applied.get(t, [])}
            ev = [{**e, "applied_to": applied_ids[e["id"]],
                   "role": "derived" if applied_ids[e["id"]] in terms.derived else "applied"}
                  for e in evidence if e["id"] in applied_ids]
            out["contributing_rules"].append({
                "rule": label, "relaxation": key, "peak_shortfall_reduction": round(reduction, 2),
                "removes_shortfall": not alt.has_shortfall,
                "first_shortfall_month_without_rule": alt.first_shortfall_month,
                "terms": [{"term": t, "value": getattr(terms, t),
                           "provenance": terms.provenance.get(t, "scenario assumption")} for t in spec["terms"]],
                "evidence": ev,
                "basis": ("approved contract clauses" if any(e["role"] == "applied" for e in ev) else
                          "derived from an approved clause (interpretation)" if ev else
                          "scenario assumption (trading-window months)" if key == "trading_window" else
                          "default modelling assumption - no approved clause"),
            })
        out["contributing_rules"].sort(key=lambda r: -r["peak_shortfall_reduction"])
    for key, label, lo_fn, hi_fn in PERTURBATIONS:
        base_v = getattr(scenario, key)
        variants = []
        for name, fn in (("lower", lo_fn), ("higher", hi_fn)):
            v = fn(base_v)
            if v == base_v:
                continue
            alt = simulate_contract_aware(scenario.model_copy(update={key: type(base_v)(v)}), terms)
            variants.append({"direction": name, "value": round(float(v), 4), **_outcome(alt),
                             "material": _material(result, alt)})
        out["material_assumptions"].append({"assumption": key, "label": label, "base_value": base_v,
                                            "material": any(x["material"] for x in variants), "variants": variants})
    out["material_assumptions"].sort(key=lambda a: not a["material"])
    used = {cid for ids in terms.applied.values() for cid in ids}
    out["not_modelled"] = [
        {**e, "reason": "Qualitative restriction: shown as a risk; the engine applies no numerical effect for it."
         if e.get("value") is None else "Approved, but no simulator input uses this term."}
        for e in evidence if e["id"] not in used]
    out["excluded_unsupported"] = list(terms.excluded_unsupported)
    return out
