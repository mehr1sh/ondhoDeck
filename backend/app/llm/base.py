"""Provider-independent LLM interface for contract extraction.

Adapters (anthropic_adapter.py, openai_adapter.py) keep provider-specific requests and response
parsing out of the rest of the application. An adapter only *reads text and returns JSON*: it never
computes balances, never touches simulation code, and never executes instructions from documents.

Every error message raised from an adapter is written by us (never copied from a provider response),
so credentials and request payloads cannot leak through exceptions or logs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

PROVIDERS = ("anthropic", "openai")
PROVIDER_LABELS = {"anthropic": "Anthropic", "openai": "OpenAI"}
# Defaults are only suggestions shown in the UI; the user picks from the provider's live model list.
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": None}


class ProviderError(RuntimeError):
    """Permanent failure. `code` is a stable machine-readable reason shown to users."""

    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


class TransientProviderError(ProviderError):
    """Retryable failure (rate limit, timeout, 5xx, network)."""

    def __init__(self, message: str, code: str = "provider_unavailable"):
        super().__init__(message, code)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ConnectionResult:
    ok: bool
    code: str            # "ok", "invalid_key", "quota_exceeded", "rate_limited", "model_not_found", ...
    message: str
    model_checked: str | None = None


class LLMProvider(Protocol):
    name: str
    model: str
    last_usage: Usage
    last_latency_ms: int

    def extract_json(self, system: str, user: str, schema: dict) -> dict:
        """One schema-constrained request. Raises ProviderError / TransientProviderError, or the engine's
        LLMError for malformed JSON (so the extractor's single bounded retry applies)."""
        ...

    def test_connection(self) -> ConnectionResult: ...

    def list_models(self) -> list[str]: ...


@dataclass
class Timer:
    start: float = field(default_factory=time.perf_counter)

    def ms(self) -> int:
        return int((time.perf_counter() - self.start) * 1000)


def connection_failure(exc: ProviderError) -> ConnectionResult:
    return ConnectionResult(ok=False, code=exc.code, message=str(exc))


def schema_name(schema: dict[str, Any]) -> str:
    return str(schema.get("title") or "contract_terms").replace(" ", "_")[:64]
