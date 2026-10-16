"""
Vision provider selection for the scene description service.

AI_PROVIDER picks the backend: "deepseek" (default) or "openai". Both speak the OpenAI
chat-completions format, so only base_url, api_key and model differ.
"""
import os
from typing import Optional, Tuple

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def get_provider_name() -> str:
    return (os.getenv("AI_PROVIDER") or "deepseek").strip().lower()


def _strip_slash(base_url: Optional[str]) -> Optional[str]:
    """Strip trailing slashes to avoid //chat/completions."""
    return base_url.rstrip("/") if base_url else base_url


def get_vision_provider() -> Tuple[Optional[str], Optional[str], str]:
    """Return (base_url, api_key, model) for the provider selected by AI_PROVIDER."""
    provider = get_provider_name()
    if provider == "deepseek":
        return (
            _strip_slash(os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL),
            os.getenv("DEEPSEEK_API_KEY"),
            os.getenv("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL,
        )
    if provider != "openai":
        raise ValueError(f"Unsupported AI_PROVIDER '{provider}', expected 'openai' or 'deepseek'")
    return (
        # None means the official https://api.openai.com/v1. The legacy OPENAI_API_BASE proxy setting used by
        # other routes is deliberately NOT read here.
        _strip_slash(os.getenv("OPENAI_BASE_URL")),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
    )
