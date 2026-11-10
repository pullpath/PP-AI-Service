"""Data access for spy-hunt rooms, players and events.

Every state change goes through `tx(room_id)`: the room's RLock plus one
`BEGIN IMMEDIATE` transaction, and bumps `rooms.version`. This module never
reads `players.role` or pair words; client payloads come from visibility.py.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import secrets
import sqlite3
import threading
import time
import unicodedata
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from ai_svc.spy_hunt import locks, visibility
from ai_svc.spy_hunt.config import LANGS, GameConfig
from ai_svc.spy_hunt.db import get_conn

log = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 4
NAME_MAX = 16
_CODE_ATTEMPTS = 50
# Columns store may read from players; never `role` (visibility.py owns that).
PUBLIC_PLAYER_COLS = "seat, player_id, name, lang, is_bot, alive, connected, avatar_emoji, avatar_color, bot_id"


class StoreError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def now_ms() -> int:
    return int(time.time() * 1000)


# ---- input cleaning ----

def clean_name(value: Any) -> str:
    """Strip control/format characters (Unicode category C, which includes
    \\n, \\t, bidi overrides and zero-width chars), collapse whitespace, cap at 16."""
    if not isinstance(value, str):
        raise StoreError(400, "bad_name", "Name must be a string.")
    kept = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C"))
    name = " ".join(kept.split())[:NAME_MAX].strip()
    if not name:
        raise StoreError(400, "bad_name", "Name is empty.")
    return name


def check_lang(value: Any) -> str:
    if not isinstance(value, str) or value not in LANGS:
        raise StoreError(400, "bad_lang", f"Language must be one of {', '.join(LANGS)}.")
    return value


# ---- transactions ----

@contextmanager
def tx(room_id: str) -> Iterator[sqlite3.Connection]:
    """Room lock + one `BEGIN IMMEDIATE` transaction; commit on success, rollback on error.

    Contract for callers (Task 5 and later):
    - Every state change runs inside `with store.tx(room_id) as conn:` and uses
      that `conn` (the thread's connection) for all reads and writes, including
      `append_event(..., conn=conn)`. Events are committed atomically with the
      state change they describe.
    - Re-entrant: the room lock is an RLock, and if this thread's connection is
      already in a transaction, a nested `tx` just yields it: no new BEGIN, no
      commit, no rollback. The OUTERMOST `tx` decides commit/rollback, so an
      exception raised in a nested block and caught inside the outer block
      does NOT roll back the nested writes.
    - Nesting `tx` for a DIFFERENT room joins the outer transaction too, but
      takes that room's lock as well; always lock rooms in a consistent order.
    - Call `_bump(conn, room_id)` for every state change (bumps `version`).
      Never make a model call inside `tx` (impl §8.3).
    """
    with locks.room_lock(room_id):
        conn = get_conn()
        if conn.in_transaction:
            yield conn
            return
        _pending_notify().clear()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            _pending_notify().clear()
            raise
        else:
            conn.commit()
            _flush_notify()


# Rooms that got an event in this thread's open transaction. Stream waiters are
# woken only after the OUTERMOST tx commits (events.notify), never before, and
# never for a rolled-back transaction.
_notify_local = threading.local()


def _pending_notify() -> set:
    rooms = getattr(_notify_local, "rooms", None)
    if rooms is None:
        rooms = _notify_local.rooms = set()
    return rooms


def _flush_notify() -> None:
    rooms = _pending_notify()
    if not rooms:
        return
    todo = sorted(rooms)
    rooms.clear()
    from ai_svc.spy_hunt import events  # lazy: events imports store
    for rid in todo:
        try:
            events.notify(rid)
        except Exception:  # a wake-up failure must not fail the committed change
            log.exception("events.notify failed for room %s", rid)


def _bump(conn: sqlite3.Connection, room_id: str) -> None:
    conn.execute(
        "UPDATE rooms SET version = version + 1, last_active = ? WHERE id = ?",
        (now_ms(), room_id),
    )


# ---- events ----

def _check_audience(audience: Any) -> None:
    if not visibility.valid_audience(audience):  # "all" or ASCII "seat:<n>"
        raise ValueError(f"bad audience: {audience!r}")


def append_event(room_id: str, type: str, payload: Dict[str, Any], audience: str,
                 conn: Optional[sqlite3.Connection] = None) -> int:
    """Insert an event and return its seq. Must run inside `tx(room_id)`: the
    event commits with the state change it describes, under the room lock."""
    _check_audience(audience)
    visibility.check_event_payload(type, payload, audience)
    conn = conn or get_conn()
    if not conn.in_transaction:
        raise RuntimeError("append_event must be called inside store.tx(room_id)")
    cur = conn.execute(
        "INSERT INTO events(room_id, type, payload_json, audience, created_at) VALUES(?,?,?,?,?)",
        (room_id, type, json.dumps(payload, ensure_ascii=False), audience, now_ms()),
    )
    _pending_notify().add(room_id)
    return cur.lastrowid


# ---- rooms ----

def _random_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def _room_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


def get_room(room_id: str) -> Optional[Dict[str, Any]]:
    return _room_dict(get_conn().execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone())


def get_room_by_code(code: str) -> Optional[Dict[str, Any]]:
    if not isinstance(code, str) or len(code) != CODE_LEN:
        return None
    return _room_dict(
        get_conn().execute("SELECT * FROM rooms WHERE code=?", (code.upper(),)).fetchone()
    )


def seat_of(room_id: str, player_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[int]:
    row = (conn or get_conn()).execute(
        "SELECT seat FROM players WHERE room_id=? AND player_id=?", (room_id, player_id)
    ).fetchone()
    return row["seat"] if row else None


def _player_row(conn: sqlite3.Connection, room_id: str, seat: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT " + PUBLIC_PLAYER_COLS + " FROM players WHERE room_id=? AND seat=?",
        (room_id, seat),
    ).fetchone()


def _emit_player(conn, room, seat: int, type: str) -> None:
    row = _player_row(conn, room["id"], seat)
    player = visibility.public_player(row, room["host_player_id"])
    append_event(room["id"], type, {"player": player}, "all", conn=conn)


def create_room(player_id: str, name: str, lang: str) -> Dict[str, Any]:
    name, lang = clean_name(name), check_lang(lang)
    room_id = secrets.token_urlsafe(9)
    cfg = dataclasses.asdict(GameConfig())
    cfg["bot_fill"] = True
    ts = now_ms()
    with tx(room_id) as conn:
        for _ in range(_CODE_ATTEMPTS):
            code = _random_code()
            if conn.execute("SELECT 1 FROM rooms WHERE code=?", (code,)).fetchone():
                continue
            conn.execute(
                "INSERT INTO rooms(id, code, host_player_id, main_lang, config_json, status,"
                " phase, phase_deadline, round, ai_calls, game_no, phase_seq, last_active,"
                " created_at, version)"
                " VALUES(?,?,?,?,?,'lobby',NULL,NULL,0,0,1,0,?,?,1)",
                (room_id, code, player_id, lang, json.dumps(cfg), ts, ts),
            )
            break
        else:
            raise StoreError(503, "no_code", "Could not allocate a room code, try again.")
        room = dict(conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone())
        _insert_player(conn, room, player_id, name, lang)
    return get_room(room_id)


def _insert_player(conn, room, player_id: str, name: str, lang: str) -> int:
    cfg = json.loads(room["config_json"])
    seats = {r["seat"] for r in conn.execute(
        "SELECT seat FROM players WHERE room_id=?", (room["id"],))}
    if len(seats) >= cfg["max_players"]:
        raise StoreError(409, "room_full", "The room is full.")
    seat = next(i for i in range(len(seats) + 1) if i not in seats)
    conn.execute(
        "INSERT INTO players(room_id, player_id, seat, name, lang, is_bot, bot_persona,"
        " alive, connected, joined_at) VALUES(?,?,?,?,?,0,NULL,1,0,?)",
        (room["id"], player_id, seat, name, lang, now_ms()),
    )
    _bump(conn, room["id"])
    _emit_player(conn, room, seat, "player_joined")
    return seat


def add_player(room_id: str, player_id: str, name: str, lang: str) -> tuple[int, bool]:
    """Join a lobby. Returns (seat, created). An existing member gets (seat, False)
    whatever the room status, with no change."""
    name, lang = clean_name(name), check_lang(lang)
    with tx(room_id) as conn:
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None:
            raise StoreError(404, "not_found", "No such room.")
        existing = seat_of(room_id, player_id, conn)
        if existing is not None:
            return existing, False
        if room["status"] != "lobby":
            raise StoreError(409, "game_started", "The game has already started.")
        return _insert_player(conn, dict(room), player_id, name, lang), True


def update_me(room_id: str, player_id: str, name: Any = None, lang: Any = None) -> bool:
    """Returns True when the player's language actually changed."""
    if name is None and lang is None:
        raise StoreError(400, "bad_request", "Nothing to change.")
    name = clean_name(name) if name is not None else None
    lang = check_lang(lang) if lang is not None else None
    with tx(room_id) as conn:
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        seat = seat_of(room_id, player_id, conn)
        if room is None or seat is None:
            raise StoreError(403, "not_member", "You are not in this room.")
        if name is not None:
            conn.execute("UPDATE players SET name=? WHERE room_id=? AND seat=?", (name, room_id, seat))
        changed = False
        if lang is not None:
            old = conn.execute("SELECT lang FROM players WHERE room_id=? AND seat=?",
                               (room_id, seat)).fetchone()["lang"]
            changed = old != lang
            conn.execute("UPDATE players SET lang=? WHERE room_id=? AND seat=?", (lang, room_id, seat))
        _bump(conn, room_id)
        _emit_player(conn, dict(room), seat, "player_updated")
    return changed


def update_settings(room_id: str, player_id: str, main_lang: Any = None,
                    bot_fill: Any = None) -> None:
    if main_lang is None and bot_fill is None:
        raise StoreError(400, "bad_request", "Nothing to change.")
    if main_lang is not None:
        check_lang(main_lang)
    if bot_fill is not None and not isinstance(bot_fill, bool):
        raise StoreError(400, "bad_request", "bot_fill must be true or false.")
    with tx(room_id) as conn:
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None or room["host_player_id"] != player_id:
            raise StoreError(403, "not_host", "Only the host can change settings.")
        if room["status"] != "lobby":
            raise StoreError(409, "not_lobby", "Settings can only change in the lobby.")
        cfg = json.loads(room["config_json"])
        if bot_fill is not None:
            cfg["bot_fill"] = bot_fill
        new_lang = main_lang if main_lang is not None else room["main_lang"]
        conn.execute("UPDATE rooms SET main_lang=?, config_json=? WHERE id=?",
                     (new_lang, json.dumps(cfg), room_id))
        _bump(conn, room_id)
        append_event(room_id, "settings",
                     {"main_lang": new_lang, "bot_fill": cfg["bot_fill"]}, "all", conn=conn)
