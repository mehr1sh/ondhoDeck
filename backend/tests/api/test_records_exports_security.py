"""Financial records validation, exports, RLS policies, rate limiting and account deletion."""
import csv
import io
import json
import uuid
from pathlib import Path

import psycopg
import pymupdf
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import Household, HouseholdMember, Profile

# ----------------------------------------------------------------------------- financial records

def test_asset_crud_and_validation(alice):
    hid = alice.post("/households", json={"name": "H"}).json()["id"]
    bad = [{"kind": "cash", "name": "x", "amount": "-1"}, {"kind": "yacht", "name": "x", "amount": "1"},
           {"kind": "cash", "name": "x", "amount": "1", "currency": "dollars"},
           {"kind": "cash", "name": "", "amount": "1"}, {"kind": "cash", "name": "x", "amount": "1.234"}]
    for body in bad:
        assert alice.post(f"/households/{hid}/assets", json=body).status_code == 422, body
    a = alice.post(f"/households/{hid}/assets", json={"kind": "brokerage", "name": "Brokerage", "amount": "600000",
                                                      "currency": "usd", "pledged_to_sbl": True}).json()
    assert a["currency"] == "USD" and a["pledged_to_sbl"] is True
    upd = alice.patch(f"/assets/{a['id']}", json={"amount": "550000.50"}).json()
    assert upd["amount"] == "550000.50"
    assert alice.delete(f"/assets/{a['id']}").status_code == 204
    assert alice.get(f"/households/{hid}/assets").json() == []
    actions = {e["action"] for e in alice.get(f"/households/{hid}/audit-events").json()["items"]}
    assert {"asset.created", "asset.updated", "asset.deleted"} <= actions


def test_liabilities_flows_and_events(alice):
    hid = alice.post("/households", json={"name": "H"}).json()["id"]
    assert alice.post(f"/households/{hid}/liabilities", json={"kind": "sbl", "name": "Line", "balance": "300000",
                                                              "annual_rate": "0.0725"}).status_code == 201
    assert alice.post(f"/households/{hid}/liabilities", json={"kind": "sbl", "name": "Line", "balance": "1",
                                                              "annual_rate": "7.25"}).status_code == 422
    assert alice.post(f"/households/{hid}/cash-flows", json={"kind": "income", "name": "Salary",
                                                             "monthly_amount": "35000"}).status_code == 201
    vest = alice.post(f"/households/{hid}/events", json={"kind": "rsu_vest", "month": 4, "amount": "1",
                                                         "tax_due_month": 2})
    assert vest.status_code == 422  # tax cannot be due before the vest
    assert alice.post(f"/households/{hid}/events", json={"kind": "capital_call", "month": 0,
                                                         "amount": "1"}).status_code == 422
    ok = alice.post(f"/households/{hid}/events", json={"kind": "rsu_vest", "month": 2, "amount": "300000",
                                                       "tax_due_month": 4})
    assert ok.status_code == 201
    summary = alice.get(f"/households/{hid}/summary").json()
    assert summary["monthly_income"] == {"USD": "35000.00"} and summary["counts"]["events"] == 1


# ----------------------------------------------------------------------------- exports

@pytest.fixture
def run_ctx(alice):
    h = alice.post("/households/demo").json()
    for c in alice.get(f"/households/{h['id']}/constraints").json():
        alice.post(f"/constraints/{c['id']}/approve", json={"expected_revision": c["revision"]})
    scen = alice.get(f"/households/{h['id']}/scenarios").json()[0]
    run = alice.post(f"/scenarios/{scen['id']}/runs").json()
    return h["id"], run


def _download(alice, client, export):
    assert export["status"] == "ready", export
    url = alice.get(f"/exports/{export['id']}/download").json()["url"]
    r = client.get(url)
    assert r.status_code == 200
    return r.content


def test_exports_have_correct_values(alice, client, run_ctx):
    hid, run = run_ctx
    assert alice.post(f"/households/{hid}/exports", json={"kind": "simulation_csv"}).status_code == 422
    sim = alice.post(f"/households/{hid}/exports", json={"kind": "simulation_csv", "run_id": run["id"]}).json()
    rows = list(csv.DictReader(io.StringIO(_download(alice, client, sim).decode())))
    assert len(rows) == 48
    m4 = next(r for r in rows if r["model"] == "contract_aware" and r["month"] == "4")
    assert m4["ending_cash"] == "-71871.97" and m4["shortfall"] == "71871.97"
    cons = alice.post(f"/households/{hid}/exports", json={"kind": "constraints_csv"}).json()
    crow = list(csv.DictReader(io.StringIO(_download(alice, client, cons).decode())))
    assert crow and {"evidence_quote", "pdf_page", "review_status", "source_type"} <= set(crow[0])
    res = json.loads(_download(alice, client, alice.post(
        f"/households/{hid}/exports", json={"kind": "results_json", "run_id": run["id"]}).json()))
    assert res["run"]["contract_aware_summary"]["first_shortfall_month"] == 4
    assert res["approved_constraint_versions"] and res["disclaimer"]
    pdf = _download(alice, client, alice.post(
        f"/households/{hid}/exports", json={"kind": "report_pdf", "run_id": run["id"]}).json())
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        text = "".join(p.get_text() for p in d)
    assert "SlipSlopes liquidity report" in text and "Month 4" in text
    listing = alice.get(f"/households/{hid}/exports").json()
    assert listing["total"] == 4


def test_csv_formula_injection_neutralised(alice, client, run_ctx, db):
    from app.models import ExtractedConstraint
    hid, _ = run_ctx
    c = db.scalars(select(ExtractedConstraint).where(ExtractedConstraint.household_id == uuid.UUID(hid))).first()
    c.interpretation = "=HYPERLINK(\"http://evil\")"
    db.commit()
    data = _download(alice, client, alice.post(f"/households/{hid}/exports", json={"kind": "constraints_csv"}).json())
    assert "'=HYPERLINK" in data.decode()


def test_export_access_is_scoped(alice, bob, run_ctx):
    hid, run = run_ctx
    exp = alice.post(f"/households/{hid}/exports", json={"kind": "constraints_json"}).json()
    assert bob.get(f"/exports/{exp['id']}").status_code == 404
    assert bob.get(f"/exports/{exp['id']}/download").status_code == 404
    bob_h = bob.post("/households", json={"name": "Bob"}).json()["id"]
    r = bob.post(f"/households/{bob_h}/exports", json={"kind": "results_json", "run_id": run["id"]})
    assert r.status_code == 404  # cannot export another household's run


# ----------------------------------------------------------------------------- row level security

def _raw_conn():
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(url, autocommit=False)


def test_rls_limits_authenticated_role_to_member_rows(alice, bob):
    a_h = alice.post("/households", json={"name": "Alice"}).json()["id"]
    alice.post(f"/households/{a_h}/assets", json={"kind": "cash", "name": "c", "amount": "10"})
    b_h = bob.post("/households", json={"name": "Bob"}).json()["id"]
    with _raw_conn() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": str(alice.id)}),))
        cur.execute("SELECT id::text FROM households")
        assert [r[0] for r in cur.fetchall()] == [a_h]
        cur.execute("SELECT count(*) FROM assets")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM profiles")
        assert cur.fetchone()[0] == 1  # own profile only
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE households SET name = 'pwned' WHERE id = %s", (b_h,))
        conn.rollback()
    with _raw_conn() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": str(bob.id)}),))
        cur.execute("SELECT id::text FROM households")
        assert [r[0] for r in cur.fetchall()] == [b_h]
        conn.rollback()
    with _raw_conn() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL ROLE anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("SELECT * FROM households")
        conn.rollback()


# ----------------------------------------------------------------------------- rate limiting & account

def test_compute_endpoints_are_rate_limited(alice, monkeypatch, settings):
    hid = alice.post("/households", json={"name": "H"}).json()["id"]
    scen = alice.post(f"/households/{hid}/scenarios", json={"name": "s"}).json()
    monkeypatch.setattr(settings, "rate_limit_compute_per_minute", 2)
    codes = [alice.post(f"/scenarios/{scen['id']}/runs").status_code for _ in range(3)]
    assert codes[:2] == [201, 201] and codes[2] == 429
    r = alice.post(f"/scenarios/{scen['id']}/runs")
    assert r.json()["error"]["code"] == "rate_limited" and "retry-after" in r.headers


def test_account_deletion_removes_owned_data(alice, bob, db, settings):
    h = alice.post("/households/demo").json()
    shared = bob.post("/households", json={"name": "Bob's"}).json()
    db.add(HouseholdMember(household_id=uuid.UUID(shared["id"]), user_id=alice.id, role="editor"))
    db.commit()
    alice.post(f"/households/{shared['id']}/assets", json={"kind": "cash", "name": "c", "amount": "1"})
    files = list(Path(settings.local_storage_dir, h["id"]).rglob("*.pdf"))
    assert len(files) == 4
    assert alice.delete("/me", json={"confirm": "wrong"}).status_code == 422
    r = alice.delete("/me", json={"confirm": "DELETE MY ACCOUNT"})
    assert r.status_code == 200 and r.json()["households_deleted"] == 1
    db.expire_all()
    assert db.get(Household, uuid.UUID(h["id"])) is None
    assert not any(f.exists() for f in files)
    assert db.get(Household, uuid.UUID(shared["id"])) is not None  # Bob's household survives
    assert db.scalar(select(func.count()).select_from(HouseholdMember)
                     .where(HouseholdMember.user_id == alice.id)) == 0
    assert db.get(Profile, alice.id) is None
