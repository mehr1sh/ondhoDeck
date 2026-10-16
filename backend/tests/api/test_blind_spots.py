"""Liquidity blind-spot detector: deterministic variants, transparent ranking, evidence, report export."""
import time

import pytest

from app.engine.simulator import ContractTerms, Scenario
from app.services.blind_spots import SEVERITY_ORDER, VARIANTS, detect, severity

from .test_review_and_analysis import approve_all


@pytest.fixture
def demo(alice):
    return alice.post("/households/demo").json()


def test_ranking_follows_the_documented_order_and_is_deterministic():
    s = Scenario()
    a, b = detect(s, ContractTerms(), []), detect(s, ContractTerms(), [])
    assert a == b
    risks = a["risks"]
    assert [r["rank"] for r in risks] == list(range(1, len(risks) + 1))
    keys = [(SEVERITY_ORDER[r["severity"]], not r["blind_spot"], r["first_shortfall_month"], -r["peak_shortfall"],
             r["tier"]) for r in risks]
    assert keys == sorted(keys)
    assert [c["variant"] for c in a["comparison"]] == [v.id for v in VARIANTS]
    assert all(len(c["monthly_cash"]) == s.horizon_months for c in a["comparison"])
    assert "not a forecast" in a["disclaimer"] and "guarantee" in a["disclaimer"]


def test_every_variant_states_its_assumptions_and_baseline_is_unchanged():
    s = Scenario()
    out = detect(s, ContractTerms(), [])
    base = next(c for c in out["comparison"] if c["variant"] == "baseline")
    assert base["changes"] == ["No change: the scenario as defined."]
    assert all(c["changes"] for c in out["comparison"])
    income = next(c for c in out["comparison"] if c["variant"] == "income_interruption")
    assert "months 2-7" in income["changes"][0]
    # Stresses never make the household better off than the baseline in this scenario.
    assert all(c["contract_aware"]["min_cash"] <= base["contract_aware"]["min_cash"] + 0.01 for c in out["comparison"])


def test_well_funded_household_has_no_risks():
    s = Scenario(cash=5_000_000)
    out = detect(s, ContractTerms(), [])
    assert out["risks"] == [] and out["summary"]["risks"] == 0


def test_shortfall_visible_on_paper_is_not_a_blind_spot():
    # Nothing to sell: both views run out of cash in the same month.
    s = Scenario(cash=10_000, brokerage=0, reit=0, interval_fund=0, rsu_vested=0, sbl_loan_balance=0,
                 capital_calls=[], rsu_vests=[], reit_redemption_target=0, interval_redemption_target=0)
    out = detect(s, ContractTerms(), [])
    base = next(r for r in out["risks"] if r["variant"] == "baseline")
    assert base["blind_spot"] is False and base["paper_wealth_first_shortfall_month"] == base["first_shortfall_month"]


@pytest.mark.parametrize("month,peak,expected", [(4, 50_000, "critical"), (4, 10_000, "high"), (10, 10_000, "high"),
                                                 (20, 200_000, "high"), (20, 10_000, "moderate")])
def test_severity_thresholds(month, peak, expected):
    assert severity(month, peak, spend=45_000) == expected


def test_api_report_with_clause_evidence_and_pdf(alice, bob, demo):
    hid = demo["id"]
    approve_all(alice, hid)
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    r = alice.post(f"/scenarios/{scen['id']}/blind-spots")
    assert r.status_code == 201, r.text
    rep = r.json()
    res = rep["result"]
    assert rep["risk_count"] == res["summary"]["risks"] >= 1 and rep["as_of_date"]
    base = next(x for x in res["risks"] if x["variant"] == "baseline")
    assert base["first_shortfall_month"] == 4 and base["shortfall_amount"] == pytest.approx(71871.97, abs=0.01)
    assert base["blind_spot"] is True  # the paper-wealth view shows no shortfall for the demo household
    sourced = [c for x in res["risks"] for c in x["contributing_rules"] if c["evidence"]]
    assert sourced and all(ev["quote"] and ev["pdf_page"] >= 1 for c in sourced for ev in c["evidence"])

    assert alice.get(f"/blind-spot-reports/{rep['id']}").json()["result"] == res
    assert alice.get(f"/households/{hid}/blind-spot-reports").json()["total"] == 1
    assert bob.get(f"/blind-spot-reports/{rep['id']}").status_code == 404

    exp = alice.post(f"/households/{hid}/exports", json={"kind": "blind_spot_pdf",
                                                         "blind_spot_report_id": rep["id"]}).json()
    for _ in range(50):
        exp = alice.get(f"/exports/{exp['id']}").json()
        if exp["status"] in ("ready", "failed"):
            break
        time.sleep(0.1)
    assert exp["status"] == "ready", exp
    url = alice.get(f"/exports/{exp['id']}/download").json()["url"]
    pdf = alice.client.get(url)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    import pymupdf
    text = " ".join(p.get_text() for p in pymupdf.open(stream=pdf.content, filetype="pdf"))
    assert "Liquidity blind-spot report" in text and "not a forecast" in text and "PDF p." in text

    other = bob.post("/households", json={"name": "B"}).json()["id"]
    assert bob.post(f"/households/{other}/exports", json={"kind": "blind_spot_pdf",
                                                          "blind_spot_report_id": rep["id"]}).status_code == 404


def test_reports_list_only_callers_households(alice, bob, demo):
    hid = demo["id"]
    approve_all(alice, hid)
    scen = alice.get(f"/households/{hid}/scenarios").json()[0]
    rep = alice.post(f"/scenarios/{scen['id']}/blind-spots").json()
    alice.post(f"/households/{hid}/exports", json={"kind": "constraints_csv"})
    out = alice.get("/me/reports").json()
    assert [r["id"] for r in out["blind_spot_reports"]] == [rep["id"]]
    assert out["blind_spot_reports"][0]["household_name"] == demo["name"]
    assert out["blind_spot_reports"][0]["scenario_name"] == scen["name"]
    assert len(out["exports"]) == 1 and out["exports"][0]["household_name"] == demo["name"]
    assert bob.get("/me/reports").json() == {"exports": [], "blind_spot_reports": []}
