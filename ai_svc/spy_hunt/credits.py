"""Credits: a per-player ledger earned from play, with a daily cap and rank tiers.

Guests earn too (no membership gate). `player_total_credits` is a denormalized
running total kept in the same transaction as each ledger insert.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from ai_svc.spy_hunt.db import get_conn

CREDITS_DAILY_CAP = 500

RANKS: List[Dict[str, Any]] = [
    {"key": "rookie", "min": 0, "hero": "🐣"},
    {"key": "sleuth", "min": 250, "hero": "🦊"},
    {"key": "hunter", "min": 750, "hero": "🕵️"},
    {"key": "senior", "min": 2000, "hero": "🦉"},
    {"key": "mastermind", "min": 5000, "hero": "🧠"},
    {"key": "legend", "min": 12000, "hero": "👑"},
]


def _now_ms() -> int:
    return int(time.time() * 1000)


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


def _utc_day(ts_ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _add(conn, key: str, player_id: str, credits: int, now: int) -> int:
    """Award credits once per key, clamped to the daily cap. Returns the amount added."""
    if credits <= 0:
        return 0
    if conn.execute("SELECT 1 FROM player_credits WHERE key=?", (key,)).fetchone():
        return 0
    day = _utc_day(now)
    used = conn.execute("SELECT COALESCE(SUM(credits), 0) FROM player_credits"
                        " WHERE player_id=? AND created_day=?", (player_id, day)).fetchone()[0]
    credits = min(credits, CREDITS_DAILY_CAP - used)
    if credits <= 0:
        return 0
    conn.execute("INSERT INTO player_credits(key, player_id, credits, created_day, created_at)"
                 " VALUES (?,?,?,?,?)", (key, player_id, credits, day, now))
    conn.execute("INSERT INTO player_total_credits(player_id, credits, updated_at) VALUES(?,?,?)"
                 " ON CONFLICT(player_id) DO UPDATE SET credits = credits + excluded.credits,"
                 " updated_at = excluded.updated_at", (player_id, credits, now))
    return credits


def total(conn, player_id: str) -> int:
    row = conn.execute("SELECT credits FROM player_total_credits WHERE player_id=?",
                       (player_id,)).fetchone()
    return int(row[0]) if row else 0


def rank_for(total: int) -> Dict[str, Any]:
    for i in range(len(RANKS) - 1, -1, -1):
        if total >= RANKS[i]["min"]:
            return {"index": i, "key": RANKS[i]["key"], "min": RANKS[i]["min"]}
    return {"index": 0, "key": RANKS[0]["key"], "min": RANKS[0]["min"]}


def summary(player_id: str) -> Dict[str, Any]:
    conn = get_conn()
    tot = total(conn, player_id)
    today = conn.execute("SELECT COALESCE(SUM(credits), 0) FROM player_credits"
                         " WHERE player_id=? AND created_day=?",
                         (player_id, _utc_day(_now_ms()))).fetchone()[0]
    rank = rank_for(tot)
    nxt: Optional[Dict[str, Any]] = None
    if rank["index"] + 1 < len(RANKS):
        n = RANKS[rank["index"] + 1]
        nxt = {"key": n["key"], "min": n["min"], "remaining": n["min"] - tot}
    return {"credits": tot, "today": int(today), "rank": rank, "next": nxt}
