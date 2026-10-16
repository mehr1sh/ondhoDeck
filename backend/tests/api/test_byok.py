"""BYOK: encrypted storage, masking, testing, isolation, and use by the extraction worker.

Provider calls are replaced by fakes: these tests prove storage, authorization and plumbing, not a
live provider integration.
"""
import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import select

from app.crypto import CredentialCipher, CredentialDecryptionError
from app.llm.base import ConnectionResult, Usage
from app.models import AuditEvent, ProcessingJob, ProviderCredential

from .conftest import upload

FAKE_KEY = "sk-ant-test-THISISNOTAREALKEY-0123456789abcdef"
OPENAI_KEY = "sk-proj-test-ALSONOTREAL-9876543210fedcba"
FIXTURES = Path(__file__).resolve().parents[2] / "app" / "engine" / "fixtures"


class FakeProvider:
    def __init__(self, provider, api_key, model, ok=True, code="ok"):
        self.name, self.model, self.api_key = provider, model, api_key
        self._ok, self._code = ok, code
        self.last_usage, self.last_latency_ms = Usage(1200, 300), 42

    def test_connection(self):
        return ConnectionResult(ok=self._ok, code=self._code,
                                message="Connected." if self._ok else "The API key was rejected.", model_checked=self.model)

    def list_models(self):
        return ["model-a", "model-b"]

    def extract_json(self, system, user, schema):
        assert "untrusted document content" in system
        return {"terms": []}


@pytest.fixture
def fake_providers(monkeypatch):
    built = []

    def factory(ok=True, code="ok"):
        def build(provider, api_key, model, settings, workspace_id=None):
            p = FakeProvider(provider, api_key, model, ok, code)
            p.workspace_id = workspace_id
            built.append(p)
            return p
        monkeypatch.setattr("app.routers.ai_providers.build_provider", build)
        monkeypatch.setattr("app.services.processing.build_provider", build)
        return built
    return factory


def test_cipher_roundtrip_binding_and_rotation():
    from cryptography.fernet import Fernet
    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    c = CredentialCipher([k1])
    token = c.encrypt(FAKE_KEY, owner="u1", provider="anthropic")
    assert FAKE_KEY not in token and c.decrypt(token, owner="u1", provider="anthropic") == FAKE_KEY
    with pytest.raises(CredentialDecryptionError):
        c.decrypt(token, owner="u2", provider="anthropic")  # moved to another user's row
    with pytest.raises(CredentialDecryptionError):
        CredentialCipher([k2]).decrypt(token, owner="u1", provider="anthropic")  # wrong server key
    rotated = CredentialCipher([k2, k1]).rotate(token)
    assert CredentialCipher([k2]).decrypt(rotated, owner="u1", provider="anthropic") == FAKE_KEY


def test_save_key_is_encrypted_masked_and_never_returned(alice, db, fake_providers, caplog):
    built = fake_providers()
    caplog.set_level(logging.DEBUG)
    r = alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY})
    assert r.status_code == 200, r.text
    assert FAKE_KEY not in r.text
    body = r.json()
    assert body["ok"] and body["credential"]["status"] == "valid"
    assert body["credential"]["key_hint"] == "…cdef" and body["credential"]["is_active"] is True
    assert body["credential"]["model"] == "claude-opus-5-5"
    assert built[-1].api_key == FAKE_KEY  # the decrypted key reached the provider adapter only
    row = db.scalar(select(ProviderCredential).where(ProviderCredential.user_id == alice.id))
    assert FAKE_KEY not in row.ciphertext and row.ciphertext.startswith("gAAAA")
    listing = alice.get("/me/ai-providers")
    assert FAKE_KEY not in listing.text and listing.json()["active_provider"] == "anthropic"
    audits = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "ai_credential")).all()
    assert {a.action for a in audits} >= {"ai_credential.created", "ai_credential.tested"}
    assert all(FAKE_KEY not in json.dumps(a.details) for a in audits)
    assert FAKE_KEY not in caplog.text


def test_invalid_key_and_quota_are_reported_without_echo(alice, fake_providers):
    fake_providers(ok=False, code="invalid_key")
    r = alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert r.json()["credential"]["status"] == "invalid" and FAKE_KEY not in r.text
    fake_providers(ok=False, code="quota_exceeded")
    t = alice.post("/me/ai-providers/anthropic/test")
    assert t.json()["credential"]["status"] == "quota_exceeded"


def test_key_validation_rules(alice, fake_providers):
    fake_providers()
    assert alice.put("/me/ai-providers/anthropic", json={"api_key": "short"}).status_code == 422
    bad = alice.put("/me/ai-providers/anthropic", json={"api_key": "sk-ant has spaces in the middle 1234"})
    assert bad.status_code == 422 and "has spaces" not in bad.text
    assert alice.put("/me/ai-providers/gemini", json={"api_key": FAKE_KEY}).status_code == 422


def test_replace_activate_models_and_delete(alice, db, fake_providers):
    fake_providers()
    alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY})
    r = alice.put("/me/ai-providers/openai", json={"api_key": OPENAI_KEY, "model": "model-b"})
    assert r.json()["credential"]["is_active"] is True
    listing = alice.get("/me/ai-providers").json()
    assert listing["active_provider"] == "openai"
    assert sum(c["is_active"] for c in listing["credentials"]) == 1
    assert alice.get("/me/ai-providers/openai/models").json()["models"] == ["model-a", "model-b"]
    alice.patch("/me/ai-providers/anthropic", json={"is_active": True})
    assert alice.get("/me/ai-providers").json()["active_provider"] == "anthropic"
    new_key = FAKE_KEY[:-4] + "WXYZ"
    replaced = alice.put("/me/ai-providers/anthropic", json={"api_key": new_key}).json()
    assert replaced["credential"]["key_hint"] == "…WXYZ"
    assert alice.delete("/me/ai-providers/openai").status_code == 204
    assert alice.get("/me/ai-providers/openai/models").status_code == 404
    assert len(db.scalars(select(ProviderCredential)).all()) == 1


def test_credentials_are_isolated_between_users(alice, bob, fake_providers):
    fake_providers()
    alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY})
    assert bob.get("/me/ai-providers").json()["credentials"] == []
    assert bob.post("/me/ai-providers/anthropic/test").status_code == 404
    assert bob.delete("/me/ai-providers/anthropic").status_code == 404
    assert alice.get("/me/ai-providers").json()["credentials"][0]["provider"] == "anthropic"


def test_storage_disabled_without_encryption_key(alice, monkeypatch, settings, fake_providers):
    fake_providers()
    monkeypatch.setattr(settings, "credentials_encryption_keys", "")
    r = alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY})
    assert r.status_code == 503 and r.json()["error"]["code"] == "credential_storage_unavailable"
    assert alice.get("/me/ai-providers").json()["storage_available"] is False


def test_worker_uses_requesters_key_and_celery_carries_only_job_id(alice, db, fake_providers, monkeypatch):
    built = fake_providers()
    alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY})
    sent = []
    import app.worker as worker
    real = worker.process_document.apply_async

    def spy(args=None, **kw):
        sent.append({"args": args, "kwargs": kw})
        return real(args=args, **kw)

    monkeypatch.setattr(worker.process_document, "apply_async", spy)
    hid = alice.post("/households", json={"name": "BYOK"}).json()["id"]
    data = (FIXTURES / "SYNTHETIC_Securities_Backed_Line_Agreement.pdf").read_bytes()
    doc, job = upload(alice, hid, data)
    assert sent and sent[0]["args"] == [job["id"]] and FAKE_KEY not in json.dumps(sent, default=str)
    row = db.get(ProcessingJob, __import__("uuid").UUID(job["id"]))
    db.refresh(row)
    assert row.status == "succeeded" and row.credential_source == "user_byok"
    assert row.provider == "anthropic" and row.model == "claude-opus-5-5" and row.extraction_method == "llm"
    assert row.stats["llm_input_tokens"] == 1200 and FAKE_KEY not in json.dumps(row.stats)
    assert any(p.api_key == FAKE_KEY for p in built)
    api_job = alice.get(f"/documents/{doc['id']}").json()["latest_job"]
    assert api_job["credential_source"] == "user_byok" and FAKE_KEY not in json.dumps(api_job)


def test_worker_falls_back_to_rule_based_without_key(alice, db):
    hid = alice.post("/households", json={"name": "No key"}).json()["id"]
    data = (FIXTURES / "SYNTHETIC_Securities_Backed_Line_Agreement.pdf").read_bytes()
    doc, job = upload(alice, hid, data)
    row = db.get(ProcessingJob, __import__("uuid").UUID(job["id"]))
    db.refresh(row)
    assert row.credential_source == "none" and row.extraction_method == "rule_based"
    cons = alice.get(f"/households/{hid}/constraints").json()
    adv = next(c for c in cons if c["constraint_type"] == "sbl_advance_rate")
    assert adv["value_kind"] == "maximum" and adv["validation_issues"] == []


def test_unusable_stored_key_fails_job_clearly(alice, db, fake_providers, monkeypatch, settings):
    fake_providers()
    alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY})
    from cryptography.fernet import Fernet
    monkeypatch.setattr(settings, "credentials_encryption_keys", Fernet.generate_key().decode())  # server key changed
    hid = alice.post("/households", json={"name": "Rotated"}).json()["id"]
    data = (FIXTURES / "SYNTHETIC_RSU_Grant_and_Trading_Policy.pdf").read_bytes()
    doc, _ = upload(alice, hid, data)
    d = alice.get(f"/documents/{doc['id']}").json()
    assert d["status"] == "failed" and d["error_code"] == "credential_unusable" and FAKE_KEY not in json.dumps(d)


def test_own_key_audit_events_listed_without_secrets(alice, bob, fake_providers):
    fake_providers()
    alice.put("/me/ai-providers/openai", json={"api_key": FAKE_KEY, "model": "m"})
    alice.delete("/me/ai-providers/openai")
    ev = alice.get("/me/ai-providers-events").json()
    actions = [e["action"] for e in ev["items"]]
    assert "ai_credential.created" in actions and "ai_credential.deleted" in actions
    assert FAKE_KEY not in json.dumps(ev) and FAKE_KEY[-12:] not in json.dumps(ev)
    assert bob.get("/me/ai-providers-events").json()["total"] == 0


def test_workspace_id_stored_validated_and_passed_to_provider(alice, fake_providers):
    built = fake_providers()
    bad = alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY, "workspace_id": "not-a-workspace"})
    assert bad.status_code == 422
    r = alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY, "model": "claude-opus-5-5",
                                                       "workspace_id": "wrkspc_01ABCdef234"})
    assert r.status_code == 200, r.text
    assert r.json()["credential"]["workspace_id"] == "wrkspc_01ABCdef234"
    assert built[-1].workspace_id == "wrkspc_01ABCdef234"  # the connection test used it
    assert FAKE_KEY not in r.text
    cleared = alice.patch("/me/ai-providers/anthropic", json={"workspace_id": None})
    assert cleared.status_code == 200 and cleared.json()["workspace_id"] is None
    assert cleared.json()["status"] == "untested"
    other = alice.put("/me/ai-providers/openai", json={"api_key": OPENAI_KEY, "model": "m",
                                                        "workspace_id": "wrkspc_01ABCdef234"})
    assert other.status_code == 422


def test_failed_ai_job_is_distinguishable_and_never_stores_the_key(alice, db, fake_providers, monkeypatch):
    from app.llm.base import ProviderError

    def build(provider, api_key, model, settings, workspace_id=None):
        p = FakeProvider(provider, api_key, model)
        def boom(system, user, schema):
            raise ProviderError(f"provider echoed {api_key} in its error", "request_rejected")
        p.extract_json = boom
        return p
    fake_providers()  # passing connection test when the key is saved
    monkeypatch.setattr("app.services.processing.build_provider", build)  # the worker's call then fails
    alice.put("/me/ai-providers/anthropic", json={"api_key": FAKE_KEY, "model": "claude-opus-5-5"})
    hid = alice.post("/households", json={"name": "H"}).json()["id"]
    doc, _ = upload(alice, hid, (FIXTURES / "SYNTHETIC_Securities_Backed_Line_Agreement.pdf").read_bytes(),
                    "sbl.pdf", "sbl_agreement")
    job = alice.get(f"/documents/{doc['id']}/jobs").json()[0]
    assert job["status"] == "failed" and job["error_code"] == "request_rejected"
    assert (job["extraction_method"], job["provider"], job["credential_source"]) == ("llm", "anthropic", "user_byok")
    assert job["model"] == "claude-opus-5-5"
    assert FAKE_KEY not in json.dumps(job) and "[redacted]" in job["error_message"]
