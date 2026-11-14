"""Durable per-game history snapshots, written once when a game finishes."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Mapping, Optional

from ai_svc.spy_hunt import engine


def build_replay_log(conn, room: Mapping, rows: List[Mapping], words: dict,
                     winner: Optional[str]) -> dict:
    room_id, game_no = room["id"], room["game_no"]
    msg_rows = conn.execute(
        "SELECT * FROM messages WHERE room_id=? AND game_no=? ORDER BY round, stage, id",
        (room_id, game_no)).fetchall()
    vote_rows = conn.execute(
        "SELECT * FROM votes WHERE room_id=? AND game_no=? ORDER BY round, stage, voter_seat",
        (room_id, game_no)).fetchall()

    translations_by_message: Dict[int, Dict[str, str]] = {}
    for m in msg_rows:
        trs = conn.execute(
            "SELECT target_lang, text FROM translations WHERE message_id=?", (m["id"],)).fetchall()
        if trs:
            translations_by_message[m["id"]] = {t["target_lang"]: t["text"] for t in trs}

    round_numbers = sorted({m["round"] for m in msg_rows} | {v["round"] for v in vote_rows})
    alive = {r["seat"] for r in rows}
    rounds = []
    for rnd in round_numbers:
        statements = [{
            "seat": m["seat"], "stage": m["stage"], "kind": m["kind"], "text": m["text"],
            "lang": m["lang"], "translations": translations_by_message.get(m["id"], {}),
        } for m in msg_rows if m["round"] == rnd]
        round_votes = [v for v in vote_rows if v["round"] == rnd]
        votes = [{"voter": v["voter_seat"], "target": v["target_seat"], "stage": v["stage"]}
                 for v in round_votes]

        votes0 = {v["voter_seat"]: v["target_seat"] for v in round_votes if v["stage"] == 0}
        res0 = engine.resolve_vote(votes0, 0, sorted(alive), None)
        if res0.outcome == "tiebreak":
            votes1 = {v["voter_seat"]: v["target_seat"] for v in round_votes if v["stage"] == 1}
            res1 = engine.resolve_vote(votes1, 1, sorted(alive), res0.tied)
            eliminated = res1.eliminated
        else:
            eliminated = res0.eliminated
        if eliminated is not None:
            alive.discard(eliminated)

        rounds.append({"round": rnd, "statements": statements, "votes": votes,
                       "eliminated": eliminated})

    return {
        "players": [{"seat": r["seat"], "name": r["name"], "is_bot": bool(r["is_bot"]),
                    "role": r["role"]} for r in rows],
        "rounds": rounds,
        "words": words,
        "winner": winner,
    }


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
        won = None if winner is None else int((r["role"] == "spy") == (winner == "spies"))
        conn.execute(
            "INSERT OR IGNORE INTO room_result_players(room_id, game_no, player_id, seat, role,"
            " won, credits_earned, credit_parts) VALUES (?,?,?,?,?,?,?,?)",
            (room["id"], room["game_no"], r["player_id"], r["seat"], r["role"], won,
             sum(p["n"] for p in mine), json.dumps(mine)))
    log = build_replay_log(conn, room, rows, words, winner)
    conn.execute(
        "INSERT OR IGNORE INTO room_replays(room_id, game_no, log_json, created_at) VALUES (?,?,?,?)",
        (room["id"], room["game_no"], json.dumps(log), now))


def games_for(player_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    from ai_svc.spy_hunt.db import get_conn
    rows = get_conn().execute(
        "SELECT p.room_id, p.game_no, p.role, p.won, p.credits_earned, r.finished_at, r.winner"
        " FROM room_result_players p JOIN room_results r"
        " ON r.room_id=p.room_id AND r.game_no=p.game_no"
        " WHERE p.player_id=? ORDER BY r.finished_at DESC, p.rowid DESC LIMIT ?",
        (player_id, limit)).fetchall()
    return [{"room_id": r["room_id"], "game_no": r["game_no"], "finished_at": r["finished_at"],
             "winner": r["winner"], "your_role": r["role"], "won": None if r["won"] is None else bool(r["won"]),
             "credits_earned": r["credits_earned"]} for r in rows]


def game_detail(player_id: str, room_id: str, game_no: int) -> Optional[Dict[str, Any]]:
    from ai_svc.spy_hunt.db import get_conn
    conn = get_conn()
    if not 0 <= game_no <= 2**62:
        return None
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
