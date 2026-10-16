"""API test fixtures.

Uses a real PostgreSQL database (TEST_DATABASE_URL, default: local slipslopes_test), migrated with
Alembic, so constraints, partial indexes and RLS policies are exercised. External services are
replaced: Celery runs eagerly in-process, storage is a temp directory, auth uses locally signed
test tokens, and no LLM provider is configured unless a test injects a mock. These tests therefore
do NOT prove a live Supabase/Redis/LLM integration.
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid

import pytest

_STORAGE = tempfile.mkdtemp(prefix="slipslopes-test-storage-")
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL",
                                   "postgresql+psycopg://slipslopes:slipslopes@localhost:54329/slipslopes_test"),
    "SUPABASE_URL": "",
    "SUPABASE_JWT_SECRET": "test-secret-for-hs256-tokens-only-0123456789",
    "STORAGE_BACKEND": "local",
    "LOCAL_STORAGE_DIR": _STORAGE,
    "CELERY_TASK_ALWAYS_EAGER": "true",
    "LLM_PROVIDER": "none",
    "OCR_ENABLED": "true",
    "CORS_ORIGINS": "http://localhost:3000",
    "RATE_LIMIT_EXTRACTION_PER_HOUR": "1000",
    "RATE_LIMIT_COMPUTE_PER_MINUTE": "1000",
    "REDIS_URL": "redis://localhost:1/0",  # unreachable on purpose: rate limiter falls back to memory
    # Throwaway Fernet key generated per test session (never a real secret).
    "CREDENTIALS_ENCRYPTION_KEYS": __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
    "RATE_LIMIT_PROVIDER_TESTS_PER_10MIN": "1000",
})

import jwt  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.ratelimit import reset_local  # noqa: E402

SECRET = os.environ["SUPABASE_JWT_SECRET"]
BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_token(sub: uuid.UUID | str, email: str = "user@example.com", exp_in: int = 3600, aud: str = "authenticated",
               secret: str = SECRET, role: str = "authenticated", **extra) -> str:
    now = int(time.time())
    claims = {"sub": str(sub), "email": email, "aud": aud, "role": role, "iat": now, "exp": now + exp_in, **extra}
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    # Test database only: clear library rows left by a previous session so the migration's downgrade guard
    # (which refuses to destroy library data) lets the schema be rebuilt from scratch.
    with get_engine().begin() as conn:
        if conn.execute(text("SELECT to_regclass('public.funds')")).scalar() is not None:
            conn.execute(text("TRUNCATE funds, firm_members, firms CASCADE"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_db():
    tables = ["chat_messages", "chat_conversations", "provider_credentials", "audit_events", "exports", "prevention_recommendations", "prevention_plans", "stress_results",
              "simulation_months", "simulation_runs", "scenarios", "constraint_revisions", "extracted_constraints",
              "processing_jobs", "document_pages", "documents", "scheduled_events", "cash_flows", "liabilities",
              "blind_spot_reports", "assets", "household_members", "households", "funds", "firm_members", "firms", "profiles"]
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(tables) + " CASCADE"))
    reset_local()
    yield


@pytest.fixture
def db():
    s = get_sessionmaker()()
    yield s
    s.close()


@pytest.fixture
def client():
    return TestClient(app)


class User:
    def __init__(self, client: TestClient, email: str):
        self.id = uuid.uuid4()
        self.email = email
        self.client = client
        self.headers = {"Authorization": f"Bearer {make_token(self.id, email)}"}

    def get(self, url, **kw):
        return self.client.get(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, url, **kw):
        return self.client.post(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def put(self, url, **kw):
        return self.client.put(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, url, **kw):
        return self.client.patch(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def delete(self, url, **kw):
        return self.client.request("DELETE", f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})},
                                   **kw)


@pytest.fixture
def alice(client):
    return User(client, "alice@example.com")


@pytest.fixture
def bob(client):
    return User(client, "bob@example.com")


@pytest.fixture
def settings():
    return get_settings()


def make_pdf(text_lines: list[str] | None = None, pages: int = 1) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), "\n\n".join(text_lines or [f"Page {i + 1} text."]),
                            fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def upload(user: User, household_id: str, data: bytes, filename: str = "agreement.pdf", category: str = "sbl_agreement",
           complete: bool = True):
    import hashlib
    init = user.post(f"/households/{household_id}/documents",
                     json={"filename": filename, "category": category, "size_bytes": len(data),
                           "sha256": hashlib.sha256(data).hexdigest()})
    assert init.status_code == 201, init.text
    body = init.json()
    if body["duplicate"]:
        return body["document"], None
    doc_id = body["document"]["id"]
    put = user.put(f"/documents/{doc_id}/content", content=data, headers={"Content-Type": "application/pdf"})
    assert put.status_code == 200, put.text
    job = None
    if complete:
        r = user.post(f"/documents/{doc_id}/complete")
        assert r.status_code == 202, r.text
        job = r.json()
    return user.get(f"/documents/{doc_id}").json(), job
