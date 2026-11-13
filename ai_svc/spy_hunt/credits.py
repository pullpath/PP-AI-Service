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
GAME_PLAY, GAME_WIN = 10, 10
DAILY_DONE, DAILY_SOLVED = 10, 10
MIN_HUMANS = 2
STREAK_STEP, STREAK_MAX = 5, 50

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


def _safely(fn, *args):
    """Run fn(*args) in a savepoint; return its result, or 0 if it raised (rolled back).

    Credits are a side effect of play and must never break the game or puzzle.
    """
    import logging
    conn = args[0]
    try:
        conn.execute("SAVEPOINT credit_award")
        result = fn(*args)
        conn.execute("RELEASE credit_award")
        return result
    except Exception:
        logging.getLogger(__name__).exception("credit award failed")
        try:
            conn.execute("ROLLBACK TO credit_award")
            conn.execute("RELEASE credit_award")
        except sqlite3.Error:
            pass
        return 0


Part = Dict[str, Any]   # {"kind": "played" | "won" | "daily" | "found" | "streak", "n": int}


def _split(got: int, nominal: List[tuple]) -> List[Part]:
    """Spread the amount actually added over its nominal parts, in order.

    The ledger stores one row per award, so when the daily cap clamps an award the
    later parts are the ones that shrink or drop; parts are never overstated.
    """
    out: List[Part] = []
    for kind, n in nominal:
        take = min(n, got)
        if take > 0:
            out.append({"kind": kind, "n": take})
        got -= take
    return out


def _award_game(conn, room_id: str, game_no: int, rows, winner: Optional[str]) -> Dict[str, List[Part]]:
    if winner not in ("spies", "civilians"):
        return {}
    humans = [r for r in rows if not r["is_bot"]]
    if len(humans) < MIN_HUMANS:
        return {}
    now = _now_ms()
    out: Dict[str, List[Part]] = {}
    for r in humans:
        pid = r["player_id"]
        key = f"g:{room_id}:{game_no}:{pid}"
        won = (r["role"] == "spy") == (winner == "spies")
        nominal = [("played", GAME_PLAY)] + ([("won", GAME_WIN)] if won else [])
        out[pid] = _split(_add(conn, key, pid, sum(n for _, n in nominal), now), nominal)
    return out


def award_game_parts(conn, room_id: str, game_no: int, rows, winner: Optional[str]) -> Dict[str, List[Part]]:
    """Per-human {player_id: [parts actually added]}; {} if ineligible or on error."""
    res = _safely(_award_game, conn, room_id, game_no, rows, winner)
    return res if isinstance(res, dict) else {}


def award_game(conn, room_id: str, game_no: int, rows, winner: Optional[str]) -> Dict[str, int]:
    """Per-human {player_id: delta actually added}; {} if ineligible or on error."""
    return {pid: sum(p["n"] for p in parts)
            for pid, parts in award_game_parts(conn, room_id, game_no, rows, winner).items()}


def _award_daily(conn, player_id: str, day: str, solved: bool, streak: int) -> List[Part]:
    now = _now_ms()
    nominal = [("daily", DAILY_DONE)] + ([("found", DAILY_SOLVED)] if solved else [])
    parts = _split(_add(conn, f"d:{day}:{player_id}", player_id, sum(n for _, n in nominal), now), nominal)
    if solved:
        bonus = min(STREAK_STEP * max(streak, 0), STREAK_MAX)
        parts += _split(_add(conn, f"ds:{day}:{player_id}", player_id, bonus, now), [("streak", bonus)])
    return parts


def award_daily_parts(conn, player_id: str, day: str, solved: bool, streak: int) -> List[Part]:
    res = _safely(_award_daily, conn, player_id, day, solved, streak)
    return res if isinstance(res, list) else []


def award_daily(conn, player_id: str, day: str, solved: bool, streak: int) -> int:
    return sum(p["n"] for p in award_daily_parts(conn, player_id, day, solved, streak))


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
    return {"credits": tot, "today": int(today), "rank": rank, "next": nxt, "rules": rules()}


def rules() -> Dict[str, Any]:
    """How credits are earned, so the client never hard-codes the numbers."""
    return {
        "game": {"played": GAME_PLAY, "won": GAME_WIN, "min_humans": MIN_HUMANS},
        "daily": {"daily": DAILY_DONE, "found": DAILY_SOLVED},
        "streak": {"step": STREAK_STEP, "max": STREAK_MAX},
        "daily_cap": CREDITS_DAILY_CAP,
    }
