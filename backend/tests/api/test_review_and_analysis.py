"""Constraint review, approved terms flowing into the engine, persisted runs, stress and prevention."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import (
    ConstraintRevision,
    Document,
    ExtractedConstraint,
    SimulationMonth,
    SimulationRun,
)


@pytest.fixture
def demo(alice):
    h = alice.post("/households/demo").json()
    assert h["is_demo"] is True
    return h


def approve_all(user, hid):
    for c in user.get(f"/households/{hid}/constraints").json():
        r = user.post(f"/constraints/{c['id']}/approve", json={"expected_revision": c["revision"]})
        assert r.status_code == 200, r.text


def test_demo_household_processes_synthetic_contracts(alice, demo):
    hid = demo["id"]
    docs = alice.get(f"/households/{hid}/documents").json()["items"]
    assert len(docs) == 4 and all(d["is_demo_fixture"] and d["status"] == "extracted" for d in docs)
    cons = alice.get(f"/households/{hid}/constraints").json()
    assert cons and all(c["source_type"] == "synthetic_document" and c["quote_verified"] for c in cons)
    summary = alice.get(f"/households/{hid}/summary").json()
    assert summary["totals_by_kind"]["cash"]["USD"] == "250000.00"
    assert summary["counts"]["constraints_pending_review"] == len(cons)


def test_review_edit_conflict_and_qualitative_guard(alice, demo, db):
    hid = demo["id"]
    cons = {c["constraint_type"]: c for c in alice.get(f"/households/{hid}/constraints").json()}
    adv = cons["sbl_advance_rate"]
    r = alice.patch(f"/constraints/{adv['id']}", json={"expected_revision": 1, "value": "45", "note": "per lender"})
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "edited" and body["source_type"] == "user_confirmed" and body["revision"] == 2
    assert body["original_value"] == "50.000000" and body["evidence_quote"] == adv["evidence_quote"]
    stale = alice.patch(f"/constraints/{adv['id']}", json={"expected_revision": 1, "value": "40"})
    assert stale.status_code == 409 and stale.json()["error"]["details"]["current_revision"] == 2
    detail = alice.get(f"/constraints/{adv['id']}").json()
    assert detail["revisions"][0]["change"]["value"] == {"from": "50.000000", "to": "45"}
    assert db.scalar(select(func.count()).select_from(ConstraintRevision)) == 1

    qual = cons["trading_window"]
    assert qual["is_qualitative"] and qual["value"] is None
    bad = alice.patch(f"/constraints/{qual['id']}", json={"expected_revision": 1, "value": "100"})
    assert bad.status_code == 422
    rej = alice.post(f"/constraints/{qual['id']}/reject", json={"expected_revision": 1})
    assert rej.json()["review_status"] == "rejected"
    pending = alice.get(f"/households/{hid}/constraints", params={"review_status": "needs_review"}).json()
    assert all(c["review_status"] == "needs_review" for c in pending)


def test_simulation_uses_only_approved_terms_and_is_persisted(alice, demo, db):
    hid = demo["id"]
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    # Before review: SBL terms are defaults (flagged), but the household's SBL rate record is used.
    run0 = alice.post(f"/scenarios/{scen['id']}/runs").json()
    terms0 = {t["term"]: t for t in run0["terms"]}
    assert terms0["sbl_advance_rate"]["source_backed"] is False
    assert any("sbl_advance_rate" in w for w in run0["warnings"])
    assert run0["constraint_versions"] == []

    approve_all(alice, hid)
    run = alice.post(f"/scenarios/{scen['id']}/runs", headers={"Idempotency-Key": "run-1"}).json()
    terms = {t["term"]: t for t in run["terms"]}
    assert terms["sbl_advance_rate"]["source_backed"] and "SYNTHETIC_Securities" in terms["sbl_advance_rate"]["provenance"]
    # No REIT prospectus in the demo: the REIT caps stay labelled default assumptions.
    assert terms["reit_monthly_cap_pct"]["source_backed"] is False
    assert any("reit_monthly_cap_pct" in w for w in run["warnings"])
    # Deterministic engine result for the seeded synthetic household (same as the engine's own tests).
    assert run["aware_summary"]["first_shortfall_month"] == 4
    assert run["aware_summary"]["shortfall_amount"] == pytest.approx(71871.97, abs=0.01)
    assert run["naive_summary"]["first_shortfall_month"] is None
    assert run["engine_version"] and len(run["constraint_versions"]) == len(
        [c for c in alice.get(f"/households/{hid}/constraints").json()])
    months = run["months"]
    assert len(months) == 48 and {m["model"] for m in months} == {"naive", "contract_aware"}
    m4 = next(m for m in months if m["model"] == "contract_aware" and m["month"] == 4)
    assert Decimal(m4["ending_cash"]) == Decimal("-71871.97") and Decimal(m4["shortfall"]) == Decimal("71871.97")
    assert any("Capital call" in b for b in m4["binding_constraints"])
    # Idempotent re-submission returns the same run.
    again = alice.post(f"/scenarios/{scen['id']}/runs", headers={"Idempotency-Key": "run-1"}).json()
    assert again["id"] == run["id"]
    assert db.scalar(select(func.count()).select_from(SimulationRun)) == 2
    assert db.scalar(select(func.count()).select_from(SimulationMonth)) == 96
    history = alice.get(f"/households/{hid}/runs").json()
    assert history["total"] == 2 and history["items"][0]["scenario_name"] == scen["name"]


def test_edited_constraint_changes_results(alice, demo):
    hid = demo["id"]
    approve_all(alice, hid)
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    base = alice.post(f"/scenarios/{scen['id']}/runs").json()
    maint = next(c for c in alice.get(f"/households/{hid}/constraints").json()
                 if c["constraint_type"] == "sbl_maintenance_threshold")
    # Raising the maintenance threshold to 70% removes the March collateral call.
    alice.patch(f"/constraints/{maint['id']}", json={"expected_revision": maint["revision"], "value": "70"})
    edited = alice.post(f"/scenarios/{scen['id']}/runs").json()
    calls = lambda run: sum(Decimal(m["collateral_call"]) for m in run["months"] if m["model"] == "contract_aware")  # noqa: E731
    assert calls(base) > 0 and calls(edited) == 0
    assert edited["aware_summary"]["shortfall_amount"] < base["aware_summary"]["shortfall_amount"]


def test_breit_style_caps_from_approved_constraints(alice, db):
    """Approved 2%/5% caps drive fund-level gating; changing the cap changes household fills."""
    hid = alice.post("/households", json={"name": "REIT holder"}).json()["id"]
    alice.post(f"/households/{hid}/assets", json={"kind": "non_traded_reit", "name": "REIT", "amount": "500000"})
    alice.post(f"/households/{hid}/assets", json={"kind": "cash", "name": "Cash", "amount": "100000"})
    alice.post(f"/households/{hid}/events", json={"kind": "reit_redemption_request", "month": 1, "amount": "500000"})
    doc = Document(household_id=uuid.UUID(hid), uploaded_by=alice.id, category="prospectus",
                   original_filename="prospectus.pdf", safe_filename="prospectus.pdf", storage_bucket="documents",
                   status="extracted", page_count=100)
    db.add(doc)
    db.flush()
    for key, ctype, val in (("m", "redemption_monthly_cap", "2"), ("q", "redemption_quarterly_cap", "5")):
        db.add(ExtractedConstraint(
            household_id=doc.household_id, document_id=doc.id, extraction_key=key, constraint_type=ctype,
            asset_key="non_traded_reit", description=ctype, value=Decimal(val), original_value=Decimal(val),
            unit="% of NAV", pdf_page=53, evidence_quote=f"no more than {val}% of our aggregate NAV",
            quote_verified=True, interpretation="fund-level cap", confidence="high", source_type="source_backed",
            review_status="confirmed", extraction_method="rule_based"))
    db.commit()
    scen = alice.post(f"/households/{hid}/scenarios", json={"name": "s", "assumptions": {
        "reit_base_demand_pct": 10, "reit_demand_sensitivity": 0}}).json()
    run = alice.post(f"/scenarios/{scen['id']}/runs").json()
    fills = [Decimal(m["reit_fill_rate"]) for m in run["months"] if m["model"] == "contract_aware"][:3]
    # demand 10%/month: months 1-2 fill 2/10 = 20%; month 3 has only 1% of the 5% quarter left -> 10%.
    assert fills == [Decimal("0.2"), Decimal("0.2"), Decimal("0.1")]
    terms = {t["term"]: t for t in run["terms"]}
    assert terms["reit_monthly_cap_pct"]["source_backed"] and "p.53" in terms["reit_monthly_cap_pct"]["provenance"]


def test_missing_fx_rate_is_reported(alice):
    hid = alice.post("/households", json={"name": "Multi-ccy", "reporting_currency": "USD"}).json()["id"]
    alice.post(f"/households/{hid}/assets", json={"kind": "cash", "name": "EUR cash", "amount": "1000",
                                                  "currency": "EUR"})
    scen = alice.post(f"/households/{hid}/scenarios", json={"name": "s"}).json()
    r = alice.post(f"/scenarios/{scen['id']}/runs")
    assert r.status_code == 422 and r.json()["error"]["details"]["missing_currencies"] == ["EUR"]
    alice.patch(f"/scenarios/{scen['id']}", json={"assumptions": {"fx_rates": {"EUR": 1.1}}})
    ok = alice.post(f"/scenarios/{scen['id']}/runs").json()
    assert ok["household_snapshot"]["fx_rates"] == {"EUR": 1.1}
    first = next(m for m in ok["months"] if m["model"] == "contract_aware" and m["month"] == 1)
    assert Decimal(first["beginning_cash"]) == Decimal("1100.00")


def test_reverse_stress_and_prevention_flow(alice, demo):
    hid = demo["id"]
    approve_all(alice, hid)
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    st = alice.post(f"/scenarios/{scen['id']}/stress", json={}).json()
    assert st["found"] and st["grid_monotone"]
    assert float(st["boundary_drawdown"]) == pytest.approx(0.1669, abs=0.001)
    assert st["first_shortfall_month"] == 4 and st["attribution"] and st["key_events"]
    assert len(st["search"]["grid"]) == 61 and "bisection" in st["method"]
    assert alice.get(f"/households/{hid}/stress-results").json()["total"] == 1

    plan = alice.post(f"/scenarios/{scen['id']}/prevention", json={}).json()
    assert plan["baseline_first_shortfall"] == 4 and plan["combined_verified"]
    singles = [r for r in plan["recommendations"] if r["kind"] == "single"]
    feasible = [r for r in singles if r["feasible_alone"]]
    assert feasible == sorted(feasible, key=lambda r: Decimal(r["cost"]))
    assert all(r["status"] == "proposed" for r in plan["recommendations"])
    combined = [r for r in plan["recommendations"] if r["kind"] == "combined"]
    # Applying requires approval first.
    assert alice.post(f"/recommendations/{combined[0]['id']}/apply").status_code == 409
    alice.post(f"/recommendations/{combined[0]['id']}/decision", json={"decision": "approved"})
    new_scen = alice.post(f"/recommendations/{combined[0]['id']}/apply").json()["scenario"]
    fixed = alice.post(f"/scenarios/{new_scen['id']}/runs").json()
    assert fixed["aware_summary"]["first_shortfall_month"] is None  # verified plan holds when re-run
    rej = alice.post(f"/recommendations/{singles[-1]['id']}/decision", json={"decision": "rejected"}).json()
    assert rej["status"] == "rejected"


def test_stress_never_fails_edge_case(alice):
    hid = alice.post("/households", json={"name": "Cash rich"}).json()["id"]
    alice.post(f"/households/{hid}/assets", json={"kind": "cash", "name": "Cash", "amount": "5000000"})
    scen = alice.post(f"/households/{hid}/scenarios", json={"name": "s"}).json()
    st = alice.post(f"/scenarios/{scen['id']}/stress", json={"step": 0.05}).json()
    assert st["found"] is False and st["boundary_drawdown"] is None
    plan = alice.post(f"/scenarios/{scen['id']}/prevention", json={}).json()
    assert plan["recommendations"] == [] and "No shortfall" in plan["lp_status"]


def test_scenario_assumption_validation(alice):
    hid = alice.post("/households", json={"name": "x"}).json()["id"]
    r = alice.post(f"/households/{hid}/scenarios", json={"name": "bad", "assumptions": {"equity_drawdown": 1.5}})
    assert r.status_code == 422
    r = alice.post(f"/households/{hid}/scenarios", json={"name": "bad", "assumptions": {"unknown_field": 1}})
    assert r.status_code == 422
    defaults = alice.get("/scenario-defaults").json()
    assert defaults["assumptions"]["equity_drawdown"] == 0.25 and len(defaults["fields"]) >= 20
