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
