"""End-to-end acceptance run against a *running* local stack (not part of the unit test suite).

Requires: API on :8000, Celery worker, Redis, Supabase Auth (GoTrue) behind the dev gateway on :54321,
Mailpit on :8025 (see docs/LOCAL_DEVELOPMENT.md). Exercises real auth emails, real storage writes,
real queue processing and real database persistence. It does not exercise a live LLM provider.

    python scripts/e2e_local.py [path/to/prospectus.pdf]
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

API = "http://localhost:8000/api/v1"
AUTH = "http://localhost:54321/auth/v1"
MAILPIT = "http://localhost:8025/api/v1"
ANON_KEY = Path(sys.argv[2]).read_text().strip() if len(sys.argv) > 2 else ""
FIXTURES = Path(__file__).resolve().parents[1] / "app" / "engine" / "fixtures"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        raise SystemExit(1)


def mail_link(to: str, kind: str, timeout: float = 20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = httpx.get(f"{MAILPIT}/search", params={"query": f"to:{to}"}).json().get("messages", [])
        for m in msgs:
            body = httpx.get(f"{MAILPIT}/message/{m['ID']}").json()
            text = body.get("Text", "") + body.get("HTML", "")
            for link in re.findall(r"https?://[^\s\"'<>]+", text):
                link = link.replace("&amp;", "&")
                if "/verify" in link and f"type={kind}" in link:
                    return link
        time.sleep(1)
    raise SystemExit(f"no {kind} email for {to}")


def auth_headers() -> dict:
    return {"apikey": ANON_KEY, "Content-Type": "application/json"}


def signup_and_login(email: str, password: str) -> str:
    r = httpx.post(f"{AUTH}/signup", json={"email": email, "password": password}, headers=auth_headers())
    check(f"signup {email}", r.status_code == 200, str(r.status_code))
    pre = httpx.post(f"{AUTH}/token", params={"grant_type": "password"}, headers=auth_headers(),
                     json={"email": email, "password": password})
    check("login blocked before email confirmation", pre.status_code == 400)
    link = mail_link(email, "signup")
    v = httpx.get(link, follow_redirects=False)
    confirmed = v.status_code in (302, 303) and "access_token" in v.headers.get("location", "")
    check("email confirmation link accepted", confirmed)
    return login(email, password)


def login(email: str, password: str) -> str:
    r = httpx.post(f"{AUTH}/token", params={"grant_type": "password"}, headers=auth_headers(),
                   json={"email": email, "password": password})
    check(f"login {email}", r.status_code == 200, str(r.status_code))
    return r.json()["access_token"]


class Api:
    def __init__(self, token: str):
        self.c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=120)

    def __getattr__(self, name):
        return getattr(self.c, name)


def wait_document(api: Api, doc_id: str, timeout: float = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = api.get(f"/documents/{doc_id}").json()
        if d["status"] in ("extracted", "failed"):
            return d
        time.sleep(2)
    raise SystemExit("document processing timed out")


def upload(api: Api, hid: str, data: bytes, name: str, category: str) -> dict:
    init = api.post(f"/households/{hid}/documents", json={"filename": name, "category": category,
                                                           "size_bytes": len(data),
                                                           "sha256": hashlib.sha256(data).hexdigest()}).json()
    doc_id = init["document"]["id"]
    put = api.put(f"/documents/{doc_id}/content", content=data, headers={"Content-Type": "application/pdf"})
    check(f"upload {name} stored", put.status_code == 200 and put.json()["status"] == "uploaded",
          f"{len(data) / 1e6:.1f} MB")
    job = api.post(f"/documents/{doc_id}/complete").json()
    check(f"processing job queued for {name}", job["status"] in ("queued", "running"), job["status"])
    return wait_document(api, doc_id)


def main() -> None:
    prospectus = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    stamp = uuid.uuid4().hex[:8]
    a_email, b_email, pw = f"advisor-{stamp}@example.com", f"other-{stamp}@example.com", "Correct-Horse-91!"

    # 1-2. register, confirm, log in, create household
    a = Api(signup_and_login(a_email, pw))
    hid = a.post("/households", json={"name": f"E2E household {stamp}"}).json()["id"]
    # 3. financial records
    for body in ({"kind": "cash", "name": "Cash", "amount": "250000"},
                 {"kind": "brokerage", "name": "Brokerage", "amount": "600000", "pledged_to_sbl": True},
                 {"kind": "non_traded_reit", "name": "BREIT", "amount": "500000"},
                 {"kind": "interval_fund", "name": "Interval fund", "amount": "300000"},
                 {"kind": "vested_rsu", "name": "RSUs", "amount": "150000"}):
        check(f"create asset {body['kind']}", a.post(f"/households/{hid}/assets", json=body).status_code == 201)
    a.post(f"/households/{hid}/liabilities", json={"kind": "sbl", "name": "SBL", "balance": "300000",
                                                   "annual_rate": "0.0725"})
    for body in ({"kind": "income", "name": "Salary", "monthly_amount": "35000"},
                 {"kind": "core_expense", "name": "Core", "monthly_amount": "30000"},
                 {"kind": "discretionary_expense", "name": "Discretionary", "monthly_amount": "15000"}):
        a.post(f"/households/{hid}/cash-flows", json=body)
    for body in ({"kind": "capital_call", "month": 4, "amount": "250000"},
                 {"kind": "rsu_vest", "month": 2, "amount": "300000", "tax_due_month": 4},
                 {"kind": "reit_redemption_request", "month": 1, "amount": "100000"},
                 {"kind": "interval_redemption_request", "month": 3, "amount": "150000"}):
        a.post(f"/households/{hid}/events", json=body)
    asset = a.get(f"/households/{hid}/assets").json()[0]
    edited = a.patch(f"/assets/{asset['id']}", json={"name": asset["name"] + " (edited)"})
    check("edit asset", edited.status_code == 200)

    # 4-7. upload a prospectus and the synthetic SBL agreement; real worker processing
    if prospectus and prospectus.exists():
        doc = upload(a, hid, prospectus.read_bytes(), prospectus.name, "prospectus")
        check("prospectus extracted", doc["status"] == "extracted",
              f"pages={doc['page_count']} constraints={doc['constraint_count']}")
    sbl = upload(a, hid, (FIXTURES / "SYNTHETIC_Securities_Backed_Line_Agreement.pdf").read_bytes(),
                 "SYNTHETIC_Securities_Backed_Line_Agreement.pdf", "sbl_agreement")
    check("SBL agreement extracted", sbl["status"] == "extracted", f"constraints={sbl['constraint_count']}")
    cons = a.get(f"/households/{hid}/constraints").json()
    caps = {c["constraint_type"]: c for c in cons if c["asset_key"] == "non_traded_reit"}
    if prospectus:
        m = caps["redemption_monthly_cap"]
        check("BREIT 2% monthly cap with verified evidence", float(m["value"]) == 2.0 and m["quote_verified"],
              f"PDF p.{m['pdf_page']} printed p.{m['printed_page']} ({m['document_section']})")
        page = a.get(f"/documents/{m['document_id']}/pages/{m['pdf_page']}").json()
        check("evidence quote present on cited page",
              " ".join(m["evidence_quote"].split())[:120] in " ".join(page["text"].replace("’", "'").split()))
    # 8-9. correct and approve constraints
    adv = next(c for c in cons if c["constraint_type"] == "sbl_advance_rate")
    e = a.patch(f"/constraints/{adv['id']}", json={"expected_revision": adv["revision"], "value": "50",
                                                   "note": "confirmed with lender"})
    check("constraint edit accepted", e.status_code == 200)
    for c in a.get(f"/households/{hid}/constraints").json():
        if c["review_status"] == "needs_review":
            a.post(f"/constraints/{c['id']}/approve", json={"expected_revision": c["revision"]})
    approved = [c for c in a.get(f"/households/{hid}/constraints").json()
                if c["review_status"] in ("confirmed", "edited")]
    check("constraints approved and persisted", len(approved) == len(cons), f"{len(approved)} approved")

    # 10-12. scenario + simulation
    scen = a.post(f"/households/{hid}/scenarios", json={"name": "25% drawdown"}).json()
    run = a.post(f"/scenarios/{scen['id']}/runs").json()
    terms = {t["term"]: t for t in run["terms"]}
    check("simulation persisted with both models", len(run["months"]) == 48,
          f"aware first shortfall M{run['aware_summary']['first_shortfall_month']} "
          f"{run['aware_summary']['shortfall_amount']}; naive {run['naive_summary']['first_shortfall_month']}")
    if prospectus:
        check("REIT caps source-backed from the uploaded prospectus", terms["reit_monthly_cap_pct"]["source_backed"],
              terms["reit_monthly_cap_pct"]["provenance"])
    # 13-14. reverse stress + prevention
    st = a.post(f"/scenarios/{scen['id']}/stress", json={}).json()
    check("reverse stress", "found" in st, f"boundary={st['boundary_drawdown']} month={st['first_shortfall_month']}")
    plan = a.post(f"/scenarios/{scen['id']}/prevention", json={}).json()
    check("prevention plan ranked and verified", plan["combined_verified"],
          f"{len(plan['recommendations'])} recommendations, cost {plan['combined_cost']}")
    # 15. exports
    exp = a.post(f"/households/{hid}/exports", json={"kind": "report_pdf", "run_id": run["id"]}).json()
    for _ in range(60):
        exp = a.get(f"/exports/{exp['id']}").json()
        if exp["status"] in ("ready", "failed"):
            break
        time.sleep(1)
    check("PDF report generated by worker", exp["status"] == "ready", f"{exp['size_bytes']} bytes")
    url = a.get(f"/exports/{exp['id']}/download").json()["url"]
    pdf = httpx.get(url if url.startswith("http") else "http://localhost:8000" + url)
    check("signed export download", pdf.status_code == 200 and pdf.content[:5] == b"%PDF-")

    # 16. logout / login keeps records
    r = httpx.post(f"{AUTH}/logout", headers={**auth_headers(), "Authorization": a.headers["Authorization"]})
    check("logout", r.status_code == 204, str(r.status_code))
    a = Api(login(a_email, pw))
    check("records persist across sessions", a.get(f"/households/{hid}/runs").json()["total"] == 1)

    # 17. another account cannot access
    b = Api(signup_and_login(b_email, pw))
    for url in (f"/households/{hid}", f"/documents/{sbl['id']}", f"/documents/{sbl['id']}/download",
                f"/runs/{run['id']}", f"/exports/{exp['id']}/download"):
        check(f"other account denied {url}", b.get(url).status_code == 404)

    # 18. failed extraction can be retried; deletion follows retention policy
    import pymupdf
    blank = pymupdf.open()
    blank.new_page()
    failed = upload(a, hid, blank.tobytes(), "blank-scan.pdf", "other")
    check("text-less document fails clearly", failed["status"] == "failed", failed["error_code"] or "")
    retry = a.post(f"/documents/{failed['id']}/retry")
    check("retry accepted", retry.status_code == 202)
    again = wait_document(a, failed["id"])
    jobs = a.get(f"/documents/{failed['id']}/jobs").json()
    check("retry processed (deterministically fails again)", again["status"] == "failed", f"jobs={len(jobs)}")
    d = a.delete(f"/documents/{sbl['id']}")
    check("document deleted", d.status_code == 200 and a.get(f"/documents/{sbl['id']}/download").status_code == 404)

    # Password recovery
    r = httpx.post(f"{AUTH}/recover", json={"email": a_email}, headers=auth_headers())
    check("recovery email requested", r.status_code == 200)
    link = mail_link(a_email, "recovery")
    loc = httpx.get(link, follow_redirects=False).headers.get("location", "")
    token = re.search(r"access_token=([^&]+)", loc)
    check("recovery link yields a session", token is not None)
    new_pw = "Another-Horse-42!"
    u = httpx.put(f"{AUTH}/user", json={"password": new_pw},
                  headers={**auth_headers(), "Authorization": f"Bearer {token.group(1)}"})
    check("password updated", u.status_code == 200)
    Api(login(a_email, new_pw))

    print(f"\n{sum(ok for _, ok, _ in results)}/{len(results)} checks passed")


if __name__ == "__main__":
    main()
