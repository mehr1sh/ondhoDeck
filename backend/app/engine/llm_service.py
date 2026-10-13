"""Thin wrapper around the Anthropic Messages API for schema-constrained extraction.

Configuration comes from environment variables (see .env.example). The app
never requires this module to succeed: callers catch `LLMError` and fall back
to Demo Mode.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    api_key: str | None
    model: str
    effort: str
    fallbacks: bool

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def get_config() -> LLMConfig:
    return LLMConfig(
        api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        model=os.getenv("SLIPSLOPES_LLM_MODEL", "claude-opus-5-5"),
        effort=os.getenv("SLIPSLOPES_LLM_EFFORT", "medium"),
        fallbacks=os.getenv("SLIPSLOPES_LLM_FALLBACKS", "1") != "0",
    )


def call_structured(system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
    """Return the JSON object produced under `schema`. Raises LLMError on any failure."""
    cfg = get_config()
    if not cfg.configured:
        raise LLMError("ANTHROPIC_API_KEY is not set. Live extraction is unavailable; use Demo Mode.")
    try:
        import anthropic
    except ImportError as exc:
        raise LLMError("The 'anthropic' package is not installed.") from exc

    client = anthropic.Anthropic(api_key=cfg.api_key)
    kwargs: dict = dict(
        model=cfg.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": cfg.effort, "format": {"type": "json_schema", "schema": schema}},
    )
    if cfg.fallbacks:
        # Server-side refusal fallback; the API picks the fallback model by refusal category.
        kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
        kwargs["extra_body"] = {"fallbacks": "default"}
    try:
        response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise LLMError("Authentication failed - check ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Rate limited by the API - try again shortly or use Demo Mode.") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Could not reach the Anthropic API (network error).") from exc

    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request.")
    if response.stop_reason == "max_tokens":
        raise LLMError("Model output was truncated (max_tokens).")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise LLMError("No text content in model response.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model returned malformed JSON: {exc}") from exc
