"""Durable per-game history snapshots, written once when a game finishes."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Mapping, Optional


def record_game(conn, room: Mapping, rows: List[Mapping], winner: Optional[str],
                words: dict, parts: Dict[str, list]) -> None:
    roles = [{"seat": r["seat"], "role": r["role"], "is_bot": bool(r["is_bot"]), "name": r["name"]}
             for r in rows]
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT OR IGNORE INTO room_results(room_id, game_no, finished_at, winner, lang,"
        " roles_json, words_json) VALUES (?,?,?,?,?,?,?)",
        (room["id"], room["game_no"], now, winner, room["main_lang"],
         json.dumps(roles), json.dumps(words)))
    for r in rows:
        if r["is_bot"]:
            continue
        mine = parts.get(r["player_id"], [])
        won = (r["role"] == "spy") == (winner == "spies")
        conn.execute(
            "INSERT OR IGNORE INTO room_result_players(room_id, game_no, player_id, seat, role,"
            " won, credits_earned, credit_parts) VALUES (?,?,?,?,?,?,?,?)",
            (room["id"], room["game_no"], r["player_id"], r["seat"], r["role"], int(won),
             sum(p["n"] for p in mine), json.dumps(mine)))


def games_for(player_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    from ai_svc.spy_hunt.db import get_conn
    rows = get_conn().execute(
        "SELECT p.room_id, p.game_no, p.role, p.won, p.credits_earned, r.finished_at, r.winner"
        " FROM room_result_players p JOIN room_results r"
        " ON r.room_id=p.room_id AND r.game_no=p.game_no"
        " WHERE p.player_id=? ORDER BY r.finished_at DESC, p.rowid DESC LIMIT ?",
        (player_id, limit)).fetchall()
    return [{"room_id": r["room_id"], "game_no": r["game_no"], "finished_at": r["finished_at"],
             "winner": r["winner"], "your_role": r["role"], "won": bool(r["won"]),
             "credits_earned": r["credits_earned"]} for r in rows]


def game_detail(player_id: str, room_id: str, game_no: int) -> Optional[Dict[str, Any]]:
    from ai_svc.spy_hunt.db import get_conn
    conn = get_conn()
    if conn.execute("SELECT 1 FROM room_result_players WHERE room_id=? AND game_no=? AND player_id=?",
                    (room_id, game_no, player_id)).fetchone() is None:
        return None
    res = conn.execute("SELECT * FROM room_results WHERE room_id=? AND game_no=?",
                       (room_id, game_no)).fetchone()
    if res is None:
        return None
    humans = {r["seat"]: r for r in conn.execute(
        "SELECT seat, player_id, credits_earned, credit_parts FROM room_result_players"
        " WHERE room_id=? AND game_no=?", (room_id, game_no)).fetchall()}
    roles = []
    for entry in json.loads(res["roles_json"]):
        out = dict(entry)
        h = humans.get(entry["seat"])
        out["is_you"] = bool(h and h["player_id"] == player_id)
        if h is not None:
            out["credits_earned"] = h["credits_earned"]
            out["credit_parts"] = json.loads(h["credit_parts"] or "[]")
        roles.append(out)
    return {"finished_at": res["finished_at"], "winner": res["winner"], "lang": res["lang"],
            "words": json.loads(res["words_json"] or "null") or {}, "roles": roles}
