"""Language detection and translation of chat messages.

Everything here runs in worker threads (workers.py), OUTSIDE any lock or
transaction: the model is only called between short transactions (impl §8.3).

* `detect_local` decides en / zh-Hans from the letters; the model only decides
  when that is undecidable (digits, emoji, genuinely mixed text).
* `process_message` stores `messages.lang`, and makes at most ONE model call for
  all target languages (the distinct languages of the room's HUMAN players that
  differ from the message language; bots read the original text).
* `ensure_for` is the lazy backfill when a player switches language.

Budget degradation order (impl §14): host narration stops first (Task 11),
then translation (below 20% of the room budget left, translation is skipped),
and bots/host replies keep working longest. Failures (`LlmError`,
`BudgetExceeded`) are logged without message text and never raised: the
original message stays the real one and no event is emitted.

Own-word rule: a translation is withheld (nothing stored or emitted) when it
contains the speaker's own secret word. The check is a case-insensitive
substring comparison on normalised text (engine.contains_own_word: NFKC, format
characters and variation selectors removed). Very short secret words (e.g. 'tea',
a single CJK character) can therefore withhold harmless translations; viewers
then see the original only (accepted trade-off).

Security: message text reaches the model only inside `prompts.data_block`;
output is schema-validated, stripped of control characters and length-capped.
"""
from __future__ import annotations

import json
import logging
import threading
import unicodedata
from typing import Dict, Iterable, List, Optional

from pydantic import BaseModel

from . import engine, game, llm, prompts, store, workers
from .config import LANGS
from .db import get_conn

log = logging.getLogger("spy_hunt.translation")

MIN_BUDGET_FRACTION = 0.20
BATCH_SIZE = 10
MAX_OUT_CHARS = 500
TRANSLATABLE_KINDS = ("statement", "host")
_installed = False
_inflight: set = set()
_inflight_lock = threading.Lock()


def _claim(key) -> bool:
    with _inflight_lock:
        if key in _inflight:
            return False
        _inflight.add(key)
        return True


def _release(key) -> None:
    with _inflight_lock:
        _inflight.discard(key)


# ---- local detection ----

def _is_cjk(c: str) -> bool:
    o = ord(c)
    return (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0x20000 <= o <= 0x2A6DF
            or 0xF900 <= o <= 0xFAFF)


def _is_latin(c: str) -> bool:
    return c.isalpha() and unicodedata.name(c, "").startswith("LATIN")


def detect_local(text: str) -> Optional[str]:
    """'zh-Hans' if mostly CJK letters, 'en' if mostly Latin letters, else None."""
    if not isinstance(text, str):
        return None
    cjk = sum(1 for c in text if _is_cjk(c))
    latin = sum(1 for c in text if _is_latin(c))
    total = cjk + latin
    if total == 0:
        return None
    if cjk / total >= 0.7:
        return "zh-Hans"
    if latin / total >= 0.7:
        return "en"
    return None


# ---- helpers ----

class _One(BaseModel):
    lang: Optional[str] = None
    translations: Dict[str, str] = {}


class _Item(BaseModel):
    id: int
    text: str


class _Batch(BaseModel):
    items: List[_Item] = []


def _clean(out: object, original: str) -> Optional[str]:
    """Strip control/format chars (bidi, zero-width, BOM, soft hyphen...) but keep
    ZWJ (U+200D) so multi-person emoji survive; collapse whitespace; cap length."""
    if not isinstance(out, str):
        return None
    kept = "".join(" " if c in "\n\r\t" else c for c in out
                   if c in "\n\r\t" or c == "\u200d"
                   or not unicodedata.category(c).startswith("C"))
    kept = " ".join(kept.split())
    cap = min(MAX_OUT_CHARS, max(40, 4 * len(original)))
    kept = kept[:cap].strip()
    return kept or None


def _leaks(room_id: str, msg, translated: str) -> bool:
    """True when the translation contains the speaker's own secret word."""
    if msg["kind"] != "statement" or msg["seat"] is None:
        return False
    words = game.speaker_words(room_id, msg["seat"])
    if words and engine.contains_own_word(translated, words):
        log.info("translation withheld (own word) message_id=%s", msg["id"])
        return True
    return False


def _stale(conn, msg) -> bool:
    room = conn.execute("SELECT game_no, status FROM rooms WHERE id=?",
                        (msg["room_id"],)).fetchone()
    return room is None or room["game_no"] != msg["game_no"] or room["status"] == "finished"


def _human_langs(conn, room_id: str) -> List[str]:
    return sorted({r["lang"] for r in conn.execute(
        "SELECT lang FROM players WHERE room_id=? AND is_bot=0", (room_id,))
        if r["lang"] in LANGS})


def _budget_ok(room_id: str) -> bool:
    if llm.budget_fraction_left(room_id) < MIN_BUDGET_FRACTION:
        log.info("translation skipped, low budget room_id=%s", room_id)
        return False
    return True


def _store(room_id: str, message_id: int, rows: Dict[str, str]) -> None:
    """INSERT OR IGNORE each translation; emit an event only for rows we inserted."""
    if not rows:
        return
    with store.tx(room_id) as conn:
        for lang, text in rows.items():
            cur = conn.execute(
                "INSERT OR IGNORE INTO translations(message_id, target_lang, text)"
                " VALUES(?,?,?)", (message_id, lang, text))
            if cur.rowcount == 1:
                store._bump(conn, room_id)
                store.append_event(room_id, "translation",
                                   {"message_id": message_id, "target_lang": lang,
                                    "text": text}, "all", conn=conn)


# ---- single message ----

def process_message(message_id: int) -> None:
    key = ("msg", message_id)
    if not _claim(key):
        return  # already being translated by another worker
    try:
        _process(message_id)
    except (llm.LlmError, llm.BudgetExceeded) as e:
        log.info("translation failed message_id=%s: %s", message_id, type(e).__name__)
    finally:
        _release(key)


def _process(message_id: int) -> None:
    conn = get_conn()
    msg = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if msg is None or msg["kind"] not in TRANSLATABLE_KINDS or msg["text"] is None:
        return
    if _stale(conn, msg):
        return
    room_id, text = msg["room_id"], msg["text"]
    speaker = None
    if msg["seat"] is not None:
        speaker = conn.execute("SELECT is_bot FROM players WHERE room_id=? AND seat=?",
                               (room_id, msg["seat"])).fetchone()
    known = msg["kind"] == "host" or (speaker is not None and speaker["is_bot"])
    lang = msg["lang"] if known and msg["lang"] in LANGS else None
    if lang is None and not any(c.isalpha() for c in text):
        return  # digits/emoji/punctuation only: nothing to translate or detect
    if lang is None:
        lang = detect_local(text)
        if lang is not None and lang != msg["lang"]:
            _set_lang(room_id, message_id, lang)
    done = {r["target_lang"] for r in conn.execute(
        "SELECT target_lang FROM translations WHERE message_id=?", (message_id,))}
    humans = [h for h in _human_langs(conn, room_id) if h not in done]
    # known source: skip it; otherwise the model decides and the source is dropped later
    targets = [t for t in humans if t != lang]
    if not targets:
        return
    if not _budget_ok(room_id):
        return
    prompt = (
        f"{prompts.TRANSLATE_RULE}\n"
        f"Target languages (codes): {json.dumps(targets)}.\n"
        + (f"The source language is {lang}.\n" if lang else
           "First detect the source language of the text: \"en\" or \"zh-Hans\".\n")
        + 'Return JSON: {"lang": "<source language code>", "translations": '
          '{"<target code>": "<translated text>"}} with one entry per target language '
          "that differs from the source language.\n"
        + prompts.data_block(text))
    res = llm.call_json("translate", prompt, _One, room_id, 400,
                        llm.TASK_TIMEOUTS["translate"])
    detected = res.lang if res.lang in LANGS else lang
    if lang is None and detected is not None and detected != msg["lang"]:
        _set_lang(room_id, message_id, detected)
    rows: Dict[str, str] = {}
    for t, out in res.translations.items():
        if t in targets and t != detected:
            c = _clean(out, text)
            if c and not _leaks(room_id, msg, c):
                rows[t] = c
    _store(room_id, message_id, rows)


def _set_lang(room_id: str, message_id: int, lang: str) -> None:
    with store.tx(room_id) as conn:
        conn.execute("UPDATE messages SET lang=? WHERE id=?", (lang, message_id))


# ---- lazy backfill ----

def ensure_for(message_ids: Iterable[int], lang: str) -> None:
    try:
        _ensure(list(message_ids), lang)
    except (llm.LlmError, llm.BudgetExceeded) as e:
        log.info("translation backfill failed: %s", type(e).__name__)


def _ensure(message_ids: List[int], lang: str) -> None:
    if lang not in LANGS:
        return
    conn = get_conn()
    todo: Dict[str, List[dict]] = {}  # room_id -> [{id, text}]
    for mid in dict.fromkeys(message_ids):
        m = conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        if m is None or m["kind"] not in TRANSLATABLE_KINDS or m["text"] is None:
            continue
        if _stale(conn, m):
            continue
        src = m["lang"] if m["lang"] in LANGS else detect_local(m["text"])
        if src is None or src == lang:
            continue
        if conn.execute("SELECT 1 FROM translations WHERE message_id=? AND target_lang=?",
                        (mid, lang)).fetchone():
            continue
        todo.setdefault(m["room_id"], []).append(
            {"id": mid, "text": m["text"], "lang": src, "row": m})
    for room_id, items in todo.items():
        if lang not in _human_langs(conn, room_id):
            continue  # nobody in the room reads it
        key = ("backfill", room_id, lang)
        if not _claim(key):
            continue  # a backfill for this room+language is already running
        try:
            _backfill_items(room_id, lang, items)
        finally:
            _release(key)


def _backfill_items(room_id: str, lang: str, items: List[dict]) -> None:
    for i in range(0, len(items), BATCH_SIZE):
        if not _budget_ok(room_id):
            break
        chunk = items[i:i + BATCH_SIZE]
        payload = json.dumps([{"id": c["id"], "text": c["text"]} for c in chunk],
                             ensure_ascii=False)
        prompt = (
            f"{prompts.TRANSLATE_RULE}\n"
            f"Translate every item's text into {lang}.\n"
            'Return JSON: {"items": [{"id": <same id>, "text": "<translation>"}]} '
            "with one entry per item.\n" + prompts.data_block(payload))
        res = llm.call_json("translate", prompt, _Batch, room_id, 1500,
                            llm.TASK_TIMEOUTS["translate"])
        by_id = {c["id"]: c for c in chunk}
        for it in res.items:
            c = by_id.get(it.id)
            out = _clean(it.text, c["text"]) if c else None
            if out and not _leaks(room_id, c["row"], out):
                _store(room_id, it.id, {lang: out})


def backfill_room(room_id: str, lang: str) -> None:
    """Translate the room's existing messages into `lang` (after a language switch)."""
    room = store.get_room(room_id)
    if room is None:
        return
    ids = [r["id"] for r in get_conn().execute(
        "SELECT id FROM messages WHERE room_id=? AND game_no=? AND kind IN ('statement','host')"
        " AND text IS NOT NULL ORDER BY id", (room_id, room["game_no"]))]
    ensure_for(ids, lang)


# ---- wiring ----

def _enqueue(message_id: int) -> None:
    workers.submit(process_message, message_id)


def install() -> None:
    """Hook game.py's post-commit message hook. Idempotent."""
    global _installed
    if not _installed:
        game.set_on_message(_enqueue)
        _installed = True


def reset() -> None:
    global _installed
    _installed = False
