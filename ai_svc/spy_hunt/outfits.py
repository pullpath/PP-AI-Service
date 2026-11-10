"""Bot outfit option tables and validation. Must not import bots/game."""
from __future__ import annotations

from typing import Any, Dict, List

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

TRIGGERS = ("accused", "first_to_speak", "last_to_speak", "after_elimination", "late_game")
ACTIONS = ("counter_accuse", "copy_previous", "go_vague", "vote_accuser", "vote_leader")
MAX_RULES = 3
STATEMENT_ACTIONS = frozenset({"counter_accuse", "copy_previous", "go_vague"})
VOTE_ACTIONS = frozenset({"vote_accuser", "vote_leader"})

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


def _rule(e: Any) -> Any:
    if not isinstance(e, dict):
        return None
    when, do = e.get("when"), e.get("do")
    if not isinstance(when, str) or when not in TRIGGERS or not isinstance(do, str) or do not in ACTIONS:
        return None
    return {"when": when, "do": do}


def _check_rules(value: Any) -> List[Dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StoreError(400, "bad_outfit", "bad rules")
    if len(value) > MAX_RULES:
        raise StoreError(400, "bad_outfit", f"at most {MAX_RULES} rules")
    out: List[Dict[str, str]] = []
    for e in value:
        r = _rule(e)
        if r is None or r in out:
            raise StoreError(400, "bad_outfit", "bad rule")
        out.append(r)
    return out


def clean_rules(value: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(value, list):
        return out
    for e in value:
        r = _rule(e)
        if r is not None and r not in out:
            out.append(r)
        if len(out) == MAX_RULES:
            break
    return out


def check_outfit(value: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = _check(value, _OUTFIT_SLOTS, "bad_outfit")
    out["rules"] = _check_rules(value.get("rules"))
    return out


def catalog() -> Dict[str, Any]:
    return {"voices": list(VOICES), "styles": list(STYLES), "quirks": list(QUIRKS),
            "emojis": list(EMOJIS), "colors": list(COLORS),
            "triggers": list(TRIGGERS), "actions": list(ACTIONS), "max_rules": MAX_RULES}
