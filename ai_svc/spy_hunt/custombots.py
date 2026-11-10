"""Custom bots owned by guests: CRUD and the public card."""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from . import outfits
from .db import get_conn
from .store import StoreError, clean_name

MAX_BOTS = 3


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


def _record(row: sqlite3.Row) -> Dict[str, int]:
    return {k: row[k] or 0 for k in ("games", "wins", "spy_games", "spy_wins")}


def stored_rules(row: sqlite3.Row) -> List[Dict[str, str]]:
    try:
        return outfits.clean_rules(json.loads(row["rules_json"]))
    except (TypeError, ValueError):
        return []


def _card(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    credit = None
    if row["remix_of"]:
        src = conn.execute("SELECT id, name FROM custom_bots WHERE id=? AND blocked=0",
                           (row["remix_of"],)).fetchone()
        if src:
            credit = {"id": src["id"], "name": src["name"]}
    remixes = conn.execute("SELECT COUNT(*) FROM remixes WHERE source_id=?", (row["id"],)).fetchone()[0]
    return {
        "id": row["id"], "name": row["name"],
        "avatar": {"emoji": row["avatar_emoji"], "color": row["avatar_color"]},
        "outfit": {"voice": row["voice"], "style": row["style"], "quirk": row["quirk"],
                   "rules": stored_rules(row)},
        "record": _record(row),
        "remix_of": credit, "remixes": remixes, "remixable": not row["blocked"],
        "ranked": {k: row[f"ranked_{k}"] or 0 for k in ("games", "wins", "spy_games", "spy_wins")},
        "listed": bool(row["listed"] if row["listed"] is not None else 1),
    }


def get_owned(conn: sqlite3.Connection, owner: str, bot_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM custom_bots WHERE id=? AND owner_player_id=?",
                        (bot_id, owner)).fetchone()


def _check_listed(v: Any) -> bool:
    if not isinstance(v, bool):
        raise StoreError(400, "bad_request", "listed must be true or false.")
    return v


def create(owner: str, name: Any, avatar: Any, outfit: Any, remix_of: Any = None,
           listed: Any = True) -> Dict[str, Any]:
    if remix_of is not None and not isinstance(remix_of, str):
        raise StoreError(400, "bad_request", "remix_of must be a bot id.")
    listed = _check_listed(listed)
    name = clean_name(name)
    av = outfits.check_avatar(avatar)
    out = outfits.check_outfit(outfit)
    with _tx() as c:
        n = c.execute("SELECT COUNT(*) FROM custom_bots WHERE owner_player_id=?", (owner,)).fetchone()[0]
        if n >= MAX_BOTS:
            raise StoreError(409, "bot_limit", f"You can have at most {MAX_BOTS} bots.")
        credit = None
        if remix_of is not None:
            src = c.execute("SELECT id, owner_player_id FROM custom_bots WHERE id=? AND blocked=0",
                            (remix_of,)).fetchone()
            if src is None:
                raise StoreError(404, "not_found", "No such bot.")
            if src["owner_player_id"] != owner:
                credit = src["id"]
        while True:
            bot_id = secrets.token_urlsafe(6)
            if not c.execute("SELECT 1 FROM custom_bots WHERE id=?", (bot_id,)).fetchone():
                break
        c.execute(
            "INSERT INTO custom_bots(id, owner_player_id, name, avatar_emoji, avatar_color,"
            " voice, style, quirk, created_at, rules_json, listed, remix_of)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (bot_id, owner, name, av["emoji"], av["color"], out["voice"], out["style"],
             out["quirk"], int(time.time() * 1000), json.dumps(out["rules"]), int(listed), credit))
        if credit:
            c.execute("INSERT OR IGNORE INTO remixes(source_id, owner_player_id) VALUES(?,?)",
                      (credit, owner))
        return _card(c, c.execute("SELECT * FROM custom_bots WHERE id=?", (bot_id,)).fetchone())


def list_for(owner: str) -> List[Dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM custom_bots WHERE owner_player_id=? ORDER BY created_at, rowid", (owner,)).fetchall()
    conn = get_conn()
    return [_card(conn, r) for r in rows]


def update(owner: str, bot_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if not any(k in body for k in ("name", "avatar", "outfit", "listed")):
        raise StoreError(400, "bad_request", "Nothing to update.")
    sets: Dict[str, Any] = {}
    if "listed" in body:
        sets["listed"] = int(_check_listed(body["listed"]))
    if "name" in body:
        sets["name"] = clean_name(body["name"])
    if "avatar" in body:
        av = outfits.check_avatar(body["avatar"])
        sets["avatar_emoji"], sets["avatar_color"] = av["emoji"], av["color"]
    if "outfit" in body:
        out = outfits.check_outfit(body["outfit"])
        rules = out.pop("rules")
        sets.update(out)
        sets["rules_json"] = json.dumps(rules)
    with _tx() as c:
        if get_owned(c, owner, bot_id) is None:
            raise StoreError(404, "not_found", "No such bot.")
        cols = ", ".join(f"{k}=?" for k in sets)
        c.execute(f"UPDATE custom_bots SET {cols} WHERE id=?", (*sets.values(), bot_id))
        return _card(c, c.execute("SELECT * FROM custom_bots WHERE id=?", (bot_id,)).fetchone())


def delete(owner: str, bot_id: str) -> None:
    with _tx() as c:
        if c.execute("DELETE FROM custom_bots WHERE id=? AND owner_player_id=?",
                     (bot_id, owner)).rowcount == 0:
            raise StoreError(404, "not_found", "No such bot.")


def get_card(bot_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM custom_bots WHERE id=?", (bot_id,)).fetchone()
    return _card(conn, row) if row else None


def record_game(conn: sqlite3.Connection, rows, winner: Optional[str]) -> None:
    if winner is None:
        return
    for r in rows:
        if not r["bot_id"]:
            continue
        spy = r["role"] == "spy"
        won = (spy and winner == "spies") or (r["role"] == "civilian" and winner == "civilians")
        conn.execute(
            "UPDATE custom_bots SET games = games + 1, wins = wins + ?, spy_games = spy_games + ?,"
            " spy_wins = spy_wins + ? WHERE id=?",
            (int(won), int(spy), int(spy and won), r["bot_id"]))
