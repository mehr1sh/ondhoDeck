"""Authentication failures and cross-user / cross-household authorization."""
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.models import HouseholdMember

from .conftest import make_pdf, make_token, upload


def test_health_needs_no_auth(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ready_reports_database(client):
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"].startswith("ok")


@pytest.mark.parametrize("header,code", [
    (None, "not_authenticated"),
    ("Bearer", "not_authenticated"),
    ("Basic abc", "not_authenticated"),
    ("Bearer not-a-jwt", "invalid_token"),
])
def test_missing_or_malformed_token(client, header, code):
    headers = {"Authorization": header} if header else {}
    r = client.get("/api/v1/households", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == code
    assert "request_id" in r.json()["error"]


def test_expired_wrong_audience_wrong_secret_and_service_role(client):
    uid = uuid.uuid4()
    cases = {
        "token_expired": make_token(uid, exp_in=-120),
        "invalid_token": make_token(uid, aud="someone-else"),
    }
    for code, token in cases.items():
        r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401 and r.json()["error"]["code"] == code
    forged = make_token(uid, secret="not-the-server-secret-but-long-enough-000000")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    service = make_token(uid, role="service_role")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {service}"}).status_code == 403


def test_asymmetric_token_verified_against_jwks(client, monkeypatch, settings):
    """ES256 tokens (Supabase JWT signing keys) are verified with the key fetched from JWKS."""
    key = ec.generate_private_key(ec.SECP256R1())
    uid = uuid.uuid4()
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")

    class FakeJwks:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr("app.auth._jwks_client", lambda url: FakeJwks())
    import time
    claims = {"sub": str(uid), "aud": "authenticated", "exp": int(time.time()) + 600, "role": "authenticated",
              "iss": "https://example.supabase.co/auth/v1", "email": "es@example.com"}
    good = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "k1"})
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {good}"})
    assert r.status_code == 200 and r.json()["id"] == str(uid)
    wrong_iss = jwt.encode({**claims, "iss": "https://evil.example/auth/v1"}, key, algorithm="ES256")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {wrong_iss}"}).status_code == 401


def test_profile_created_from_verified_identity(alice):
    r = alice.get("/me")
    assert r.status_code == 200
    assert r.json()["id"] == str(alice.id) and r.json()["email"] == alice.email


def test_cross_user_household_access_denied(alice, bob):
    h = alice.post("/households", json={"name": "Alice family"}).json()
    hid = h["id"]
    asset = alice.post(f"/households/{hid}/assets", json={"kind": "cash", "name": "Cash", "amount": "1000"}).json()
    scen = alice.post(f"/households/{hid}/scenarios", json={"name": "Base"}).json()
    run = alice.post(f"/scenarios/{scen['id']}/runs").json()
    doc, _ = upload(alice, hid, make_pdf(["Hello"]), complete=False)

    assert bob.get("/households").json()["total"] == 0
    for url in (f"/households/{hid}", f"/households/{hid}/summary", f"/households/{hid}/assets",
                f"/households/{hid}/documents", f"/households/{hid}/constraints", f"/households/{hid}/scenarios",
                f"/households/{hid}/runs", f"/scenarios/{scen['id']}", f"/runs/{run['id']}",
                f"/documents/{doc['id']}", f"/documents/{doc['id']}/download", f"/households/{hid}/audit-events"):
        r = bob.get(url)
        assert r.status_code == 404, (url, r.status_code)
    assert bob.patch(f"/households/{hid}", json={"name": "x"}).status_code == 404
    assert bob.delete(f"/households/{hid}").status_code == 404
    assert bob.patch(f"/assets/{asset['id']}", json={"amount": "5"}).status_code == 404
    assert bob.delete(f"/assets/{asset['id']}").status_code == 404
    assert bob.post(f"/households/{hid}/assets", json={"kind": "cash", "name": "x", "amount": "1"}).status_code == 404
    assert bob.post(f"/scenarios/{scen['id']}/runs").status_code == 404
    assert bob.put(f"/documents/{doc['id']}/content", content=make_pdf(),
                   headers={"Content-Type": "application/pdf"}).status_code == 404
    assert bob.delete(f"/documents/{doc['id']}").status_code == 404
    # Alice's data is untouched.
    assert alice.get(f"/households/{hid}/assets").json()[0]["amount"] == "1000.00"


def test_user_id_in_body_is_ignored(alice, bob):
    """Ownership comes from the verified token, never from client-supplied ids."""
    r = bob.post("/households", json={"name": "Mine", "created_by": str(alice.id)})
    assert r.status_code == 201
    assert alice.get("/households").json()["total"] == 0


def test_viewer_role_cannot_modify(alice, bob, db):
    hid = alice.post("/households", json={"name": "Shared"}).json()["id"]
    bob.get("/me")  # creates Bob's profile
    db.add(HouseholdMember(household_id=uuid.UUID(hid), user_id=bob.id, role="viewer"))
    db.commit()
    assert bob.get(f"/households/{hid}").json()["role"] == "viewer"
    r = bob.post(f"/households/{hid}/assets", json={"kind": "cash", "name": "x", "amount": "1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert bob.delete(f"/households/{hid}").status_code == 403


def test_validation_errors_use_envelope(alice):
    r = alice.post("/households", json={"name": "", "reporting_currency": "dollars"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error" and body["details"]


def test_cors_restricted_to_configured_origin(client):
    ok = client.options("/api/v1/households", headers={"Origin": "http://localhost:3000",
                                                        "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options("/api/v1/households", headers={"Origin": "https://evil.example",
                                                         "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
