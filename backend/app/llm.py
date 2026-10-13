"""LLM provider abstraction for structured extraction.

The provider only *reads text*: it proposes structured terms from retrieved excerpts. Every
financial calculation is done by the deterministic engine. Credentials and model ids come from
settings; nothing here is hardcoded per environment.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from .config import Settings

log = logging.getLogger("slipslopes.llm")


class ProviderError(RuntimeError):
    """Permanent failure (bad credentials, refusal, invalid output)."""


class TransientProviderError(ProviderError):
    """Retryable failure (rate limit, timeout, 5xx, network)."""


class LLMProvider(Protocol):
    name: str
    model: str

    def extract_json(self, system: str, user: str, schema: dict) -> dict: ...


@dataclass
class AnthropicProvider:
    api_key: str
    model: str
    effort: str
    timeout_s: int
    name: str = "anthropic"

    def extract_json(self, system: str, user: str, schema: dict) -> dict:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_s, max_retries=1)
        try:
            response = client.messages.create(  # type: ignore[call-overload]
                model=self.model, max_tokens=16000, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                extra_body={"fallbacks": "default"},
            )
        except anthropic.RateLimitError as exc:
            raise TransientProviderError("provider rate limit") from exc
        except anthropic.APITimeoutError as exc:
            raise TransientProviderError("provider timeout") from exc
        except anthropic.APIConnectionError as exc:
            raise TransientProviderError("provider unreachable") from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderError("provider authentication failed") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code == 529:
                raise TransientProviderError(f"provider error {exc.status_code}") from exc
            raise ProviderError(f"provider rejected request ({exc.status_code})") from exc
        if response.stop_reason == "refusal":
            raise ProviderError("provider declined the request")
        if response.stop_reason == "max_tokens":
            raise ProviderError("provider output truncated")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ProviderError("no text in provider response")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # Surfaced to the extractor's bounded retry as malformed output.
            from .engine.llm_service import LLMError
            raise LLMError(f"Model returned malformed JSON: {exc}") from exc


def get_provider(settings: Settings) -> LLMProvider | None:
    """The configured provider, or None (rule-based extraction is used instead)."""
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.llm_model,
                                 effort=settings.llm_effort, timeout_s=settings.llm_timeout_s)
    return None
