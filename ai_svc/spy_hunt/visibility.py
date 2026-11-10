"""Information firewall (impl spec §7.2, §7.3).

This is the ONLY module that may read `players.role` or a pair's words while
building a client payload. Nothing here writes to the DB.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any, Dict, Iterable, Optional

from ai_svc.spy_hunt import engine
from ai_svc.spy_hunt.db import get_conn

SECRET_KEYS = frozenset({"role", "roles", "word", "words", "my_word", "bot_owner_id", "outfit_json"})
DESCRIBE_PHASES = ("describe", "tiebreak_describe")
STAGE1_PHASES = ("tiebreak_describe", "revote")
_SEAT_AUDIENCE = re.compile(r"seat:([0-9]+)")  # strict ASCII; used with fullmatch


# ---- events ----

def audience_seat(audience: Any) -> Optional[int]:
    """The seat of a `seat:<n>` audience (ASCII digits only), else None. Never raises."""
    if not isinstance(audience, str):
        return None
    m = _SEAT_AUDIENCE.fullmatch(audience)
    return int(m.group(1)) if m else None


def valid_audience(audience: Any) -> bool:
    return audience == "all" or audience_seat(audience) is not None


def visible_to(event: Dict[str, Any], seat: Optional[int]) -> bool:
    """True when the event may be sent to the player in `seat` (None = no seat)."""
    audience = event.get("audience") if isinstance(event, dict) else None
    if audience == "all":
        return True
    target = audience_seat(audience)
    return target is not None and seat is not None and target == seat


def _keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _keys(v)


def check_event_payload(type: str, payload: Dict[str, Any], audience: str) -> None:
    """Refuse to store a broadcast event that would leak a secret.

    `game_over` may carry everything; `reveal` may carry the eliminated seat's
    `role` as a TOP-LEVEL key only (never nested, never words); `state` (a full
    snapshot) must be personal.
    """
    if not isinstance(payload, dict):
        raise ValueError("event payload must be a dict")
    if audience != "all":
        return
    if type == "game_over":
        return
    if type == "state":
        raise ValueError("state events carry a personal snapshot; use audience seat:<n>")
    top = dict(payload)
    if type == "reveal":
        top.pop("role", None)
    leaked = set(_keys(top)) & SECRET_KEYS
    if leaked:
        raise ValueError(f"secret keys {sorted(leaked)} in audience=all {type!r} event")


# ---- players ----

def public_player(row: sqlite3.Row, host_player_id: Optional[str]) -> Dict[str, Any]:
    """The public view of a player row: no role, no player_id."""
    return {
        "seat": row["seat"],
        "name": row["name"],
        "lang": row["lang"],
        "is_bot": bool(row["is_bot"]),
        "alive": bool(row["alive"]),
        "connected": bool(row["connected"]),
        "avatar": ({"emoji": row["avatar_emoji"], "color": row["avatar_color"]}
                   if row["avatar_emoji"] is not None else None),
        "bot_id": row["bot_id"],
        "is_host": row["player_id"] == host_player_id,
    }


# ---- words ----

def _pair_words(conn: sqlite3.Connection, room: sqlite3.Row) -> Optional[Dict[str, Dict[str, str]]]:
    """{"civilian": {lang: word}, "spy": {lang: word}} or None if no pair."""
    if not room["pair_id"]:
        return None
    row = conn.execute("SELECT words_json FROM pairs WHERE id=?", (room["pair_id"],)).fetchone()
    if row is None or not row["words_json"]:
        return None
    words = json.loads(row["words_json"])
    civ, spy = ("a", "b") if room["civ_is_a"] else ("b", "a")
    return {
        "civilian": {lang: w.get(civ) for lang, w in words.items()},
        "spy": {lang: w.get(spy) for lang, w in words.items()},
    }


# ---- describe speaker ----

def _current_speaker(conn: sqlite3.Connection, room: sqlite3.Row,
                     players: list) -> Optional[int]:
    if room["status"] != "playing" or room["phase"] not in DESCRIBE_PHASES:
        return None
    stage = 1 if room["phase"] in STAGE1_PHASES else 0
    key = (room["id"], room["game_no"], room["round"])
    spoken = {r["seat"] for r in conn.execute(
        "SELECT seat FROM messages WHERE room_id=? AND game_no=? AND round=? AND stage=?"
        " AND kind IN ('statement','skipped') AND seat IS NOT NULL", key + (stage,))}
    alive = [p["seat"] for p in players if p["alive"]]
    tied = None
    if stage == 1:
        votes = {r["voter_seat"]: r["target_seat"] for r in conn.execute(
            "SELECT voter_seat, target_seat FROM votes WHERE room_id=? AND game_no=?"
            " AND round=? AND stage=0", key)}
        tied = engine.resolve_vote(votes, 0, alive, None).tied
    return engine.next_speaker(sorted(alive), set(alive), spoken, tied)


# ---- snapshot ----

def build_snapshot(room_id: str, player_id: str) -> Dict[str, Any]:
    """The caller's view of the room. Raises LookupError if the room is unknown
    or the caller is not a member.

    All reads happen inside one read transaction (a deferred BEGIN; in WAL mode
    every SELECT then sees the same database snapshot), so a room row and its
    players/messages can never come from different moments, e.g. a `finished`
    room combined with players from a rematch. If the caller already holds a
    transaction (inside store.tx), the reads join it.
    """
    conn = get_conn()
    if conn.in_transaction:
        return _build_snapshot(conn, room_id, player_id)
    conn.execute("BEGIN")
    try:
        return _build_snapshot(conn, room_id, player_id)
    finally:
        conn.rollback()  # read-only: end the transaction without writing


def _build_snapshot(conn: sqlite3.Connection, room_id: str, player_id: str) -> Dict[str, Any]:
    room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    if room is None:
        raise LookupError("room")
    rows = conn.execute(
        "SELECT * FROM players WHERE room_id=? ORDER BY seat", (room_id,)).fetchall()
    me = next((r for r in rows if r["player_id"] == player_id), None)
    if me is None:
        raise LookupError("member")

    status = room["status"]
    finished = status == "finished"
    playing = status == "playing"
    host_seat = next((r["seat"] for r in rows if r["player_id"] == room["host_player_id"]), None)

    players = []
    for r in rows:
        p = public_player(r, room["host_player_id"])
        if r["role"]:
            if finished:
                p["role"] = r["role"]
            elif playing and not r["alive"]:
                # revealed on elimination, to everyone including that player
                # (design §2.3); an alive caller's own role is never included
                p["role"] = r["role"]
        players.append(p)

    words = _pair_words(conn, room) if (playing or finished) else None
    my_word = None
    if words and me["role"] in words:
        my_word = words[me["role"]].get(me["lang"])

    messages = []
    for m in conn.execute(
        "SELECT m.*, t.text AS tr FROM messages m LEFT JOIN translations t"
        " ON t.message_id = m.id AND t.target_lang = ?"
        " WHERE m.room_id=? AND m.game_no=? ORDER BY m.id",
        (me["lang"], room_id, room["game_no"]),
    ):
        messages.append({
            "id": m["id"], "round": m["round"], "stage": m["stage"], "seat": m["seat"],
            "kind": m["kind"], "text": m["text"], "lang": m["lang"],
            "translation": m["tr"] if m["lang"] != me["lang"] else None,
            "created_at": m["created_at"],
        })

    last_seq = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM events WHERE room_id=?", (room_id,)).fetchone()[0]

    snap: Dict[str, Any] = {
        "code": room["code"],
        "status": status,
        "phase": room["phase"],
        "phase_deadline": room["phase_deadline"],
        "round": room["round"],
        "game_no": room["game_no"],
        "version": room["version"],
        "main_lang": room["main_lang"],
        "config": json.loads(room["config_json"] or "{}"),
        "host_seat": host_seat,
        "players": players,
        "messages": messages,
        "current_speaker": _current_speaker(conn, room, rows),
        "me": {
            "seat": me["seat"],
            "is_host": me["player_id"] == room["host_player_id"],
            "my_word": my_word,
        },
        "winner": room["winner"] if finished else None,
        "last_seq": last_seq,
        "server_time": int(time.time() * 1000),
    }
    if finished and words:
        snap["words"] = words
    return snap
