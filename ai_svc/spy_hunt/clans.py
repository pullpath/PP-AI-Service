"""Clans: membership, points from play, and weekly seasons against a rival clan.

Registered accounts only. Everything is lazy: there is no scheduler, so the
first request in a new UTC week closes the weeks that ended and pairs clans
for the current one (`roll_weeks`).
"""
from __future__ import annotations

import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.outfits import COLORS
from ai_svc.spy_hunt.store import CODE_ALPHABET, StoreError

MAX_MEMBERS = 30
NAME_MIN, NAME_MAX = 3, 20
CODE_LEN = 6
OPEN_LIST_MAX = 20

_BADGE_EMOJIS = ("🦊", "🐺", "🦉", "🐉", "🦁", "🐙", "🦅", "🐝", "🌵", "🚀", "⚡", "🔥")
BADGES: List[Dict[str, str]] = [
    {"emoji": e, "color": COLORS[i % len(COLORS)]} for i, e in enumerate(_BADGE_EMOJIS)]


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


def _require_registered(conn: sqlite3.Connection, player_id: str) -> None:
    row = conn.execute("SELECT email FROM guests WHERE player_id=?", (player_id,)).fetchone()
    if row is None or not row["email"]:
        raise StoreError(403, "register_required", "Register an account to join a clan.")


def _badge(row) -> Dict[str, str]:
    return {"emoji": row["badge_emoji"], "color": row["badge_color"]}


def _check_name(name: Any) -> str:
    if not isinstance(name, str):
        raise StoreError(400, "bad_name", f"Clan name must be {NAME_MIN} to {NAME_MAX} characters.")
    name = " ".join(name.split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise StoreError(400, "bad_name", f"Clan name must be {NAME_MIN} to {NAME_MAX} characters.")
    return name


def _member_count(conn, clan_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id=?", (clan_id,)).fetchone()[0]


def _clan_dict(conn, row) -> Dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "badge": _badge(row), "code": row["code"],
            "members": _member_count(conn, row["id"])}


def _in_clan(conn, player_id: str) -> bool:
    return conn.execute("SELECT 1 FROM clan_members WHERE player_id=?", (player_id,)).fetchone() is not None


def create(player_id: str, name: Any, badge_index: Any) -> Dict[str, Any]:
    name = _check_name(name)
    if isinstance(badge_index, bool) or not isinstance(badge_index, int) \
            or not 0 <= badge_index < len(BADGES):
        raise StoreError(400, "bad_badge", "Pick one of the offered badges.")
    badge = BADGES[badge_index]
    with _tx() as c:
        _require_registered(c, player_id)
        if _in_clan(c, player_id):
            raise StoreError(409, "already_in_clan", "Leave your current clan first.")
        if c.execute("SELECT 1 FROM clans WHERE name_key=?", (name.casefold(),)).fetchone():
            raise StoreError(409, "name_taken", "That clan name is taken.")
        now = _now_ms()
        clan_id = uuid.uuid4().hex
        for _ in range(50):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            if not c.execute("SELECT 1 FROM clans WHERE code=?", (code,)).fetchone():
                break
        else:  # pragma: no cover - 31^6 codes
            raise StoreError(503, "no_code", "Try again.")
        c.execute("INSERT INTO clans(id, name, name_key, badge_emoji, badge_color, code, leader_id,"
                  " created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (clan_id, name, name.casefold(), badge["emoji"], badge["color"], code, player_id, now))
        c.execute("INSERT INTO clan_members(player_id, clan_id, joined_at) VALUES (?,?,?)",
                  (player_id, clan_id, now))
        return _clan_dict(c, c.execute("SELECT * FROM clans WHERE id=?", (clan_id,)).fetchone())


def join(player_id: str, code: Any) -> Dict[str, Any]:
    code = code.strip().upper() if isinstance(code, str) else ""
    with _tx() as c:
        _require_registered(c, player_id)
        row = c.execute("SELECT * FROM clans WHERE code=?", (code,)).fetchone()
        if row is None:
            raise StoreError(404, "no_clan", "No clan has that code.")
        if _in_clan(c, player_id):
            raise StoreError(409, "already_in_clan", "Leave your current clan first.")
        if _member_count(c, row["id"]) >= MAX_MEMBERS:
            raise StoreError(409, "clan_full", "That clan is full.")
        c.execute("INSERT INTO clan_members(player_id, clan_id, joined_at) VALUES (?,?,?)",
                  (player_id, row["id"], _now_ms()))
        return _clan_dict(c, row)


def leave(player_id: str) -> Dict[str, Any]:
    with _tx() as c:
        m = c.execute("SELECT clan_id FROM clan_members WHERE player_id=?", (player_id,)).fetchone()
        if m is None:
            raise StoreError(409, "not_in_clan", "You are not in a clan.")
        clan_id = m["clan_id"]
        c.execute("DELETE FROM clan_members WHERE player_id=?", (player_id,))
        heir = c.execute("SELECT player_id FROM clan_members WHERE clan_id=?"
                         " ORDER BY joined_at, rowid LIMIT 1", (clan_id,)).fetchone()
        if heir is None:
            c.execute("DELETE FROM clans WHERE id=?", (clan_id,))
        else:
            c.execute("UPDATE clans SET leader_id=? WHERE id=? AND leader_id=?",
                      (heir["player_id"], clan_id, player_id))
        return {"ok": True}


def list_open(limit: int = OPEN_LIST_MAX) -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id=c.id) n FROM clans c"
        " WHERE (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id=c.id) < ?"
        " ORDER BY c.created_at DESC, c.rowid DESC LIMIT ?", (MAX_MEMBERS, limit)).fetchall()
    return [{"id": r["id"], "name": r["name"], "badge": _badge(r), "code": r["code"],
             "members": r["n"]} for r in rows]


def membership(player_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    conn = conn or get_conn()
    r = conn.execute("SELECT c.*, m.joined_at FROM clan_members m JOIN clans c ON c.id=m.clan_id"
                     " WHERE m.player_id=?", (player_id,)).fetchone()
    if r is None:
        return None
    return {"clan_id": r["id"], "name": r["name"], "badge": _badge(r), "code": r["code"],
            "leader_id": r["leader_id"], "joined_at": r["joined_at"]}


# ---- points ----

GAME_PLAY, GAME_WIN = 10, 10
DAILY_DONE, DAILY_SOLVED = 10, 10
DAILY_CAP = 100
MIN_HUMANS = 2


def week_of(ts_ms: int) -> str:
    """ISO date of the UTC Monday that starts the week containing ts_ms."""
    from datetime import datetime, timedelta, timezone
    d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def _utc_day(ts_ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _add(conn, key: str, player_id: str, points: int, now: int) -> None:
    m = membership(player_id, conn)
    if m is None or points <= 0:
        return
    if conn.execute("SELECT 1 FROM clan_points WHERE key=?", (key,)).fetchone():
        return
    day = _utc_day(now)
    used = conn.execute("SELECT COALESCE(SUM(points), 0) FROM clan_points"
                        " WHERE player_id=? AND created_day=?", (player_id, day)).fetchone()[0]
    points = min(points, DAILY_CAP - used)
    if points <= 0:
        return
    conn.execute("INSERT OR IGNORE INTO clan_points(key, clan_id, player_id, week, created_day,"
                 " points, created_at) VALUES (?,?,?,?,?,?,?)",
                 (key, m["clan_id"], player_id, week_of(now), day, points, now))


def _safely(fn, *args) -> None:
    # Clan points are a side effect of play; they must never break the game or the puzzle.
    import logging
    conn = args[0]
    try:
        conn.execute("SAVEPOINT clan_award")
        fn(*args)
        conn.execute("RELEASE clan_award")
    except Exception:
        logging.getLogger(__name__).exception("clan award failed")
        try:
            conn.execute("ROLLBACK TO clan_award")
            conn.execute("RELEASE clan_award")
        except sqlite3.Error:
            pass


def _award_game(conn, room_id: str, game_no: int, rows, winner: Optional[str]) -> None:
    if winner not in ("spies", "civilians"):
        return
    humans = [r for r in rows if not r["is_bot"]]
    if len(humans) < MIN_HUMANS:
        return
    now = _now_ms()
    for r in humans:
        won = (r["role"] == "spy") == (winner == "spies")
        _add(conn, f"g:{room_id}:{game_no}:{r['player_id']}", r["player_id"],
             GAME_PLAY + (GAME_WIN if won else 0), now)


def award_game(conn, room_id: str, game_no: int, rows, winner: Optional[str]) -> None:
    _safely(_award_game, conn, room_id, game_no, rows, winner)


def _award_daily(conn, player_id: str, day: str, solved: bool) -> None:
    _add(conn, f"d:{day}:{player_id}", player_id, DAILY_DONE + (DAILY_SOLVED if solved else 0), _now_ms())


def award_daily(conn, player_id: str, day: str, solved: bool) -> None:
    _safely(_award_daily, conn, player_id, day, solved)
