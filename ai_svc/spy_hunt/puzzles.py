"""Daily puzzle storage, publishing and play state (design: daily-puzzle spec).

No model calls here: generation lives in puzzle_gen.py. Mutations run in one
`BEGIN IMMEDIATE` transaction so parallel requests serialise.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from .db import get_conn
from .store import StoreError

MAX_TRIES = 2
PLAYERS = 5
OPTIONS = 4
FULL_BONUS_MS = 60_000
NO_BONUS_MS = 180_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def utc_day(now_ms: Optional[int] = None) -> str:
    ms = _now_ms() if now_ms is None else now_ms
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


@contextmanager
def _tx() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def insert_ready(public: Dict[str, Any], answer: Dict[str, Any], difficulty: int,
                 pair_id: str) -> int:
    with _tx() as c:
        cur = c.execute(
            "INSERT INTO puzzles(number, day, status, pair_id, difficulty, public_json,"
            " answer_json, created_at) VALUES(NULL, NULL, 'ready', ?, ?, ?, ?, ?)",
            (pair_id, difficulty, json.dumps(public, ensure_ascii=False),
             json.dumps(answer, ensure_ascii=False), _now_ms()))
        return int(cur.lastrowid)


def ready_count() -> int:
    return get_conn().execute(
        "SELECT COUNT(*) c FROM puzzles WHERE status='ready'").fetchone()["c"]


def list_ready() -> List[Dict[str, Any]]:
    return [dict(r) for r in get_conn().execute(
        "SELECT id, pair_id, difficulty, created_at FROM puzzles WHERE status='ready'"
        " ORDER BY id")]


def veto(puzzle_id: int) -> bool:
    with _tx() as c:
        cur = c.execute("UPDATE puzzles SET status='vetoed' WHERE id=? AND status='ready'",
                        (puzzle_id,))
        return cur.rowcount == 1


def publish_today(day: str) -> Optional[sqlite3.Row]:
    with _tx() as c:
        row = c.execute("SELECT * FROM puzzles WHERE day=?", (day,)).fetchone()
        if row is not None:
            return row
        nxt = c.execute(
            "SELECT id FROM puzzles WHERE status='ready' ORDER BY id LIMIT 1").fetchone()
        if nxt is None:
            return None
        number = c.execute("SELECT COALESCE(MAX(number), 0) + 1 n FROM puzzles").fetchone()["n"]
        c.execute("UPDATE puzzles SET day=?, number=?, status='published' WHERE id=?",
                  (day, number, nxt["id"]))
        return c.execute("SELECT * FROM puzzles WHERE id=?", (nxt["id"],)).fetchone()


def public_payload(row: sqlite3.Row) -> Dict[str, Any]:
    pub = json.loads(row["public_json"])
    return {"number": row["number"], "day": row["day"], "difficulty": row["difficulty"],
            "origin_lang": pub["origin_lang"], "civilian_word": pub["civilian_word"],
            "players": pub["players"], "statements": pub["statements"],
            "options": pub["options"]}


# ---- play ----

def score(solved_try: Optional[int], elapsed_ms: int, word_correct: bool) -> int:
    if solved_try is None:
        return 0
    base = 100 if solved_try == 1 else 60
    frac = (NO_BONUS_MS - elapsed_ms) / (NO_BONUS_MS - FULL_BONUS_MS)
    bonus = round(20 * min(1.0, max(0.0, frac)))
    return base + bonus + (20 if word_correct else 0)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _me(att) -> Dict[str, Any]:
    return {"stage": att["stage"], "tries": att["tries"],
            "tries_left": max(0, MAX_TRIES - att["tries"]) if att["stage"] == "spy" else 0}


def _attempt(c, day: str, player_id: str):
    return c.execute("SELECT * FROM puzzle_results WHERE day=? AND player_id=?",
                     (day, player_id)).fetchone()


def _answer(c, day: str) -> Dict[str, Any]:
    return json.loads(c.execute("SELECT answer_json FROM puzzles WHERE day=?",
                                (day,)).fetchone()["answer_json"])


def get_today(player_id: str, day: Optional[str] = None) -> Dict[str, Any]:
    day = day or utc_day()
    row = publish_today(day)
    if row is None:
        raise StoreError(503, "no_puzzle", "Today's puzzle is not ready yet.")
    with _tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO puzzle_results(day, player_id, stage, tries, solved,"
            " started_at) VALUES(?,?,?,?,?,?)", (day, player_id, "spy", 0, 0, _now_ms()))
        att = _attempt(c, day, player_id)
    return {"puzzle": public_payload(row), "me": _me(att)}


def guess_spy(player_id: str, spy_seat: Any, day: Optional[str] = None) -> Dict[str, Any]:
    day = day or utc_day()
    if not _is_int(spy_seat) or not 0 <= spy_seat < PLAYERS:
        raise StoreError(400, "bad_seat", "spy_seat must be a seat number from 0 to 4.")
    with _tx() as c:
        att = _attempt(c, day, player_id)
        if att is None:
            raise StoreError(404, "no_attempt", "Open today's puzzle first.")
        if att["stage"] != "spy":
            raise StoreError(409, "wrong_stage", "You are not guessing the spy right now.")
        tries = att["tries"] + 1
        if spy_seat == _answer(c, day)["spy_seat"]:
            c.execute("UPDATE puzzle_results SET tries=?, solved=1, stage='word'"
                      " WHERE day=? AND player_id=?", (tries, day, player_id))
            return {"correct": True, "stage": "word", "tries": tries,
                    "tries_left": MAX_TRIES - tries}
        if tries >= MAX_TRIES:
            c.execute("UPDATE puzzle_results SET tries=?, solved=0, stage='done', finished_at=?,"
                      " score=0 WHERE day=? AND player_id=?", (tries, _now_ms(), day, player_id))
            return {"correct": False, "stage": "done", "tries": tries, "tries_left": 0}
        c.execute("UPDATE puzzle_results SET tries=? WHERE day=? AND player_id=?",
                  (tries, day, player_id))
        return {"correct": False, "stage": "spy", "tries": tries,
                "tries_left": MAX_TRIES - tries}


def guess_word(player_id: str, option: Any, day: Optional[str] = None) -> Dict[str, Any]:
    day = day or utc_day()
    if option is not None and (not _is_int(option) or not 0 <= option < OPTIONS):
        raise StoreError(400, "bad_option", "option must be 0 to 3, or null to skip.")
    with _tx() as c:
        att = _attempt(c, day, player_id)
        if att is None:
            raise StoreError(404, "no_attempt", "Open today's puzzle first.")
        if att["stage"] != "word":
            raise StoreError(409, "wrong_stage", "You are not guessing the word right now.")
        correct = None if option is None else option == _answer(c, day)["option_index"]
        now = _now_ms()
        total = score(att["tries"], now - att["started_at"], bool(correct))
        c.execute("UPDATE puzzle_results SET stage='done', finished_at=?, score=?,"
                  " word_correct=? WHERE day=? AND player_id=?",
                  (now, total, None if correct is None else int(correct), day, player_id))
        return {"correct": correct, "stage": "done"}


def result(player_id: str, day: Optional[str] = None) -> Dict[str, Any]:
    day = day or utc_day()
    with _tx() as c:
        att = _attempt(c, day, player_id)
        if att is None or att["stage"] != "done":
            raise StoreError(409, "not_finished", "Finish today's puzzle first.")
        ans = _answer(c, day)
        agg = c.execute("SELECT COUNT(*) n, COALESCE(SUM(solved), 0) s FROM puzzle_results"
                        " WHERE day=? AND stage='done'", (day,)).fetchone()
    wc = att["word_correct"]
    return {
        "solved": bool(att["solved"]), "tries": att["tries"],
        "word_correct": None if wc is None else bool(wc),
        "elapsed_ms": att["finished_at"] - att["started_at"], "score": att["score"],
        "answer": {"spy_seat": ans["spy_seat"], "spy_word": ans["spy_word"],
                   "civilian_word": ans["civilian_word"]},
        "stats": {"players": agg["n"], "solved_pct": round(100 * agg["s"] / agg["n"]) if agg["n"] else 0},
    }
