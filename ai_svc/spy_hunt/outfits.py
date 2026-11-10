"""Bot outfit option tables and validation. Must not import bots/game."""
from __future__ import annotations

from typing import Any, Dict

from .store import StoreError

VOICES: Dict[str, str] = {
    "cheerful": "Cheerful and upbeat; a little playful.",
    "dry": "Dry and understated; deadpan, minimal enthusiasm.",
    "chatty": "Chatty and a bit rambly, friendly tangents.",
    "terse": "Terse; short, clipped sentences, no fluff.",
    "pirate": "Speak like a cheerful pirate, with nautical slang and an occasional 'arr'.",
    "grandma": "Speak like a warm, doting grandma: gentle, affectionate, fond of calling people 'dear'.",
    "sleepy_cat": "Speak like a sleepy cat: drowsy, lazy, easily distracted by naps and sunbeams.",
    "robot": "Speak like a stiff, literal robot: formal, mechanical, precise phrasing.",
}

STYLES: Dict[str, str] = {
    "concrete": "Describe the word with concrete physical details such as shape, size, material or where it is found, applied in the language of the statement.",
    "vague": "Describe the word with abstract, indirect hints and avoid concrete physical details, applied in the language of the statement.",
    "metaphor": "Describe the word through a metaphor or comparison to something else, applied in the language of the statement.",
    "brief": "Keep the statement very short, about 8 words (a guide, not a hard limit), applied in the language of the statement.",
    "memory": "Describe the word through a tiny personal memory involving it, applied in the language of the statement.",
    "contrast": "Describe the word by contrast, saying what it is unlike or the opposite of, applied in the language of the statement.",
}

QUIRKS: Dict[str, str] = {
    "question": "End every statement with a question, applied in the language of the statement.",
    "agree": "Begin by agreeing with the previous speaker, applied in the language of the statement.",
    "number": "Include a number in every statement, applied in the language of the statement.",
    "emoji": "End every statement with one emoji, whatever the language of the statement.",
    "honestly": "Start every statement with the word 'Honestly,', translated into the language of the statement.",
    "color": "Mention a colour in every statement, applied in the language of the statement.",
}

EMOJIS = (
    "🦊", "🐱", "🐶", "🐼", "🐸", "🦉", "🐙", "🦄",
    "🐧", "🐯", "🐰", "🐻", "🦁", "🐨", "🐵", "🐢",
    "🦋", "🐳", "🦖", "🐝", "🍄", "🌵", "🚀", "👾",
)
COLORS = ("#ff6b6b", "#ffa94d", "#4cd08a", "#38c9d6", "#5b8cff", "#b07cff")

_AVATAR_SLOTS = {"emoji": EMOJIS, "color": COLORS}
_OUTFIT_SLOTS = {"voice": VOICES, "style": STYLES, "quirk": QUIRKS}


def _check(value: Any, slots: Dict[str, Any], code: str) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise StoreError(400, code, "expected an object")
    out = {}
    for key, allowed in slots.items():
        v = value.get(key)
        if not isinstance(v, str) or v not in allowed:
            raise StoreError(400, code, f"bad {key}")
        out[key] = v
    return out


def check_avatar(value: Any) -> Dict[str, str]:
    return _check(value, _AVATAR_SLOTS, "bad_avatar")


def check_outfit(value: Any) -> Dict[str, str]:
    return _check(value, _OUTFIT_SLOTS, "bad_outfit")


def catalog() -> Dict[str, Any]:
    return {"voices": list(VOICES), "styles": list(STYLES), "quirks": list(QUIRKS),
            "emojis": list(EMOJIS), "colors": list(COLORS)}
