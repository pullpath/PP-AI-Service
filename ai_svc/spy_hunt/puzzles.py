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
