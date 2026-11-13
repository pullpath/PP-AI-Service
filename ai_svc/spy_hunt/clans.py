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
    import unicodedata
    if not isinstance(name, str):
        raise StoreError(400, "bad_name", f"Clan name must be {NAME_MIN} to {NAME_MAX} characters.")
    # drop invisible format/control characters so "Fo\u200bxes" can't pass as a new name
    name = "".join(ch for ch in unicodedata.normalize("NFKC", name)
                   if unicodedata.category(ch) not in ("Cf", "Cc") or ch in " \t\n")
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


def _refresh_badge(player_id: str) -> None:
    """After a membership change commits: re-announce this player in rooms that aren't
    finished, each under its own room lock, so other players see the new badge now."""
    from ai_svc.spy_hunt import store
    rooms = get_conn().execute(
        "SELECT DISTINCT p.room_id FROM players p JOIN rooms r ON r.id=p.room_id"
        " WHERE p.player_id=? AND p.is_bot=0 AND r.status IN ('lobby', 'playing')",
        (player_id,)).fetchall()
    for (room_id,) in rooms:
        try:
            with store.tx(room_id) as conn:
                room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
                seat = conn.execute("SELECT seat FROM players WHERE room_id=? AND player_id=? AND is_bot=0",
                                    (room_id, player_id)).fetchone()
                if room is None or seat is None or room["status"] == "finished":
                    continue
                store._bump(conn, room_id)
                store._emit_player(conn, dict(room), seat["seat"], "player_updated")
        except Exception:  # a stale badge must never fail the clan change itself
            import logging
            logging.getLogger(__name__).exception("clan badge refresh failed for room %s", room_id)


def _pick_badge(value: Any) -> Dict[str, str]:
    """A preset index (legacy) or a built {emoji, color} from looks.CLAN_EMOJIS x COLORS."""
    from ai_svc.spy_hunt import looks
    if isinstance(value, dict):
        return looks.check_badge(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(BADGES):
        raise StoreError(400, "bad_badge", "Pick one of the offered badges.")
    return BADGES[value]


def create(player_id: str, name: Any, badge_index: Any) -> Dict[str, Any]:
    name = _check_name(name)
    badge = _pick_badge(badge_index)
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
        out = _clan_dict(c, c.execute("SELECT * FROM clans WHERE id=?", (clan_id,)).fetchone())
    _refresh_badge(player_id)
    return out


def change_badge(player_id: str, value: Any) -> Dict[str, Any]:
    badge = _pick_badge(value)
    with _tx() as c:
        row = c.execute("SELECT c.* FROM clan_members m JOIN clans c ON c.id=m.clan_id"
                        " WHERE m.player_id=?", (player_id,)).fetchone()
        if row is None:
            raise StoreError(404, "no_clan", "You are not in a clan.")
        if row["leader_id"] != player_id:
            raise StoreError(403, "not_leader", "Only the clan leader can change the badge.")
        c.execute("UPDATE clans SET badge_emoji=?, badge_color=? WHERE id=?",
                  (badge["emoji"], badge["color"], row["id"]))
        out = _clan_dict(c, c.execute("SELECT * FROM clans WHERE id=?", (row["id"],)).fetchone())
        members = [r[0] for r in c.execute("SELECT player_id FROM clan_members WHERE clan_id=?",
                                           (row["id"],))]
    for pid in members:
        _refresh_badge(pid)
    return out


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
        out = _clan_dict(c, row)
    _refresh_badge(player_id)
    return out


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
    _refresh_badge(player_id)
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
    roll_weeks()
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
    roll_weeks()
    _add(conn, f"d:{day}:{player_id}", player_id, DAILY_DONE + (DAILY_SOLVED if solved else 0), _now_ms())


def award_daily(conn, player_id: str, day: str, solved: bool) -> None:
    _safely(_award_daily, conn, player_id, day, solved)


# ---- seasons ----

MIN_RIVAL_MEMBERS = 3
GHOST_FLOOR = 50
HISTORY_MAX = 8
_WEEK_MS = 7 * 24 * 3600 * 1000


def _shift_week(week: str, n: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(week) + timedelta(days=7 * n)).isoformat()


def _week_start_ms(week: str) -> int:
    from datetime import datetime, timezone
    return int(datetime.fromisoformat(week).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _score(conn, clan_id: str, week: str) -> int:
    return conn.execute("SELECT COALESCE(SUM(points), 0) FROM clan_points WHERE clan_id=? AND week=?",
                        (clan_id, week)).fetchone()[0]


def _ghost_score(conn, clan_id: str, week: str) -> int:
    others = [r["clan_id"] for r in conn.execute(
        "SELECT clan_id FROM clan_weeks WHERE week=? AND clan_id<>?", (week, clan_id))]
    if not others:
        return GHOST_FLOOR
    avg = sum(_score(conn, o, week) for o in others) / len(others)
    return max(GHOST_FLOOR, int(round(avg)))


def _close(conn, week: str) -> None:
    for r in conn.execute("SELECT * FROM clan_weeks WHERE week=? AND result IS NULL", (week,)).fetchall():
        own = _score(conn, r["clan_id"], week)
        if r["ghost"]:
            theirs = _ghost_score(conn, r["clan_id"], week)
            name = None
        else:
            theirs = _score(conn, r["rival_id"], week)
            live = conn.execute("SELECT name FROM clans WHERE id=?", (r["rival_id"],)).fetchone()
            name = live["name"] if live else r["rival_name"]
        result = "won" if own > theirs else "lost" if own < theirs else "draw"
        conn.execute("UPDATE clan_weeks SET own=?, rival_score=?, rival_name=?, result=?"
                     " WHERE week=? AND clan_id=?", (own, theirs, name, result, week, r["clan_id"]))


def _pair(conn, week: str) -> None:
    import hashlib
    prev = _shift_week(week, -1)
    rows = conn.execute(
        "SELECT c.id, c.name, c.name_key, (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id=c.id) n"
        " FROM clans c WHERE EXISTS (SELECT 1 FROM clan_points p WHERE p.clan_id=c.id AND p.week=?)",
        (prev,)).fetchall()
    eligible = sorted((r for r in rows if r["n"] >= MIN_RIVAL_MEMBERS),
                      key=lambda r: (r["n"], hashlib.sha1((r["name_key"] + week).encode()).hexdigest()))
    ins = ("INSERT OR IGNORE INTO clan_weeks(week, clan_id, rival_id, rival_name, ghost)"
           " VALUES (?,?,?,?,?)")
    for i in range(0, len(eligible) - 1, 2):
        a, b = eligible[i], eligible[i + 1]
        conn.execute(ins, (week, a["id"], b["id"], b["name"], 0))
        conn.execute(ins, (week, b["id"], a["id"], a["name"], 0))
    if len(eligible) % 2:
        conn.execute(ins, (week, eligible[-1]["id"], None, None, 1))


def roll_weeks(now_ms: Optional[int] = None) -> None:
    """Close every week that has ended, then pair the current week. Idempotent."""
    cur = week_of(_now_ms() if now_ms is None else now_ms)
    conn = get_conn()
    if not conn.in_transaction:
        # cheap read first, so viewing a clan page doesn't queue for the write lock
        seen = conn.execute("SELECT v FROM clan_meta WHERE k='paired_week'").fetchone()
        if seen is not None and seen["v"] >= cur:
            return
    with _tx() as c:
        done = c.execute("SELECT v FROM clan_meta WHERE k='paired_week'").fetchone()
        if done is not None and done["v"] >= cur:
            return
        # Walk every week since the last roll, so a week nobody touched is still paired
        # (from the week before it) and closed, in order.
        w = cur if done is None else _shift_week(done["v"], 1)
        while w <= cur:
            for prev in [r["week"] for r in c.execute(
                    "SELECT DISTINCT week FROM clan_weeks WHERE result IS NULL AND week<? ORDER BY week",
                    (w,))]:
                _close(c, prev)
            _pair(c, w)
            w = _shift_week(w, 1)
        c.execute("INSERT INTO clan_meta(k, v) VALUES ('paired_week', ?)"
                  " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (cur,))


def _display_name(conn, player_id: str) -> str:
    r = conn.execute("SELECT name FROM players WHERE player_id=? AND is_bot=0"
                     " ORDER BY joined_at DESC, rowid DESC LIMIT 1", (player_id,)).fetchone()
    return r["name"] if r and r["name"] else "Player"


def season(player_id: str, now_ms: Optional[int] = None) -> Optional[Dict[str, Any]]:
    now = _now_ms() if now_ms is None else now_ms
    conn = get_conn()
    m = membership(player_id, conn)
    if m is None:
        return None
    roll_weeks(now)
    clan_id, cur = m["clan_id"], week_of(now)
    wk = conn.execute("SELECT * FROM clan_weeks WHERE week=? AND clan_id=?", (cur, clan_id)).fetchone()
    rival = None
    if wk is not None and wk["ghost"]:
        rival = {"name": None, "badge": None, "score": _ghost_score(conn, clan_id, cur)}
    elif wk is not None:
        live = conn.execute("SELECT * FROM clans WHERE id=?", (wk["rival_id"],)).fetchone()
        rival = {"name": live["name"] if live else wk["rival_name"],
                 "badge": _badge(live) if live else None, "score": _score(conn, wk["rival_id"], cur)}
    closed = conn.execute("SELECT * FROM clan_weeks WHERE clan_id=? AND result IS NOT NULL"
                          " ORDER BY week", (clan_id,)).fetchall()
    streak = 0
    for r in closed:
        streak = streak + 1 if r["result"] == "won" else 0 if r["result"] == "lost" else streak
    history = [{"week": r["week"], "result": r["result"], "own": r["own"],
                "rival_score": r["rival_score"], "rival_name": r["rival_name"],
                "ghost": bool(r["ghost"])} for r in reversed(closed[-HISTORY_MAX:])]
    mem = conn.execute(
        "SELECT m.player_id, m.joined_at, (SELECT COALESCE(SUM(points), 0) FROM clan_points p"
        " WHERE p.clan_id=m.clan_id AND p.player_id=m.player_id AND p.week=?"
        " AND p.created_at >= m.joined_at) pts"
        " FROM clan_members m WHERE m.clan_id=? ORDER BY pts DESC, m.joined_at, m.rowid",
        (cur, clan_id)).fetchall()
    members = [{"name": _display_name(conn, r["player_id"]), "points": r["pts"],
                "is_leader": r["player_id"] == m["leader_id"]} for r in mem]
    return {"this_week": {"week": cur, "own": _score(conn, clan_id, cur), "rival": rival,
                          "ghost": bool(wk is not None and wk["ghost"]),
                          "ends_at": _week_start_ms(cur) + _WEEK_MS},
            "streak": streak, "history": history, "members": members}


def mine(player_id: str) -> Dict[str, Any]:
    m = membership(player_id)
    if m is None:
        return {"clan": None}
    conn = get_conn()
    return {"clan": {"id": m["clan_id"], "name": m["name"], "badge": m["badge"], "code": m["code"],
                     "members": _member_count(conn, m["clan_id"]),
                     "is_leader": m["leader_id"] == player_id},
            "season": season(player_id)}
