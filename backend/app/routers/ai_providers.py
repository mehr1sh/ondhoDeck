"""BYOK: per-user LLM provider credentials (stored encrypted; never returned)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import AuditOut, Page
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..config import Settings, get_settings
from ..crypto import CredentialDecryptionError, CredentialStorageUnavailable, get_cipher, key_hint
from ..db import get_db
from ..errors import ApiError
from ..llm import DEFAULT_MODELS, PROVIDER_LABELS, PROVIDERS, ProviderError, build_provider
from ..models import AuditEvent, ProviderCredential
from ..ratelimit import check_rate
from .common import Pagination, paginate

router = APIRouter(tags=["ai providers"])
Provider = Literal["anthropic", "openai"]


WORKSPACE_ID = r"^wrkspc_[A-Za-z0-9]{6,58}$"


class CredentialOut(BaseModel):
    provider: Provider
    key_hint: str
    model: Optional[str]
    workspace_id: Optional[str] = None
    is_active: bool
    status: str
    last_tested_at: Optional[datetime]
    last_error_code: Optional[str]
    last_error: Optional[str]
    updated_at: datetime


class ProviderInfo(BaseModel):
    provider: Provider
    label: str
    default_model: Optional[str]


class ServerFallback(BaseModel):
    configured: bool
    provider: Optional[str]
    model: Optional[str]


class AIProvidersOut(BaseModel):
    storage_available: bool
    storage_message: Optional[str]
    providers: list[ProviderInfo]
    credentials: list[CredentialOut]
    active_provider: Optional[Provider]
    server_fallback: ServerFallback
    extraction_order: str = ("Your active key if it is valid; otherwise the server provider if configured; "
                             "otherwise deterministic rule-based extraction.")


class CredentialIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=400, repr=False)
    model: Optional[str] = Field(None, max_length=120)
    workspace_id: Optional[str] = Field(None, pattern=WORKSPACE_ID,
                                        description="Anthropic workspace ID, for keys not scoped to a workspace")
    activate: bool = True

    @field_validator("api_key")
    @classmethod
    def _shape(cls, v: str) -> str:
        v = v.strip()
        if any(ch.isspace() for ch in v) or not v.isprintable():
            raise ValueError("API keys cannot contain spaces or control characters")
        return v


class CredentialUpdate(BaseModel):
    model: Optional[str] = Field(None, max_length=120)
    workspace_id: Optional[str] = Field(None, pattern=WORKSPACE_ID, description="Set null to clear")
    is_active: Optional[bool] = None


class TestOut(BaseModel):
    ok: bool
    code: str
    message: str
    credential: CredentialOut


class ModelsOut(BaseModel):
    provider: Provider
    models: list[str]


def _out(c: ProviderCredential) -> CredentialOut:
    return CredentialOut(provider=c.provider, key_hint=c.key_hint, model=c.model, workspace_id=c.workspace_id,
                         is_active=c.is_active,
                         status=c.status,
                         last_tested_at=c.last_tested_at, last_error_code=c.last_error_code, last_error=c.last_error,
                         updated_at=c.updated_at)


def _cipher():
    try:
        return get_cipher()
    except CredentialStorageUnavailable as exc:
        raise ApiError(503, "credential_storage_unavailable",
                       "Storing API keys is disabled because no encryption key is configured on the server "
                       "(CREDENTIALS_ENCRYPTION_KEYS). Keys are never stored unencrypted.") from exc


def _get(db: Session, user: CurrentUser, provider: str) -> ProviderCredential:
    if provider not in PROVIDERS:
        raise ApiError(404, "not_found", "Unknown provider.")
    c = db.scalar(select(ProviderCredential).where(ProviderCredential.user_id == user.id,
                                                   ProviderCredential.provider == provider))
    if c is None:
        raise ApiError(404, "not_found", "No key is stored for this provider.")
    return c


def _decrypted_provider(c: ProviderCredential, user: CurrentUser, settings: Settings):
    try:
        secret = _cipher().decrypt(c.ciphertext, owner=str(user.id), provider=c.provider)
    except CredentialDecryptionError as exc:
        raise ApiError(409, "credential_unreadable",
                       "The stored key can no longer be decrypted (the server key may have changed). "
                       "Replace the key.") from exc
    return build_provider(c.provider, secret, c.model or DEFAULT_MODELS[c.provider], settings,
                          workspace_id=c.workspace_id)


def _run_test(db: Session, c: ProviderCredential, user: CurrentUser, settings: Settings) -> TestOut:
    if c.provider == "openai" and not c.model:
        result_ok, code, message = False, "model_required", "Choose an OpenAI model before testing."
    else:
        result = _decrypted_provider(c, user, settings).test_connection()
        result_ok, code, message = result.ok, result.code, result.message
    c.status = "valid" if result_ok else ("quota_exceeded" if code == "quota_exceeded" else
                                          "invalid" if code in ("invalid_key", "permission_denied") else "error")
    c.last_tested_at = datetime.now(UTC)
    c.last_error_code, c.last_error = (None, None) if result_ok else (code, message[:300])
    audit(db, actor_id=user.id, action="ai_credential.tested", entity_type="ai_credential", entity_id=c.id,
          details={"provider": c.provider, "result": code})
    db.commit()
    return TestOut(ok=result_ok, code=code, message=message, credential=_out(c))


@router.get("/me/ai-providers", response_model=AIProvidersOut)
def list_ai_providers(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
                      settings: Settings = Depends(get_settings)):
    creds = db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user.id)
                       .order_by(ProviderCredential.provider)).all()
    try:
        get_cipher()
        available, msg = True, None
    except CredentialStorageUnavailable:
        available, msg = False, "Key storage is disabled: the server has no CREDENTIALS_ENCRYPTION_KEYS configured."
    active = next((c.provider for c in creds if c.is_active), None)
    server_model = settings.llm_model if settings.llm_provider == "anthropic" else settings.openai_model or None
    return AIProvidersOut(
        storage_available=available, storage_message=msg,
        providers=[ProviderInfo(provider=p, label=PROVIDER_LABELS[p], default_model=DEFAULT_MODELS[p])
                   for p in PROVIDERS],
        credentials=[_out(c) for c in creds], active_provider=active,
        server_fallback=ServerFallback(configured=settings.llm_configured,
                                       provider=settings.llm_provider if settings.llm_configured else None,
                                       model=server_model if settings.llm_configured else None))


@router.put("/me/ai-providers/{provider}", response_model=TestOut)
def save_credential(provider: Provider, body: CredentialIn, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Create or replace the key for a provider, then test it with a request that generates no tokens."""
    check_rate(str(user.id), "ai_provider_test", settings.rate_limit_provider_tests_per_10min, 600)
    cipher = _cipher()
    c = db.scalar(select(ProviderCredential).where(ProviderCredential.user_id == user.id,
                                                   ProviderCredential.provider == provider))
    replaced = c is not None
    if c is None:
        c = ProviderCredential(user_id=user.id, provider=provider)
        db.add(c)
    c.ciphertext = cipher.encrypt(body.api_key, owner=str(user.id), provider=provider)
    c.key_hint = key_hint(body.api_key)
    c.model = body.model or c.model or DEFAULT_MODELS[provider]
    if "workspace_id" in body.model_fields_set:
        if provider != "anthropic" and body.workspace_id:
            raise ApiError(422, "validation_error", "A workspace ID applies only to Anthropic keys.")
        c.workspace_id = body.workspace_id
    c.status, c.last_tested_at, c.last_error_code, c.last_error = "untested", None, None, None
    if body.activate:
        for other in db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user.id,
                                                                 ProviderCredential.provider != provider)):
            other.is_active = False
        db.flush()
        c.is_active = True
    db.flush()
    audit(db, actor_id=user.id, action="ai_credential.replaced" if replaced else "ai_credential.created",
          entity_type="ai_credential", entity_id=c.id, details={"provider": provider, "model": c.model})
    db.commit()
    return _run_test(db, c, user, settings)


@router.post("/me/ai-providers/{provider}/test", response_model=TestOut)
def test_credential(provider: Provider, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)):
    check_rate(str(user.id), "ai_provider_test", settings.rate_limit_provider_tests_per_10min, 600)
    return _run_test(db, _get(db, user, provider), user, settings)


@router.get("/me/ai-providers/{provider}/models", response_model=ModelsOut)
def list_provider_models(provider: Provider, user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Models available to the stored key, fetched live from the provider (no hardcoded catalogue)."""
    check_rate(str(user.id), "ai_provider_test", settings.rate_limit_provider_tests_per_10min, 600)
    c = _get(db, user, provider)
    try:
        models = _decrypted_provider(c, user, settings).list_models()
    except ProviderError as exc:
        raise ApiError(502, exc.code, str(exc)) from None
    return ModelsOut(provider=provider, models=models)


@router.patch("/me/ai-providers/{provider}", response_model=CredentialOut)
def update_credential(provider: Provider, body: CredentialUpdate, user: CurrentUser = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    c = _get(db, user, provider)
    changes = body.model_dump(exclude_unset=True)
    if "model" in changes and changes["model"] != c.model:
        c.model = changes["model"]
        c.status, c.last_error_code, c.last_error = "untested", None, None
    if "workspace_id" in changes and changes["workspace_id"] != c.workspace_id:
        if c.provider != "anthropic" and changes["workspace_id"]:
            raise ApiError(422, "validation_error", "A workspace ID applies only to Anthropic keys.")
        c.workspace_id = changes["workspace_id"]
        c.status, c.last_error_code, c.last_error = "untested", None, None
    if changes.get("is_active") is True:
        for other in db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user.id,
                                                                 ProviderCredential.id != c.id)):
            other.is_active = False
        db.flush()
        c.is_active = True
    elif changes.get("is_active") is False:
        c.is_active = False
    audit(db, actor_id=user.id, action="ai_credential.updated", entity_type="ai_credential", entity_id=c.id,
          details={"provider": provider, "fields": sorted(changes)})
    db.commit()
    return _out(c)


@router.delete("/me/ai-providers/{provider}", status_code=204)
def delete_credential(provider: Provider, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _get(db, user, provider)
    audit(db, actor_id=user.id, action="ai_credential.deleted", entity_type="ai_credential", entity_id=c.id,
          details={"provider": provider})
    db.delete(c)
    db.commit()


@router.get("/me/ai-providers-events", response_model=Page[AuditOut])
def ai_provider_events(p: Pagination = Depends(), user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """The caller's own key events (create, replace, test, update, delete). Details never contain keys."""
    stmt = (select(AuditEvent).where(AuditEvent.actor_id == user.id, AuditEvent.entity_type == "ai_credential")
            .order_by(AuditEvent.created_at.desc()))
    rows, total = paginate(db, stmt, p)
    return Page(items=[AuditOut.model_validate(r[0]) for r in rows], total=total, limit=p.limit, offset=p.offset)
