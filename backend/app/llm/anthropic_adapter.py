"""Anthropic Messages API adapter (schema-constrained JSON via output_config.format)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import ConnectionResult, ProviderError, Timer, TransientProviderError, Usage, connection_failure

WORKSPACE_HEADER = "anthropic-workspace-id"


def _provider_message(exc: Exception, secret: str) -> str:
    """Anthropic's own error message (never contains the key; redacted anyway), shortened for display."""
    body = getattr(exc, "body", None)
    msg = ""
    if isinstance(body, dict):
        err = body.get("error")
        msg = (err or {}).get("message", "") if isinstance(err, dict) else ""
    msg = (msg or "").replace(secret, "[redacted]") if secret else (msg or "")
    return msg[:240]


def _map_error(exc: Exception, secret: str = "") -> ProviderError:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderError("The Anthropic API key was rejected.", "invalid_key")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ProviderError("This Anthropic key is not permitted to use the selected model.", "permission_denied")
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderError("The selected Anthropic model was not found for this key.", "model_not_found")
    if isinstance(exc, anthropic.RateLimitError):
        return TransientProviderError("Anthropic rate limit reached. Retry shortly.", "rate_limited")
    if isinstance(exc, anthropic.APITimeoutError):
        return TransientProviderError("The Anthropic API timed out.", "timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return TransientProviderError("Could not reach the Anthropic API.", "network_error")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 402 or "credit" in str(getattr(exc, "message", "")).lower():
            return ProviderError("The Anthropic account has insufficient credit.", "quota_exceeded")
        if exc.status_code >= 500 or exc.status_code == 529:
            return TransientProviderError(f"Anthropic service error ({exc.status_code}).", "provider_unavailable")
        detail = _provider_message(exc, secret)
        if WORKSPACE_HEADER in detail:
            return ProviderError("This Anthropic API key is not scoped to a workspace. Enter the workspace ID "
                                 "(wrkspc_...) from the Claude Console together with the key.", "workspace_required")
        return ProviderError(f"Anthropic rejected the request ({exc.status_code})"
                             + (f": {detail}" if detail else "."), "request_rejected")
    return ProviderError("Unexpected error calling Anthropic.", "provider_error")


@dataclass
class AnthropicProvider:
    api_key: str = field(repr=False)
    model: str
    effort: str = "medium"
    timeout_s: int = 180
    fallbacks: bool = True
    workspace_id: str | None = None
    name: str = "anthropic"
    last_usage: Usage = field(default_factory=Usage)
    last_latency_ms: int = 0

    def _client(self, timeout: float | None = None):
        import anthropic

        headers = {WORKSPACE_HEADER: self.workspace_id} if self.workspace_id else None
        return anthropic.Anthropic(api_key=self.api_key, timeout=timeout or self.timeout_s, max_retries=1,
                                   default_headers=headers)

    def extract_json(self, system: str, user: str, schema: dict) -> dict:
        # No `thinking` field: Claude Opus 5.5 always runs adaptive thinking, and an explicit
        # {"type": "disabled"} or a token budget is rejected with a 400. Depth is set via output_config.effort.
        kwargs: dict = dict(model=self.model, max_tokens=16000, system=system,
                            messages=[{"role": "user", "content": user}],
                            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}})
        if self.fallbacks:
            kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
            kwargs["extra_body"] = {"fallbacks": "default"}
        timer = Timer()
        try:
            response = self._client().messages.create(**kwargs)
        except Exception as exc:  # mapped to our own messages; the original is never shown
            raise _map_error(exc, self.api_key) from None
        self.last_latency_ms = timer.ms()
        usage = getattr(response, "usage", None)
        self.last_usage = Usage(getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
        if response.stop_reason == "refusal":
            raise ProviderError("The model declined to process this document.", "refusal")
        if response.stop_reason == "max_tokens":
            raise ProviderError("The model output was truncated.", "truncated")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ProviderError("The model returned no text.", "empty_response")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            from ..engine.llm_service import LLMError
            raise LLMError("Model returned malformed JSON") from None

    def test_connection(self) -> ConnectionResult:
        """Retrieve the selected model's metadata: authenticates the key without generating tokens."""
        try:
            self._client(timeout=15).models.retrieve(self.model)
        except Exception as exc:
            return connection_failure(_map_error(exc, self.api_key))
        return ConnectionResult(ok=True, code="ok", message="Connected to Anthropic.", model_checked=self.model)

    def list_models(self) -> list[str]:
        try:
            page = self._client(timeout=15).models.list(limit=100)
        except Exception as exc:
            raise _map_error(exc, self.api_key) from None
        return sorted({m.id for m in page.data})
