"""OpenAI Responses API adapter (strict JSON-schema structured output via text.format)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import ConnectionResult, ProviderError, Timer, TransientProviderError, Usage, connection_failure, schema_name


def _error_code(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict):
            return str(inner.get("code") or inner.get("type") or "")
    return str(getattr(exc, "code", "") or "")


def _map_error(exc: Exception) -> ProviderError:
    import openai

    code = _error_code(exc)
    if isinstance(exc, openai.AuthenticationError):
        return ProviderError("The OpenAI API key was rejected.", "invalid_key")
    if isinstance(exc, openai.PermissionDeniedError):
        return ProviderError("This OpenAI key is not permitted to use the selected model.", "permission_denied")
    if isinstance(exc, openai.NotFoundError):
        return ProviderError("The selected OpenAI model was not found for this key.", "model_not_found")
    if isinstance(exc, openai.RateLimitError):
        if code == "insufficient_quota":
            return ProviderError("The OpenAI account has exceeded its quota or has no credit.", "quota_exceeded")
        return TransientProviderError("OpenAI rate limit reached. Retry shortly.", "rate_limited")
    if isinstance(exc, openai.APITimeoutError):
        return TransientProviderError("The OpenAI API timed out.", "timeout")
    if isinstance(exc, openai.APIConnectionError):
        return TransientProviderError("Could not reach the OpenAI API.", "network_error")
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return TransientProviderError(f"OpenAI service error ({exc.status_code}).", "provider_unavailable")
        return ProviderError(f"OpenAI rejected the request ({exc.status_code}).", "request_rejected")
    return ProviderError("Unexpected error calling OpenAI.", "provider_error")


@dataclass
class OpenAIProvider:
    api_key: str = field(repr=False)
    model: str
    timeout_s: int = 180
    name: str = "openai"
    last_usage: Usage = field(default_factory=Usage)
    last_latency_ms: int = 0

    def _client(self, timeout: float | None = None):
        import openai

        return openai.OpenAI(api_key=self.api_key, timeout=timeout or self.timeout_s, max_retries=1)

    def extract_json(self, system: str, user: str, schema: dict) -> dict:
        timer = Timer()
        try:
            response = self._client().responses.create(
                model=self.model, instructions=system, input=user, store=False, max_output_tokens=16000,
                text={"format": {"type": "json_schema", "name": schema_name(schema), "schema": schema, "strict": True}},
            )
        except Exception as exc:
            raise _map_error(exc) from None
        self.last_latency_ms = timer.ms()
        usage = getattr(response, "usage", None)
        self.last_usage = Usage(getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
        if response.status == "incomplete":
            raise ProviderError("The model output was incomplete or truncated.", "truncated")
        if response.status == "failed":
            raise TransientProviderError("OpenAI reported a failed response.", "provider_unavailable")
        for item in response.output or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ProviderError("The model declined to process this document.", "refusal")
        text = response.output_text
        if not text:
            raise ProviderError("The model returned no text.", "empty_response")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            from ..engine.llm_service import LLMError
            raise LLMError("Model returned malformed JSON") from None

    def test_connection(self) -> ConnectionResult:
        """Retrieve the selected model (or list models): authenticates the key without generating tokens."""
        try:
            client = self._client(timeout=15)
            if self.model:
                client.models.retrieve(self.model)
            else:
                client.models.list()
        except Exception as exc:
            return connection_failure(_map_error(exc))
        return ConnectionResult(ok=True, code="ok", message="Connected to OpenAI.", model_checked=self.model or None)

    def list_models(self) -> list[str]:
        try:
            models = self._client(timeout=15).models.list()
        except Exception as exc:
            raise _map_error(exc) from None
        return sorted({m.id for m in models})
