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


def test_run_explanation_links_rules_to_approved_evidence(alice, demo):
    hid = demo["id"]
    approve_all(alice, hid)
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    run = alice.post(f"/scenarios/{scen['id']}/runs").json()
    exp = run["explanation"]
    assert exp["first_shortfall_month"] == 4 and exp["shortfall_amount"] == pytest.approx(71871.97, abs=0.01)
    assert any("Capital call" in b for b in exp["binding_in_first_shortfall_month"])
    rules = {r["relaxation"]: r for r in exp["contributing_rules"]}
    sbl = rules["collateral_call"]
    assert sbl["removes_shortfall"] is True and sbl["basis"] == "approved contract clauses"
    assert sbl["evidence"] and all(e["document"].startswith("SYNTHETIC_Securities") and e["pdf_page"] >= 1
                                   and e["quote"] for e in sbl["evidence"])
    # No REIT prospectus approved in the demo: REIT gate is explicitly a default assumption.
    assert rules["reit_gate"]["evidence"] == [] and "default" in rules["reit_gate"]["basis"]
    material = {a["assumption"]: a for a in exp["material_assumptions"]}
    assert material["equity_drawdown"]["material"] is True and len(material) >= 6
    # Stored with the run and returned again later.
    again = alice.get(f"/runs/{run['id']}").json()
    assert again["explanation"] == exp


def test_scenario_presets_are_labelled_assumptions(alice):
    presets = alice.get("/scenario-presets").json()
    ids = {p["id"] for p in presets}
    assert {"drawdown_2022", "reit_board_halves", "reit_suspended"} <= ids
    suspended = next(p for p in presets if p["id"] == "reit_suspended")
    assert suspended["assumptions"]["reit_board_fill_factor"] == 0.0 and "assumption" in suspended["label"].lower()
    hid = alice.post("/households", json={"name": "P"}).json()["id"]
    created = alice.post(f"/households/{hid}/scenarios", json={"name": suspended["name"],
                                                               "assumptions": suspended["assumptions"]})
    assert created.status_code == 201


def _clone_constraint(db, cid, value, status, key):
    src = db.get(ExtractedConstraint, uuid.UUID(cid))
    cols = {c.name: getattr(src, c.name) for c in ExtractedConstraint.__table__.columns
            if c.name not in ("id", "created_at", "updated_at")}
    clone = ExtractedConstraint(**{**cols, "extraction_key": key, "value": Decimal(value), "review_status": status,
                                   "pdf_page": src.pdf_page})
    db.add(clone)
    db.commit()
    return str(clone.id)


def test_conflicting_approved_terms_block_analysis_until_resolved(alice, demo, db):
    hid = demo["id"]
    approve_all(alice, hid)
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    baseline = alice.post(f"/scenarios/{scen['id']}/runs").json()["aware_summary"]
    adv = next(c for c in alice.get(f"/households/{hid}/constraints").json()
               if c["constraint_type"] == "sbl_advance_rate")

    # An unreviewed clause with a different value changes nothing.
    pending = _clone_constraint(db, adv["id"], "70", "needs_review", "test:pending")
    r = alice.post(f"/scenarios/{scen['id']}/runs")
    assert r.status_code == 201 and r.json()["aware_summary"] == baseline

    # Two approved clauses that disagree: every analysis endpoint refuses, listing both clauses.
    conflicting = _clone_constraint(db, adv["id"], "70", "confirmed", "test:conflict")
    for path in ("runs", "stress", "prevention"):
        r = alice.post(f"/scenarios/{scen['id']}/{path}", json={} if path != "runs" else None)
        assert r.status_code == 409, (path, r.text)
        err = r.json()["error"]
        assert err["code"] == "term_conflict" and "reject" in err["message"].lower()
        (conflict,) = err["details"]["conflicts"]
        assert conflict["term"] == "sbl_advance_rate"
        assert {x["constraint_id"] for x in conflict["candidates"]} == {adv["id"], conflicting}
        assert sorted(x["value"] for x in conflict["candidates"]) == [50.0, 70.0]
    assert alice.get(f"/households/{hid}/runs").json()["total"] == 2  # nothing persisted while blocked

    # Resolving by rejecting the clause that does not apply restores the original result.
    c = alice.get(f"/constraints/{conflicting}").json()
    assert alice.post(f"/constraints/{conflicting}/reject", json={"expected_revision": c["revision"]}).status_code == 200
    r = alice.post(f"/scenarios/{scen['id']}/runs")
    assert r.status_code == 201 and r.json()["aware_summary"] == baseline
    assert pending not in {v["id"] for v in r.json()["constraint_versions"]}


def test_assumption_field_kinds_match_default_values(alice):
    """The editor parses each field by its declared kind; a mismatch makes the defaults unsavable."""
    d = alice.get("/scenario-defaults").json()
    for f in d["fields"]:
        v = d["assumptions"][f["key"]]
        values = list(v.values()) if isinstance(v, dict) else [v]
        if f["kind"] == "list":
            assert all(isinstance(x, list) and all(isinstance(m, int) for m in x) for x in values), f["key"]
        if f["kind"] == "percent" and not f["key"].endswith("_pct"):
            assert all(0 <= x <= 1 for x in values), f["key"]


def test_approval_rechecks_evidence_on_the_cited_page(alice, demo, db):
    hid = demo["id"]
    cons = alice.get(f"/households/{hid}/constraints").json()
    adv = next(c for c in cons if c["constraint_type"] == "sbl_advance_rate")
    row = db.get(ExtractedConstraint, uuid.UUID(adv["id"]))
    row.evidence_quote = "This sentence appears on no page of the agreement."
    db.commit()
    r = alice.post(f"/constraints/{adv['id']}/approve", json={"expected_revision": adv["revision"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_evidence"
    assert "not on the cited page" in r.json()["error"]["message"]
    edit = alice.patch(f"/constraints/{adv['id']}", json={"expected_revision": adv["revision"], "value": "45"})
    assert edit.status_code == 422  # an edit cannot attach a reviewer value to a citation that does not exist


def test_unsupported_value_needs_reviewer_edit_before_it_can_be_used(alice, demo, db):
    hid = demo["id"]
    cons = alice.get(f"/households/{hid}/constraints").json()
    adv = next(c for c in cons if c["constraint_type"] == "sbl_advance_rate")
    row = db.get(ExtractedConstraint, uuid.UUID(adv["id"]))
    row.value = Decimal("70")  # quote says 50%
    row.validation_issues = [{"code": "value_not_in_quote", "severity": "error", "message": "value=70 not in quote"}]
    db.commit()
    r = alice.post(f"/constraints/{adv['id']}/approve", json={"expected_revision": adv["revision"]})
    assert r.status_code == 422 and "value=70 not in quote" in r.json()["error"]["message"]
    edit = alice.patch(f"/constraints/{adv['id']}", json={"expected_revision": adv["revision"], "value": "55",
                                                          "note": "confirmed with lender"})
    assert edit.status_code == 200 and edit.json()["review_status"] == "edited"
    assert edit.json()["source_type"] == "user_confirmed"


def test_run_explanation_evidence_links_and_unmodelled_terms(alice, demo):
    hid = demo["id"]
    approve_all(alice, hid)
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    run = alice.post(f"/scenarios/{scen['id']}/runs").json()
    exp = run["explanation"]
    version_ids = {v["id"] for v in run["constraint_versions"]}
    cited = [e for r in exp["contributing_rules"] for e in r["evidence"]]
    assert cited and all(e["id"] in version_ids and e["role"] in ("applied", "derived") for e in cited)
    assert {e["id"] for e in exp["not_modelled"]}.isdisjoint({e["id"] for e in cited})
    assert all(e["value"] is None or "no simulator input" in e["reason"].lower() for e in exp["not_modelled"])
    assert exp["excluded_unsupported"] == []
