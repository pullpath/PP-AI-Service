"""Offline daily-puzzle generator (design: daily-puzzle spec section 5).

Plays a bot-only game on paper: no rooms, timers or votes. Every model call goes
through llm.call_json against a throwaway builder room's budget, and none runs
inside a transaction.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from . import bots, engine, game, llm, prompts
from .config import BOT_NAMES, LANGS, GameConfig

log = logging.getLogger("spy_hunt.puzzle_gen")

PLAYERS = 5
ROUNDS = 2
STATEMENT_ATTEMPTS = 2
ATTEMPTS_PER_PAIR = 3
MIN_CONFIDENCE = 40
TOO_EASY_CONFIDENCE = 95
QUEUE_TARGET = 14
TRANSLATE_MAX_TOKENS = 900


class _TranslateOut(BaseModel):
    translations: List[str] = []


def _clean(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[: GameConfig().statement_max_chars]


def _leaks(text: str, pair: game.Pair) -> bool:
    secrets = {f"{lang}{k}": pair.words[lang][k] for lang in LANGS for k in ("a", "b")}
    return engine.contains_own_word(text, secrets)


def _statement(room_id: str, view: Dict[str, Any], persona: bots.BotProfile,
               pair: game.Pair) -> Optional[str]:
    for _ in range(STATEMENT_ATTEMPTS):
        try:
            out = llm.call_json("puzzle_statement", bots._prompt_describe(view, persona),
                                bots._StatementOut, room_id, bots.STATEMENT_MAX_TOKENS,
                                llm.TASK_TIMEOUTS["puzzle_statement"])
        except Exception:  # LlmError, BudgetExceeded: no canned fallback in a puzzle
            log.info("puzzle statement failed room_id=%s", room_id)
            return None
        text = _clean(out.statement)
        if text and not _leaks(text, pair):
            return text
    return None


def _translate(room_id: str, texts: List[str], source: str, target: str,
               pair: game.Pair) -> Optional[List[str]]:
    prompt = (
        f"Translate each statement below from {source} to {target}. {prompts.TRANSLATE_RULE}\n"
        + prompts.data_block(json.dumps(texts, ensure_ascii=False))
        + f'\nReturn ONLY JSON: {{"translations": [exactly {len(texts)} strings, same order]}}')
    try:
        out = llm.call_json("puzzle_translate", prompt, _TranslateOut, room_id,
                            TRANSLATE_MAX_TOKENS, llm.TASK_TIMEOUTS["puzzle_translate"])
    except Exception:
        log.info("puzzle translation failed room_id=%s", room_id)
        return None
    cleaned = [_clean(t) for t in out.translations]
    if len(cleaned) != len(texts) or not all(cleaned) or any(_leaks(t, pair) for t in cleaned):
        return None
    return cleaned


def build_candidate(room_id: str, pair: game.Pair, origin_lang: str,
                    rng: random.Random) -> Optional[Dict[str, Any]]:
    other = next(lang for lang in LANGS if lang != origin_lang)
    civ_key = rng.choice(("a", "b"))
    spy_key = "b" if civ_key == "a" else "a"
    spy_seat = rng.randrange(PLAYERS)
    names = rng.sample(BOT_NAMES, PLAYERS)
    pool = list(bots.PERSONAS.values())
    rng.shuffle(pool)
    personas = [pool[i % len(pool)] for i in range(PLAYERS)]

    statements: List[Dict[str, Any]] = []
    for rnd in range(1, ROUNDS + 1):
        for seat in range(PLAYERS):
            key = spy_key if seat == spy_seat else civ_key
            view = {"my_word": pair.words[origin_lang][key], "round": rnd, "players": names,
                    "statements": [{"name": names[m["seat"]], "text": m["text"]}
                                   for m in statements]}
            text = _statement(room_id, view, personas[seat], pair)
            if text is None:
                return None
            statements.append({"id": len(statements) + 1, "round": rnd, "stage": 0,
                               "seat": seat, "kind": "statement", "text": text,
                               "lang": origin_lang, "translations": {}, "created_at": 0})

    translated = _translate(room_id, [m["text"] for m in statements], origin_lang, other, pair)
    if translated is None:
        return None
    for m, t in zip(statements, translated):
        m["translations"] = {other: t}

    civilian_word = {lang: pair.words[lang][civ_key] for lang in LANGS}
    spy_word = {lang: pair.words[lang][spy_key] for lang in LANGS}
    return {
        "public": {"origin_lang": origin_lang, "civilian_word": civilian_word,
                   "players": [{"seat": s, "name": n} for s, n in enumerate(names)],
                   "statements": statements, "options": []},
        "answer": {"spy_seat": spy_seat, "spy_word": spy_word,
                   "civilian_word": civilian_word, "option_index": None},
    }
