import json

import pandas as pd
import pytest

from src.demo_data import demo_scenario
from src.export import (
    CONSTRAINT_EXPORT_FIELDS, SIMULATION_EXPORT_FIELDS, bundle_json, constraints_csv, results_bundle,
    simulation_csv,
)
from src.optimizer import plan_prevention
from src.reverse_stress import reverse_stress
from src.schemas import AssetKey, ConstraintType, ContractConstraint, SourceType
from src.simulator import ContractTerms, Scenario, simulate_contract_aware, simulate_naive


def test_reverse_stress_is_reproducible_and_brackets_boundary():
    s, t = demo_scenario(), ContractTerms()
    a, b = reverse_stress(s, t), reverse_stress(s, t)
    assert a.found and a.boundary_drawdown == b.boundary_drawdown
    assert a.first_shortfall_month == b.first_shortfall_month
    assert simulate_contract_aware(s.model_copy(update={"equity_drawdown": a.boundary_drawdown}), t).has_shortfall
    if a.last_safe_drawdown is not None:
        assert not simulate_contract_aware(s.model_copy(update={"equity_drawdown": a.last_safe_drawdown}), t).has_shortfall
        assert a.boundary_drawdown - a.last_safe_drawdown <= 0.0006
    assert a.attribution and a.key_events and a.binding_constraints


def test_reverse_stress_handles_never_failing_scenario():
    s = Scenario(cash=2_000_000, capital_calls=[], rsu_vest_value_prestress=0, sbl_loan_balance=0)
    r = reverse_stress(s, ContractTerms())
    assert not r.found and r.boundary_drawdown is None and r.first_shortfall_month is None


def test_prevention_plan_is_verified_by_resimulation():
    s, t = demo_scenario(), ContractTerms()
    plan = plan_prevention(s, t)
    assert plan.baseline_first_shortfall is not None
    assert plan.options and any(o.feasible_alone for o in plan.options)
    feasible = [o for o in plan.options if o.feasible_alone]
    assert feasible == sorted(feasible, key=lambda o: o.cost)
    for o in feasible:
        assert o.first_shortfall_after is None
    assert plan.combined_verified
    applied = s.model_copy(update={r["field"]: r["amount"] for r in plan.combined})
    assert not simulate_contract_aware(applied, t).has_shortfall
    assert plan.combined_cost <= min(o.cost for o in feasible) + 1.0


def test_exports_have_required_fields_and_values():
    s, t = demo_scenario(), ContractTerms()
    naive, aware = simulate_naive(s, t), simulate_contract_aware(s, t)
    c = ContractConstraint(constraint_id="d:1", constraint_type=ConstraintType.REDEMPTION_MONTHLY_CAP,
                           asset_key=AssetKey.NON_TRADED_REIT, description="cap", value=2.0, unit="%",
                           document_id="d", document_name="doc.pdf", pdf_page=12, printed_page="89",
                           evidence_quote="no more than 2% of our aggregate NAV per month", quote_verified=True,
                           interpretation="i", source_type=SourceType.SOURCE_BACKED)
    df = pd.read_csv(__import__("io").StringIO(constraints_csv([c])))
    assert list(df.columns) == CONSTRAINT_EXPORT_FIELDS
    assert df.loc[0, "pdf_page"] == 12 and df.loc[0, "evidence_quote"].startswith("no more than 2%")

    sim = pd.read_csv(__import__("io").StringIO(simulation_csv(naive, aware)))
    assert set(SIMULATION_EXPORT_FIELDS) <= set(sim.columns)
    assert len(sim) == 48
    aw = sim[sim["model"] == "contract_aware"]
    assert aw["ending_cash"].tolist() == pytest.approx([r["ending_cash"] for r in aware.rows])

    bundle = json.loads(bundle_json(results_bundle(s, t, [c], naive, aware)))
    assert bundle["results"]["contract_aware"]["first_shortfall_month"] == aware.first_shortfall_month
    assert bundle["results"]["contract_aware"]["shortfall_amount"] == pytest.approx(round(aware.shortfall_amount, 2))
    assert bundle["constraints"][0]["evidence_quote"] and bundle["constraints"][0]["pdf_page"] == 12
    assert len(bundle["monthly"]["contract_aware"]) == 24


def test_relaxing_any_contract_rule_never_worsens_the_shortfall():
    """Regression: a zero settlement lag used to drop same-month proceeds."""
    from src.reverse_stress import attribute_shortfall
    for row in attribute_shortfall(demo_scenario(), ContractTerms()):
        assert row["shortfall_reduction"] >= -1e-6, row
