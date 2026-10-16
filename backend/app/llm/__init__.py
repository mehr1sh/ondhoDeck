"""LLM provider package: common interface, adapters and the normalised extraction service."""
from __future__ import annotations

from ..config import Settings
from .anthropic_adapter import AnthropicProvider
from .base import (
    DEFAULT_MODELS,
    PROVIDER_LABELS,
    PROVIDERS,
    ConnectionResult,
    LLMProvider,
    ProviderError,
    TransientProviderError,
    Usage,
)
from .openai_adapter import OpenAIProvider

__all__ = ["AnthropicProvider", "OpenAIProvider", "LLMProvider", "ProviderError", "TransientProviderError",
           "ConnectionResult", "Usage", "PROVIDERS", "PROVIDER_LABELS", "DEFAULT_MODELS", "build_provider",
           "get_provider"]


def build_provider(provider: str, api_key: str, model: str | None, settings: Settings,
                   workspace_id: str | None = None) -> LLMProvider:
    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model or DEFAULT_MODELS["anthropic"] or "",
                                 effort=settings.llm_effort, timeout_s=settings.llm_timeout_s,
                                 workspace_id=workspace_id or None)
    if provider == "openai":
        return OpenAIProvider(api_key=api_key, model=model or "", timeout_s=settings.llm_timeout_s)
    raise ValueError(f"unsupported provider: {provider}")


def get_provider(settings: Settings) -> LLMProvider | None:
    """The deployment-level (server) provider from environment variables, or None."""
    if not settings.llm_configured:
        return None
    if settings.llm_provider == "anthropic":
        return build_provider("anthropic", settings.anthropic_api_key, settings.llm_model, settings,
                              workspace_id=settings.anthropic_workspace_id or None)
    return build_provider("openai", settings.openai_api_key, settings.openai_model, settings)
