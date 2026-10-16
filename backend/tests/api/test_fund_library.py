"""Shared fund library: firm boundaries, reviewer permissions, deduplication, effective dates, explicit
supersession, holding links and simulator integration. All documents are generated test PDFs."""
import hashlib
import json

import psycopg
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import Document, DocumentPage, ExtractedConstraint

from .conftest import make_pdf

PROSPECTUS = make_pdf(["EXAMPLE INCOME REIT - TEST PROSPECTUS (generated for tests).",
                       "The repurchase plan will be limited to no more than 2% of our aggregate NAV per month and "
                       "no more than 5% of our aggregate NAV per calendar quarter."])
SUPPLEMENT = make_pdf(["EXAMPLE INCOME REIT - TEST SUPPLEMENT NO. 1 (generated for tests).",
                       "Effective immediately, the repurchase plan will be limited to no more than 1% of our "
                       "aggregate NAV per month."])


def make_fund(user, name="Example Income REIT", fund_type="non_traded_reit", **kw):
    r = user.post("/funds", json={"name": name, "fund_type": fund_type, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def fund_upload(user, fund_id, data, filename="prospectus.pdf", category="prospectus", **kw):
    init = user.post(f"/funds/{fund_id}/documents", json={
        "filename": filename, "category": category, "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), **kw})
    assert init.status_code == 201, init.text
    body = init.json()
    if body["duplicate"]:
        return body["document"], True
    doc_id = body["document"]["id"]
    assert user.put(f"/documents/{doc_id}/content", content=data,
                    headers={"Content-Type": "application/pdf"}).status_code == 200
    assert user.post(f"/documents/{doc_id}/complete").status_code == 202
    return user.get(f"/documents/{doc_id}").json(), False


def terms(user, fund_id, as_of=None):
    r = user.get(f"/funds/{fund_id}/terms", params={"as_of": as_of} if as_of else None)
    assert r.status_code == 200, r.text
    return r.json()


def approve(user, term):
    r = user.post(f"/constraints/{term['id']}/approve", json={"expected_revision": term["revision"]})
    assert r.status_code == 200, r.text
    return r.json()


def monthly_cap(rows, doc_id):
    return next(t for t in rows if t["constraint_type"] == "redemption_monthly_cap" and t["document_id"] == doc_id)


def household_with_reit(user, fund_id=None, name="Household"):
    hid = user.post("/households", json={"name": name}).json()["id"]
    for body in ({"kind": "cash", "name": "Cash", "amount": "50000"},
                 {"kind": "non_traded_reit", "name": "REIT position", "amount": "400000", "fund_id": fund_id}):
        r = user.post(f"/households/{hid}/assets", json=body)
        assert r.status_code == 201, r.text
    return hid


def run(user, hid, as_of=None):
    assumptions = {"as_of_date": as_of} if as_of else {}
    scen = user.post(f"/households/{hid}/scenarios", json={"name": f"s {as_of}", "assumptions": assumptions}).json()
    return user.post(f"/scenarios/{scen['id']}/runs")


def add_member(admin, firm_id, user, role):
    user.get("/me/firms")  # the account must exist (first sign-in creates it)
    r = admin.post(f"/firms/{firm_id}/members", json={"email": user.email, "role": role})
    assert r.status_code == 201, r.text


# ----------------------------------------------------------------------------- firms

def test_every_account_gets_a_firm_and_households_join_it(alice):
    firms = alice.get("/me/firms").json()
    assert len(firms) == 1 and firms[0]["role"] == "admin"
    h = alice.post("/households", json={"name": "H"}).json()
    assert h["firm_id"] == firms[0]["id"]


def test_firm_membership_rules(alice, bob):
    firm = alice.get("/me/firms").json()[0]["id"]
    add_member(alice, firm, bob, "advisor")
    assert bob.post(f"/firms/{firm}/members", json={"email": "x@example.com"}).status_code == 403
    assert alice.patch(f"/firms/{firm}/members/{alice.id}", json={"role": "reviewer"}).status_code == 409
    assert alice.delete(f"/firms/{firm}/members/{alice.id}").status_code == 409  # last admin
    assert {m["role"] for m in alice.get(f"/firms/{firm}/members").json()} == {"admin", "advisor"}
    assert bob.delete(f"/firms/{firm}/members/{bob.id}").status_code == 204  # members may leave
    assert bob.get(f"/firms/{firm}/members").status_code == 404


# ----------------------------------------------------------------------------- search, isolation, dedup

def test_search_and_firm_isolation(alice, bob):
    reit = make_fund(alice, ticker="exir", issuer="Example Sponsor LLC", aliases=["EIR Class I"])
    make_fund(alice, name="Other Interval Fund", fund_type="interval_fund")
    names = lambda r: [f["name"] for f in r.json()["items"]]  # noqa: E731
    assert names(alice.get("/funds", params={"q": "income"})) == ["Example Income REIT"]
    assert names(alice.get("/funds", params={"q": "EXIR"})) == ["Example Income REIT"]  # ticker, case-insensitive
    assert names(alice.get("/funds", params={"q": "sponsor"})) == ["Example Income REIT"]
    assert names(alice.get("/funds", params={"q": "class i"})) == ["Example Income REIT"]  # alias
    assert names(alice.get("/funds", params={"q": "%"})) == []  # LIKE wildcards are literal
    assert names(alice.get("/funds", params={"fund_type": "interval_fund"})) == ["Other Interval Fund"]
    assert alice.post("/funds", json={"name": "example income reit", "fund_type": "other"}).status_code == 409

    doc, _ = fund_upload(alice, reit["id"], PROSPECTUS)
    term = monthly_cap(terms(alice, reit["id"])["terms"], doc["id"])
    assert bob.get("/funds").json()["total"] == 0
    for url in (f"/funds/{reit['id']}", f"/funds/{reit['id']}/terms", f"/funds/{reit['id']}/documents",
                f"/documents/{doc['id']}", f"/documents/{doc['id']}/pages/1", f"/constraints/{term['id']}",
                f"/funds/{reit['id']}/audit-events"):
        assert bob.get(url).status_code == 404, url
    assert bob.post(f"/constraints/{term['id']}/approve", json={"expected_revision": 1}).status_code == 404


def test_library_document_stored_once_with_verified_evidence(alice, db):
    fund = make_fund(alice)
    doc, dup = fund_upload(alice, fund["id"], PROSPECTUS, effective_date="2026-01-01")
    assert not dup and doc["status"] == "extracted" and doc["fund_id"] == fund["id"] and doc["household_id"] is None
    again, dup = fund_upload(alice, fund["id"], PROSPECTUS, filename="copy.pdf")
    assert dup and again["id"] == doc["id"]
    rows = terms(alice, fund["id"])["terms"]
    cap = monthly_cap(rows, doc["id"])
    assert float(cap["value"]) == 2.0 and cap["quote_verified"] and cap["review_status"] == "needs_review"
    assert cap["fund_id"] == fund["id"] and cap["household_id"] is None
    page = alice.get(f"/documents/{doc['id']}/pages/{cap['pdf_page']}").json()
    assert "no more than 2% of our aggregate NAV per month" in " ".join(page["text"].split())
    assert db.scalar(select(func.count()).select_from(Document).where(Document.fund_id == fund["id"])) == 1
    assert db.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.fund_id == fund["id"])) == 1
    # Household agreements stay private: the same bytes uploaded to a household are a separate household record.
    hid = alice.post("/households", json={"name": "H"}).json()["id"]
    from .conftest import upload
    hdoc, _ = upload(alice, hid, PROSPECTUS, filename="p.pdf", category="prospectus")
    assert hdoc["id"] != doc["id"] and hdoc["household_id"] == hid and hdoc["fund_id"] is None


def test_reviewer_permissions(alice, bob):
    firm = alice.get("/me/firms").json()[0]["id"]
    fund = make_fund(alice)
    add_member(alice, firm, bob, "advisor")
    doc, _ = fund_upload(bob, fund["id"], SUPPLEMENT, filename="supp.pdf", category="prospectus_supplement")
    cap = monthly_cap(terms(bob, fund["id"])["terms"], doc["id"])
    assert bob.post(f"/constraints/{cap['id']}/approve", json={"expected_revision": 1}).status_code == 403
    assert bob.patch(f"/constraints/{cap['id']}", json={"expected_revision": 1, "value": "3"}).status_code == 403
    assert bob.patch(f"/funds/{fund['id']}", json={"metadata_status": "verified"}).status_code == 403
    assert bob.patch(f"/documents/{doc['id']}/library-metadata",
                     json={"effective_date": "2026-08-01"}).status_code == 403
    assert bob.delete(f"/documents/{doc['id']}").status_code == 403
    assert alice.patch(f"/firms/{firm}/members/{bob.id}", json={"role": "reviewer"}).status_code == 200
    approved = approve(bob, cap)
    assert approved["review_status"] == "confirmed" and approved["reviewed_by"] == str(bob.id)
    events = [e["action"] for e in alice.get(f"/funds/{fund['id']}/audit-events").json()["items"]]
    assert "constraint.reviewed" in events and "fund.created" in events


def test_library_document_cannot_be_deleted_once_terms_are_approved(alice):
    fund = make_fund(alice)
    doc, _ = fund_upload(alice, fund["id"], PROSPECTUS)
    approve(alice, monthly_cap(terms(alice, fund["id"])["terms"], doc["id"]))
    r = alice.delete(f"/documents/{doc['id']}")
    assert r.status_code == 409 and "superseding" in r.json()["error"]["message"]
    other, _ = fund_upload(alice, fund["id"], SUPPLEMENT, filename="s.pdf")
    assert alice.delete(f"/documents/{other['id']}").status_code == 200  # nothing approved yet


# ----------------------------------------------------------------------------- linking and simulation

def test_holding_link_validation(alice, bob):
    reit = make_fund(alice)
    interval = make_fund(alice, name="Other Interval Fund", fund_type="interval_fund")
    hid = alice.post("/households", json={"name": "H"}).json()["id"]
    wrong_kind = alice.post(f"/households/{hid}/assets", json={"kind": "non_traded_reit", "name": "x",
                                                                "amount": "1", "fund_id": interval["id"]})
    assert wrong_kind.status_code == 422 and "interval_fund" in wrong_kind.json()["error"]["message"]
    asset = alice.post(f"/households/{hid}/assets", json={"kind": "non_traded_reit", "name": "x", "amount": "1",
                                                           "fund_id": reit["id"]}).json()
    assert asset["fund_id"] == reit["id"] and asset["fund_name"] == "Example Income REIT"
    assert alice.patch(f"/assets/{asset['id']}", json={"kind": "cash"}).status_code == 422  # still linked
    assert alice.patch(f"/assets/{asset['id']}", json={"fund_id": None}).json()["fund_id"] is None
    # A fund from another firm's library cannot be linked (bob's household is in bob's firm).
    b_hid = bob.post("/households", json={"name": "B"}).json()["id"]
    r = bob.post(f"/households/{b_hid}/assets", json={"kind": "non_traded_reit", "name": "x", "amount": "1",
                                                      "fund_id": reit["id"]})
    assert r.status_code == 404  # bob cannot even see the fund
    assert alice.patch(f"/funds/{reit['id']}", json={"status": "archived"}).status_code == 200
    archived = alice.post(f"/households/{hid}/assets", json={"kind": "non_traded_reit", "name": "y", "amount": "1",
                                                              "fund_id": reit["id"]})
    assert archived.status_code == 422


def test_unapproved_library_terms_are_not_used(alice):
    fund = make_fund(alice)
    fund_upload(alice, fund["id"], SUPPLEMENT)  # 1% cap, not approved
    r = run(alice, household_with_reit(alice, fund["id"]))
    assert r.status_code == 201, r.text
    body = r.json()
    cap = next(t for t in body["terms"] if t["term"] == "reit_monthly_cap_pct")
    assert cap["value"] == 2.0 and cap["provenance"].startswith("default")
    assert any("no approved terms in force" in w for w in body["warnings"])
    assert not [v for v in body["constraint_versions"] if v["owner"] == "fund"]


def test_two_households_share_one_canonical_fund(alice, db):
    fund = make_fund(alice)
    doc, _ = fund_upload(alice, fund["id"], SUPPLEMENT)
    approve(alice, monthly_cap(terms(alice, fund["id"])["terms"], doc["id"]))
    h1 = household_with_reit(alice, fund["id"], "Client A")
    h2 = household_with_reit(alice, fund["id"], "Client B")
    runs = [run(alice, h).json() for h in (h1, h2)]
    used = [{v["id"] for v in r["constraint_versions"] if v["owner"] == "fund"} for r in runs]
    assert used[0] == used[1] and len(used[0]) == 1
    for r in runs:
        cap = next(t for t in r["terms"] if t["term"] == "reit_monthly_cap_pct")
        assert cap["value"] == 1.0 and cap["source_backed"]
    assert db.scalar(select(func.count()).select_from(ExtractedConstraint)
                     .where(ExtractedConstraint.document_id == doc["id"])) == len(terms(alice, fund["id"])["terms"])
    detail = alice.get(f"/funds/{fund['id']}").json()
    assert detail["linked_holdings_total"] == 2 and {h["household_name"] for h in detail["linked_holdings"]} == {
        "Client A", "Client B"}


def test_effective_dates_and_explicit_supersession(alice):
    fund = make_fund(alice)
    pro, _ = fund_upload(alice, fund["id"], PROSPECTUS, effective_date="2026-01-01")
    sup, _ = fund_upload(alice, fund["id"], SUPPLEMENT, filename="supplement.pdf",
                         category="prospectus_supplement", effective_date="2026-08-01",
                         supersedes_document_id=pro["id"])
    assert sup["supersedes_document_id"] == pro["id"]
    rows = terms(alice, fund["id"])["terms"]
    old = approve(alice, monthly_cap(rows, pro["id"]))
    new = approve(alice, monthly_cap(rows, sup["id"]))
    assert old["effective_from"] == "2026-01-01" and new["effective_from"] == "2026-08-01"  # from document dates
    hid = household_with_reit(alice, fund["id"])

    # Both approved caps are in force in September: the run is blocked, never silently resolved.
    blocked = run(alice, hid, "2026-09-01")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "term_conflict"
    assert "superseding" in blocked.json()["error"]["message"]
    # Before the supplement takes effect only the prospectus cap applies.
    march = run(alice, hid, "2026-03-01").json()
    assert next(t for t in march["terms"] if t["term"] == "reit_monthly_cap_pct")["value"] == 2.0

    r = alice.post(f"/constraints/{new['id']}/supersede", json={
        "expected_revision": new["revision"], "superseded_id": old["id"],
        "superseded_expected_revision": old["revision"]})
    assert r.status_code == 200, r.text
    newer, older = r.json()
    assert older["effective_to"] == "2026-08-01" and older["superseded_by_id"] == new["id"]
    assert older["review_status"] == "confirmed"  # history kept, approval unchanged
    sept = terms(alice, fund["id"], "2026-09-01")
    assert new["id"] in sept["applicable_ids"] and old["id"] not in sept["applicable_ids"]
    assert old["id"] in terms(alice, fund["id"], "2026-03-01")["applicable_ids"]

    after = run(alice, hid, "2026-09-01")
    assert after.status_code == 201, after.text
    body = after.json()
    cap = next(t for t in body["terms"] if t["term"] == "reit_monthly_cap_pct")
    assert cap["value"] == 1.0 and "supplement.pdf" in cap["provenance"]
    quarterly = next(t for t in body["terms"] if t["term"] == "reit_quarterly_cap_pct")
    assert quarterly["value"] == 5.0  # not superseded: still from the prospectus
    version = next(v for v in body["constraint_versions"] if v["id"] == new["id"])
    assert version["owner"] == "fund" and version["effective_from"] == "2026-08-01"
    # The earlier March run keeps the term version it used.
    assert alice.get(f"/runs/{march['id']}").json()["constraint_versions"] == march["constraint_versions"]

    again = alice.post(f"/constraints/{new['id']}/supersede", json={
        "expected_revision": newer["revision"], "superseded_id": old["id"],
        "superseded_expected_revision": older["revision"]})
    assert again.status_code == 409
    quarterly_term = next(t for t in terms(alice, fund["id"])["terms"]
                          if t["constraint_type"] == "redemption_quarterly_cap")
    approve(alice, quarterly_term)
    wrong = alice.post(f"/constraints/{new['id']}/supersede", json={
        "expected_revision": newer["revision"], "superseded_id": quarterly_term["id"],
        "superseded_expected_revision": quarterly_term["revision"] + 1})
    assert wrong.status_code == 422


def test_document_supersession_cycle_rejected(alice):
    fund = make_fund(alice)
    a, _ = fund_upload(alice, fund["id"], PROSPECTUS)
    b, _ = fund_upload(alice, fund["id"], SUPPLEMENT, filename="b.pdf", supersedes_document_id=a["id"])
    r = alice.patch(f"/documents/{a['id']}/library-metadata", json={"supersedes_document_id": b["id"]})
    assert r.status_code == 422 and "cycle" in r.json()["error"]["message"]
    other = make_fund(alice, name="Other")
    r = alice.post(f"/funds/{other['id']}/documents", json={"filename": "c.pdf", "category": "prospectus",
                                                             "size_bytes": 10, "supersedes_document_id": a["id"]})
    assert r.status_code == 422


def test_rls_limits_library_rows_to_firm_members(alice, bob):
    fund = make_fund(alice)
    doc, _ = fund_upload(alice, fund["id"], PROSPECTUS)
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    for user, expected in ((alice, 1), (bob, 0)):
        with psycopg.connect(url, autocommit=False) as conn:
            cur = conn.cursor()
            cur.execute("SET LOCAL ROLE authenticated")
            cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": str(user.id)}),))
            for table in ("funds", "documents", "document_pages"):
                cur.execute(f"SELECT count(*) FROM {table} WHERE fund_id IS NOT NULL" if table != "funds"
                            else "SELECT count(*) FROM funds")
                assert cur.fetchone()[0] == expected, (user.email, table)
            cur.execute("SELECT count(*) FROM extracted_constraints WHERE document_id = %s", (doc["id"],))
            assert (cur.fetchone()[0] > 0) == bool(expected)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("UPDATE funds SET name = 'x'")
            conn.rollback()


def test_account_deletion_hands_firm_to_remaining_member(alice, bob):
    firm = alice.get("/me/firms").json()[0]["id"]
    add_member(alice, firm, bob, "advisor")
    make_fund(alice)
    assert alice.delete("/me", json={"confirm": "DELETE MY ACCOUNT"}).status_code == 200
    assert [m["role"] for m in bob.get(f"/firms/{firm}/members").json()] == ["admin"]
    assert bob.get("/funds").json()["total"] == 1


def _load_backfill():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_fund_library.py"
    spec = importlib.util.spec_from_file_location("backfill_fund_library", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_same_file_in_two_households_is_shared_to_library(alice):
    from .conftest import upload
    hids = [household_with_reit(alice, None, n) for n in ("A", "B", "C")]
    src = upload(alice, hids[0], PROSPECTUS, filename="Example-REIT-Prospectus.pdf", category="prospectus")[0]
    assert alice.get("/funds").json()["total"] == 0  # one household is not yet shared
    first = alice.get(f"/households/{hids[0]}/constraints").json()
    approve(alice, next(c for c in first if c["constraint_type"] == "redemption_monthly_cap"))
    before = alice.get(f"/households/{hids[0]}/constraints").json()

    upload(alice, hids[1], PROSPECTUS, filename="Example-REIT-Prospectus.pdf", category="prospectus")
    funds = alice.get("/funds").json()["items"]
    assert len(funds) == 1 and funds[0]["metadata_status"] == "needs_review" and funds[0]["fund_type"] == "non_traded_reit"
    assert funds[0]["name"] == "Example REIT Prospectus (confirm name)"
    lib = alice.get(f"/funds/{funds[0]['id']}/documents").json()
    assert len(lib) == 1 and lib[0]["sha256"] == src["sha256"]
    lib_terms = terms(alice, funds[0]["id"])["terms"]
    assert lib_terms and all(t["review_status"] == "needs_review" for t in lib_terms)
    detail = alice.get(f"/constraints/{lib_terms[0]['id']}").json()
    assert "Shared from household document" in detail["revisions"][0]["note"]
    assert alice.get(f"/documents/{lib[0]['id']}/download").status_code == 200
    # Originals and their approvals unchanged, holdings not linked automatically.
    assert alice.get(f"/households/{hids[0]}/constraints").json() == before
    assert all(a["fund_id"] is None for h in hids for a in alice.get(f"/households/{h}/assets").json())

    upload(alice, hids[2], PROSPECTUS, filename="Example-REIT-Prospectus.pdf", category="prospectus")
    assert alice.get("/funds").json()["total"] == 1  # identical files stored once per firm
    assert len(alice.get(f"/funds/{funds[0]['id']}/documents").json()) == 1


def test_repeated_demo_households_share_only_public_fund_documents(alice):
    for _ in range(2):
        assert alice.post("/households/demo").status_code == 201
    funds = alice.get("/funds").json()["items"]
    # Of the four synthetic contracts only the interval fund policy is a public offering document; the LPA,
    # credit line and RSU agreements stay in their households.
    assert [(f["name"], f["fund_type"]) for f in funds] == [
        ("SYNTHETIC Interval Fund Repurchase Policy (confirm name)", "interval_fund")]
    lib = alice.get(f"/funds/{funds[0]['id']}/documents").json()
    assert len(lib) == 1 and lib[0]["is_demo_fixture"] is True


def test_backfill_copies_without_touching_household_records(alice, db):
    from .conftest import upload
    backfill = _load_backfill().backfill
    hid = household_with_reit(alice, None, "A")
    src = upload(alice, hid, PROSPECTUS, filename="Example-REIT-Prospectus.pdf", category="prospectus")[0]
    before = alice.get(f"/households/{hid}/constraints").json()

    assert backfill(db, apply=False, include_demo=False, min_households=2) == []
    plan = backfill(db, apply=False, include_demo=False)
    db.rollback()
    assert plan[0].startswith("PLAN") and "1 household(s)" in plan[0]
    assert sum("candidate holding" in line for line in plan) == 1
    assert alice.get("/funds").json()["total"] == 0  # dry run wrote nothing

    done = backfill(db, apply=True, include_demo=False)
    assert done[0].startswith("COPY")
    funds = alice.get("/funds").json()["items"]
    assert len(funds) == 1 and funds[0]["fund_type"] == "non_traded_reit"
    lib = alice.get(f"/funds/{funds[0]['id']}/documents").json()
    assert len(lib) == 1 and lib[0]["sha256"] == src["sha256"]
    detail = alice.get(f"/constraints/{terms(alice, funds[0]['id'])['terms'][0]['id']}").json()
    assert "Backfilled from household document" in detail["revisions"][0]["note"]
    assert alice.get(f"/households/{hid}/constraints").json() == before

    again = backfill(db, apply=True, include_demo=False)
    assert again[0].startswith("SKIP") and alice.get("/funds").json()["total"] == 1


def test_review_queue_and_scenario_list_respect_roles(alice, bob):
    firm = alice.get("/me/firms").json()[0]["id"]
    fund = make_fund(alice)
    fund_upload(alice, fund["id"], SUPPLEMENT)
    hid = alice.post("/households/demo").json()["id"]
    q = alice.get("/me/review-queue").json()
    assert q["library_items"] >= 1 and q["household_items"] >= 1
    assert {i["owner_type"] for i in q["items"]} == {"household", "fund"}
    assert all(i["constraint"]["review_status"] == "needs_review" for i in q["items"])
    add_member(alice, firm, bob, "advisor")
    assert bob.get("/me/review-queue").json()["total"] == 0  # advisors cannot review library terms
    alice.patch(f"/firms/{firm}/members/{bob.id}", json={"role": "reviewer"})
    bq = bob.get("/me/review-queue").json()
    assert bq["library_items"] == q["library_items"] and bq["household_items"] == 0  # no access to alice's household
    scen = alice.get("/me/scenarios").json()
    assert scen and scen[0]["household_id"] == hid and scen[0]["latest_run_id"] is None
    assert bob.get("/me/scenarios").json() == []
