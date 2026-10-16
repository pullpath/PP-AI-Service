"""
Language handling for the scene description service.

The frontend sends the user's browser language (a BCP-47 tag such as "zh-CN"). It ends up inside an LLM
prompt, so it is strictly validated and mapped to a language name instead of being pasted in as is.
"""
import re
from typing import Any

DEFAULT_LANGUAGE = "en"

# Primary subtag + up to 3 further subtags, e.g. "en", "zh-CN", "zh-Hant-TW". No spaces or punctuation.
_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")

_NAMES = {
    "en": "English", "zh": "Simplified Chinese", "ja": "Japanese", "ko": "Korean",
    "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "ru": "Russian", "ar": "Arabic", "hi": "Hindi", "tr": "Turkish", "nl": "Dutch",
    "pl": "Polish", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian", "uk": "Ukrainian",
}


def normalize_language(raw: Any) -> str:
    """Return a well-formed BCP-47 tag, or DEFAULT_LANGUAGE for anything missing or malformed."""
    if isinstance(raw, str):
        tag = raw.strip().replace("_", "-")
        if len(tag) <= 35 and _TAG_RE.match(tag):
            return tag
    return DEFAULT_LANGUAGE


def language_name(tag: str) -> str:
    """Human-readable language name for the prompt, e.g. "zh-TW" -> "Traditional Chinese"."""
    parts = tag.lower().split("-")
    primary = parts[0]
    if primary == "zh":
        traditional = "hant" in parts or any(p in ("tw", "hk", "mo") for p in parts[1:])
        return "Traditional Chinese" if traditional else "Simplified Chinese"
    # Unknown but well-formed tags are described by tag; the regex guarantees they contain no quotes
    return _NAMES.get(primary) or f'the language with BCP-47 tag "{tag}"'
