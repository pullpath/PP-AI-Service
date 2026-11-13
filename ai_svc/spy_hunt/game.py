"""Game flow: start, statements, votes, phase advance, leave, rematch.

Every mutation runs under `store.tx(room_id)` (room lock + BEGIN IMMEDIATE),
bumps `rooms.version`, and appends its events in the same transaction.
`phase_seq` bumps ONLY on a phase or speaker change; timers (Task 6) key on it
through `on_phase_change` and call `advance_phase(room_id, expected_phase_seq)`.
No model or network calls happen here.

Reading `players.role` / pair words here is game logic, not client payload
building: nothing in this module puts a secret on an `all` audience except the
public `reveal`/`game_over` events that visibility.check_event_payload allows.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import random
import secrets
import unicodedata
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from ai_svc.spy_hunt import custombots, engine, store, visibility
from ai_svc.spy_hunt.config import BOT_NAMES, BOT_PERSONA_KEYS, GameConfig
from ai_svc.spy_hunt.store import StoreError, append_event, now_ms

log = logging.getLogger(__name__)

REVEAL_SECONDS = 8
DESCRIBE_PHASES = ("describe", "tiebreak_describe")
VOTE_PHASES = ("vote", "revote")

_rng = random.SystemRandom()


class Pair(NamedTuple):
    id: str
    words: Dict[str, Dict[str, str]]  # {"en": {"a","b"}, "zh-Hans": {"a","b"}}


_FIXTURE_PAIR = Pair("fixture-lighthouse-windmill", {
    "en": {"a": "lighthouse", "b": "windmill"},
    "zh-Hans": {"a": "灯塔", "b": "风车"},
})

_pair_source: Optional[Callable[[str], Pair]] = None
_phase_hook: Optional[Callable[[str, int, Optional[int]], None]] = None
_bots_hook: Optional[Callable[[str], None]] = None


def set_pair_source(fn: Optional[Callable[[str], Pair]]) -> None:
    """Inject `fn(room_id) -> Pair` (tests, Task 12). None restores the fixture pair."""
    global _pair_source
    _pair_source = fn


_pair_prepare: Optional[Callable[[str], None]] = None


def set_pair_prepare(fn: Optional[Callable[[str], None]]) -> None:
    """Hook run by start_game BEFORE its transaction (model calls are not allowed
    inside one): lets the word pool generate a pair if none is fresh."""
    global _pair_prepare
    _pair_prepare = fn


def set_on_phase_change(fn: Optional[Callable[[str, int, Optional[int]], None]]) -> None:
    global _phase_hook
    _phase_hook = fn


def on_phase_change(room_id: str, phase_seq: int, deadline: Optional[int]) -> None:
    """Hook for Task 6 timers. Called after commit; default no-op."""
    if _phase_hook is not None:
        _phase_hook(room_id, phase_seq, deadline)


def set_on_bots_due(fn: Optional[Callable[[str], None]]) -> None:
    """Second post-commit hook, alongside (never instead of) on_phase_change:
    Task 10 (bots) uses this to learn "a phase or speaker just changed" and
    decide whose turn is now a bot's. Default no-op."""
    global _bots_hook
    _bots_hook = fn


def on_bots_due(room_id: str) -> None:
    if _bots_hook is not None:
        _bots_hook(room_id)


def speaker_words(room_id: str, seat: Optional[int]) -> Dict[str, str]:
    """The seat's own role word in every supported language, {lang: word}.

    SERVER-SIDE COMPARISON ONLY (translation must withhold a translation that
    contains the speaker's own word). Never put the result in a client payload.
    Same source as submit_statement: visibility._pair_words."""
    if seat is None:
        return {}
    from ai_svc.spy_hunt.db import get_conn
    conn = get_conn()
    room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    me = conn.execute("SELECT role FROM players WHERE room_id=? AND seat=?",
                      (room_id, seat)).fetchone()
    if room is None or me is None:
        return {}
    words = visibility._pair_words(conn, room) or {}
    return {k: v for k, v in (words.get(me["role"]) or {}).items() if v}


_message_hook: Optional[Callable[[int], None]] = None


def set_on_message(fn: Optional[Callable[[int], None]]) -> None:
    global _message_hook
    _message_hook = fn


def _notify_message(message_id: int) -> None:
    """Post-commit hook for new chat messages (translation, Task 9). Default no-op."""
    if _message_hook is not None:
        try:
            _message_hook(message_id)
        except Exception:  # must never fail the player's request
            log.exception("on_message hook failed")


_host_hook: Optional[Callable[[str, str], None]] = None


def set_on_host_moment(fn: Optional[Callable[[str, str], None]]) -> None:
    """Post-commit hook for host narration (Task 11), fired at three public
    moments: round start, after an elimination reveal, and at game over. A
    SEPARATE hook, never instead of on_phase_change / on_bots_due / on_message.
    Default no-op; narration is cosmetic and must never affect game state."""
    global _host_hook
    _host_hook = fn


def _notify_host(moments: List[tuple]) -> None:
    """Fire the host-moment hook once per queued (room_id, moment), after commit.
    Fire-and-forget: a failure here must never fail a player's request, the
    timer thread, or the game flow."""
    if _host_hook is None:
        return
    for room_id, moment in moments:
        try:
            _host_hook(room_id, moment)
        except Exception:  # host narration is cosmetic: never break game flow
            log.exception("on_host_moment hook failed")


def _notify(pend: List[tuple]) -> None:
    if not pend:
        return
    room_id, seq, deadline = pend[-1]
    try:
        on_phase_change(room_id, seq, deadline)
    except Exception:  # a scheduler bug must not fail the player's request
        log.exception("on_phase_change failed")
    try:
        on_bots_due(room_id)
    except Exception:  # same: bots must never block or fail the player's request
        log.exception("on_bots_due failed")


# ---- small helpers ----

def _room(conn, room_id: str):
    row = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    if row is None:
        raise StoreError(404, "not_found", "No such room.")
    return row


def _players(conn, room_id: str):
    return conn.execute("SELECT * FROM players WHERE room_id=? ORDER BY seat", (room_id,)).fetchall()


def _gc(cfg: Dict[str, Any]) -> GameConfig:
    names = {f.name for f in dataclasses.fields(GameConfig)}
    return GameConfig(**{k: v for k, v in cfg.items() if k in names})


def _alive(rows) -> List[int]:
    return [r["seat"] for r in rows if r["alive"]]


def _public_all(rows, host_id: Optional[str]) -> List[Dict[str, Any]]:
    badges = visibility.clan_badges(r["player_id"] for r in rows if not r["is_bot"])
    ranks = visibility.credit_ranks(r["player_id"] for r in rows if not r["is_bot"])
    return [visibility.public_player(r, host_id, badges, ranks) for r in rows]


def _public(conn, room_id: str, host_id: Optional[str], seat: int) -> Dict[str, Any]:
    return visibility.public_player(store._player_row(conn, room_id, seat), host_id)


def _stage(room) -> int:
    return 1 if room["phase"] in visibility.STAGE1_PHASES else 0


def _tied(conn, room, alive: List[int]) -> List[int]:
    votes = _votes(conn, room, 0)
    return engine.resolve_vote(votes, 0, alive, None).tied


def _votes(conn, room, stage: int) -> Dict[int, Optional[int]]:
    return {r["voter_seat"]: r["target_seat"] for r in conn.execute(
        "SELECT voter_seat, target_seat FROM votes WHERE room_id=? AND game_no=? AND round=?"
        " AND stage=?", (room["id"], room["game_no"], room["round"], stage))}


def _msg_dict(row) -> Dict[str, Any]:
    return {"id": row["id"], "round": row["round"], "stage": row["stage"], "seat": row["seat"],
            "kind": row["kind"], "text": row["text"], "lang": row["lang"],
            "created_at": row["created_at"]}


def _set_phase(conn, room_id: str, pend: List[tuple], phase: Optional[str],
               deadline: Optional[int], rnd: Optional[int] = None) -> int:
    conn.execute(
        "UPDATE rooms SET phase=?, phase_deadline=?, phase_seq=phase_seq+1,"
        " round=COALESCE(?, round) WHERE id=?", (phase, deadline, rnd, room_id))
    seq = conn.execute("SELECT phase_seq FROM rooms WHERE id=?", (room_id,)).fetchone()[0]
    pend.append((room_id, seq, deadline))
    return seq


def _enter_describe(conn, room_id: str, pend: List[tuple], phase: str, rnd: int) -> None:
    """Enter (or step within) a describe phase and announce the speaker."""
    room = _room(conn, room_id)
    gc = _gc(json.loads(room["config_json"]))
    deadline = now_ms() + gc.turn_seconds * 1000
    seq = _set_phase(conn, room_id, pend, phase, deadline, rnd)
    room = _room(conn, room_id)
    speaker = visibility._current_speaker(conn, room, _players(conn, room_id))
    append_event(room_id, "turn", {
        "seat": speaker, "phase": phase, "stage": _stage(room), "round": room["round"],
        "phase_seq": seq, "deadline": deadline}, "all", conn=conn)


def _enter_vote(conn, room_id: str, pend: List[tuple], phase: str) -> None:
    room = _room(conn, room_id)
    gc = _gc(json.loads(room["config_json"]))
    deadline = now_ms() + gc.vote_seconds * 1000
    seq = _set_phase(conn, room_id, pend, phase, deadline)
    append_event(room_id, "phase", {
        "phase": phase, "stage": _stage(_room(conn, room_id)), "round": room["round"],
        "phase_seq": seq, "deadline": deadline}, "all", conn=conn)


def _after_describe_step(conn, room_id: str, pend: List[tuple]) -> None:
    room = _room(conn, room_id)
    speaker = visibility._current_speaker(conn, room, _players(conn, room_id))
    if speaker is None:
        _enter_vote(conn, room_id, pend, "vote" if room["phase"] == "describe" else "revote")
    else:
        _enter_describe(conn, room_id, pend, room["phase"], room["round"])


def _finish(conn, room_id: str, pend: List[tuple], winner: Optional[str],
            moments: List[tuple]) -> None:
    room = _room(conn, room_id)
    rows = _players(conn, room_id)
    words = visibility._pair_words(conn, room)
    conn.execute("UPDATE rooms SET status='finished', winner=? WHERE id=?", (winner, room_id))
    _set_phase(conn, room_id, pend, None, None)
    from ai_svc.spy_hunt import custombots
    custombots.record_game(conn, rows, winner)
    from ai_svc.spy_hunt import clans, credits
    clans.award_game(conn, room_id, room["game_no"], rows, winner)
    parts = credits.award_game_parts(conn, room_id, room["game_no"], rows, winner)
    seat_of = {r["player_id"]: r["seat"] for r in rows}
    parts = {seat_of[pid]: p for pid, p in parts.items() if pid in seat_of}
    deltas = {seat: sum(x["n"] for x in p) for seat, p in parts.items()}
    append_event(room_id, "game_over", {
        "winner": winner, "round": room["round"],
        "roles": [{"seat": r["seat"], "role": r["role"]} for r in rows],
        "words": words, "credits": deltas, "credit_parts": parts}, "all", conn=conn)
    if room["pair_id"]:
        from ai_svc.spy_hunt import words as words_mod
        words_mod.record_outcome(room["pair_id"], winner == "spies", conn)
    moments.append((room_id, "game_over"))


# ---- bots ----

def _insert_bot(conn, room, lang: Optional[str] = None, custom=None, owner: Optional[str] = None) -> int:
    rid = room["id"]
    cfg = json.loads(room["config_json"])
    rows = _players(conn, rid)
    if len(rows) >= cfg["max_players"]:
        raise StoreError(409, "room_full", "The room is full.")
    used_seats = {r["seat"] for r in rows}
    used_names = {r["name"] for r in rows}
    seat = next(i for i in range(len(rows) + 1) if i not in used_seats)
    if custom is not None:
        name, persona = custom["name"], "custom"
        extra = (custom["avatar_emoji"], custom["avatar_color"], custom["id"], owner,
                 json.dumps({"voice": custom["voice"], "style": custom["style"],
                             "quirk": custom["quirk"],
                              "rules": custombots.stored_rules(custom)}))
    else:
        free = [n for n in BOT_NAMES if n not in used_names]
        name = _rng.choice(free) if free else f"Bot{seat}"
        persona, extra = _rng.choice(BOT_PERSONA_KEYS), (None,) * 5
    conn.execute(
        "INSERT INTO players(room_id, player_id, seat, name, lang, is_bot, bot_persona,"
        " alive, connected, joined_at, avatar_emoji, avatar_color, bot_id, bot_owner_id,"
        " outfit_json) VALUES(?,?,?,?,?,1,?,1,1,?,?,?,?,?,?)",
        (rid, "bot-" + secrets.token_hex(6), seat, name, lang or room["main_lang"],
         persona, now_ms(), *extra))
    store._emit_player(conn, dict(room), seat, "player_joined")
    return seat


def add_bot(room_id: str, by_player: str, bot_id: Optional[str] = None) -> None:
    with store.tx(room_id) as conn:
        if bot_id is None:
            room = _lobby_host_check(conn, room_id, by_player)
            _insert_bot(conn, room)
        else:
            room = _room(conn, room_id)
            if store.seat_of(room_id, by_player, conn) is None:
                raise StoreError(403, "not_member", "You are not in this room.")
            if room["status"] != "lobby":
                raise StoreError(409, "not_lobby", "Only possible in the lobby.")
            custom = custombots.get_owned(conn, by_player, bot_id)
            if custom is None:
                raise StoreError(404, "not_found", "No such bot.")
            if conn.execute("SELECT 1 FROM players WHERE room_id=? AND bot_owner_id=?",
                            (room_id, by_player)).fetchone():
                raise StoreError(409, "bot_in_room", "You already have a bot in this room.")
            _insert_bot(conn, room, custom=custom, owner=by_player)
        store._bump(conn, room_id)


def remove_bot(room_id: str, by_player: str, seat: Optional[int] = None) -> None:
    with store.tx(room_id) as conn:
        if seat is None:
            room = _lobby_host_check(conn, room_id, by_player)
            bots = [r for r in _players(conn, room_id) if r["is_bot"]]
            if not bots:
                raise StoreError(409, "no_bots", "There are no bots to remove.")
            seat = bots[-1]["seat"]
        else:
            if not isinstance(seat, int) or isinstance(seat, bool):
                raise StoreError(400, "bad_request", "seat must be an integer.")
            room = _room(conn, room_id)
            if store.seat_of(room_id, by_player, conn) is None:
                raise StoreError(403, "not_member", "You are not in this room.")
            if room["status"] != "lobby":
                raise StoreError(409, "not_lobby", "Only possible in the lobby.")
            row = conn.execute("SELECT * FROM players WHERE room_id=? AND seat=? AND is_bot=1",
                               (room_id, seat)).fetchone()
            if row is None:
                raise StoreError(404, "not_found", "No such bot.")
            if room["host_player_id"] != by_player and row["bot_owner_id"] != by_player:
                raise StoreError(403, "not_allowed", "You cannot remove that bot.")
        player = _public(conn, room_id, room["host_player_id"], seat)
        conn.execute("DELETE FROM players WHERE room_id=? AND seat=?", (room_id, seat))
        store._bump(conn, room_id)
        append_event(room_id, "player_left", {"player": player}, "all", conn=conn)


def _lobby_host_check(conn, room_id: str, by_player: str):
    room = _room(conn, room_id)
    if room["host_player_id"] != by_player:
        raise StoreError(403, "not_host", "Only the host can do that.")
    if room["status"] != "lobby":
        raise StoreError(409, "not_lobby", "Only possible in the lobby.")
    return room


# ---- start ----

def start_game(room_id: str, by_player: str) -> None:
    pend: List[tuple] = []
    moments: List[tuple] = []
    if _pair_prepare is not None:
        try:
            _pair_prepare(room_id)
        except Exception:
            log.exception("pair prepare failed")
    with store.tx(room_id) as conn:
        room = _lobby_host_check(conn, room_id, by_player)
        cfg = json.loads(room["config_json"])
        gc = _gc(cfg)
        n = len(_players(conn, room_id))
        if n < gc.min_players:
            if not cfg.get("bot_fill", True):
                raise StoreError(409, "need_players",
                                 f"At least {gc.min_players} players are needed.")
            for _ in range(gc.min_players - n):
                _insert_bot(conn, room)
        rows = _players(conn, room_id)
        n = len(rows)

        # compact seats to 0..n-1 and shuffle the speaking order once
        perm = list(range(n))
        _rng.shuffle(perm)
        for new, r in zip(perm, rows):
            conn.execute("UPDATE players SET seat=? WHERE room_id=? AND seat=?",
                         (1000 + new, room_id, r["seat"]))
        conn.execute("UPDATE players SET seat=seat-1000 WHERE room_id=?", (room_id,))

        spies = gc.spy_count(n)
        roles = engine.assign_roles(n, spies, _rng)
        for seat, role in enumerate(roles):
            conn.execute("UPDATE players SET role=?, alive=1 WHERE room_id=? AND seat=?",
                         (role, room_id, seat))

        pair = (_pair_source or (lambda _rid: _FIXTURE_PAIR))(room_id)
        civ_is_a = _rng.randint(0, 1)
        en = pair.words.get("en", {})
        conn.execute(
            "INSERT OR IGNORE INTO pairs(id, concept_a, concept_b, difficulty, theme,"
            " words_json, active, plays, spy_wins) VALUES(?,?,?,?,?,?,1,0,0)",
            (pair.id, en.get("a"), en.get("b"), 1, None,
             json.dumps(pair.words, ensure_ascii=False)))
        cfg.update({"spy_count": spies, "players": n,
                    "max_rounds": gc.max_rounds(n, spies)})
        conn.execute(
            "UPDATE rooms SET status='playing', round=1, pair_id=?, civ_is_a=?, winner=?,"
            " config_json=? WHERE id=?",
            (pair.id, civ_is_a, None, json.dumps(cfg), room_id))
        store._bump(conn, room_id)

        room = _room(conn, room_id)
        words = visibility._pair_words(conn, room)
        rows = _players(conn, room_id)
        append_event(room_id, "roster", {
            "players": _public_all(rows, room["host_player_id"])},
            "all", conn=conn)
        for r in rows:
            append_event(room_id, "game_started", {
                "seat": r["seat"], "game_no": room["game_no"],
                "my_word": words[r["role"]][r["lang"]]}, f"seat:{r['seat']}", conn=conn)
        _enter_describe(conn, room_id, pend, "describe", 1)
        moments.append((room_id, "round_start"))
    _notify(pend)
    _notify_host(moments)


# ---- statements ----

def _clean_text(text: Any, max_chars: int) -> str:
    if not isinstance(text, str):
        raise StoreError(400, "bad_text", "Statement must be text.")
    if len(text) > max_chars * 4:
        raise StoreError(400, "too_long", f"At most {max_chars} characters.")
    t = "".join(" " if ch in "\n\r\t" else ch for ch in text)
    # ZWJ is kept so emoji families render; the own-word check normalises it away.
    t = "".join(ch for ch in t if ch == "\u200d" or not unicodedata.category(ch).startswith("C"))
    t = " ".join(t.split())
    if not t:
        raise StoreError(400, "empty_text", "Say something.")
    if len(t) > max_chars:
        raise StoreError(400, "too_long", f"At most {max_chars} characters.")
    return t


def submit_statement(room_id: str, player_id: str, text: Any) -> None:
    pend: List[tuple] = []
    with store.tx(room_id) as conn:
        room = _room(conn, room_id)
        me = conn.execute("SELECT * FROM players WHERE room_id=? AND player_id=?",
                          (room_id, player_id)).fetchone()
        if me is None:
            raise StoreError(403, "not_member", "You are not in this room.")
        if room["status"] != "playing" or room["phase"] not in DESCRIBE_PHASES:
            raise StoreError(409, "wrong_phase", "Not a describe phase.")
        if not me["alive"]:
            raise StoreError(403, "eliminated", "You have been eliminated.")
        speaker = visibility._current_speaker(conn, room, _players(conn, room_id))
        if speaker != me["seat"]:
            raise StoreError(409, "not_your_turn", "It is not your turn.")
        cfg = json.loads(room["config_json"])
        text = _clean_text(text, _gc(cfg).statement_max_chars)
        words = (visibility._pair_words(conn, room) or {}).get(me["role"], {})
        if engine.contains_own_word(text, words):
            raise StoreError(400, "own_word", "Your statement contains your own secret word.")
        cur = conn.execute(
            "INSERT INTO messages(room_id, game_no, round, stage, seat, kind, text, lang,"
            " created_at) VALUES(?,?,?,?,?,'statement',?,?,?)",
            (room_id, room["game_no"], room["round"], _stage(room), me["seat"], text,
             me["lang"], now_ms()))
        store._bump(conn, room_id)
        msg = conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
        append_event(room_id, "statement", {"message": _msg_dict(msg)}, "all", conn=conn)
        message_id = msg["id"]
        _after_describe_step(conn, room_id, pend)
    _notify(pend)
    _notify_message(message_id)


# ---- votes ----

def _check_target_type(t: Any) -> None:
    if t is not None and (isinstance(t, bool) or not isinstance(t, int)):
        raise StoreError(400, "bad_target", "target_seat must be a seat number or null.")


def submit_vote(room_id: str, player_id: str, target_seat: Any) -> None:
    _check_target_type(target_seat)
    pend: List[tuple] = []
    moments: List[tuple] = []
    with store.tx(room_id) as conn:
        room = _room(conn, room_id)
        me = conn.execute("SELECT * FROM players WHERE room_id=? AND player_id=?",
                          (room_id, player_id)).fetchone()
        if me is None:
            raise StoreError(403, "not_member", "You are not in this room.")
        if room["status"] != "playing" or room["phase"] not in VOTE_PHASES:
            raise StoreError(409, "wrong_phase", "Not a voting phase.")
        if not me["alive"]:
            raise StoreError(403, "eliminated", "You have been eliminated.")
        stage = _stage(room)
        alive = _alive(_players(conn, room_id))
        tied = _tied(conn, room, alive) if stage == 1 else None
        seat = me["seat"]
        if seat not in engine.eligible_voters(alive, stage, tied):
            raise StoreError(403, "cannot_vote", "You cannot vote in this stage.")
        if seat in _votes(conn, room, stage):
            raise StoreError(409, "already_voted", "You have already voted.")
        if target_seat is not None:
            if target_seat == seat:
                raise StoreError(400, "self_vote", "You cannot vote for yourself.")
            if target_seat not in engine.eligible_targets(alive, stage, tied):
                raise StoreError(400, "bad_target", "That seat cannot be voted for.")
        conn.execute(
            "INSERT INTO votes(room_id, game_no, round, stage, voter_seat, target_seat)"
            " VALUES(?,?,?,?,?,?)",
            (room_id, room["game_no"], room["round"], stage, seat, target_seat))
        store._bump(conn, room_id)
        append_event(room_id, "vote_locked",
                     {"seat": seat, "round": room["round"], "stage": stage}, "all", conn=conn)
        voters = set(engine.eligible_voters(alive, stage, tied))
        if voters <= set(_votes(conn, room, stage)):
            _resolve_vote(conn, room_id, pend, moments)
    _notify(pend)
    _notify_host(moments)


def _resolve_vote(conn, room_id: str, pend: List[tuple], moments: List[tuple]) -> None:
    room = _room(conn, room_id)
    stage = _stage(room)
    rows = _players(conn, room_id)
    alive = _alive(rows)
    tied = _tied(conn, room, alive) if stage == 1 else None
    votes = _votes(conn, room, stage)
    res = engine.resolve_vote(votes, stage, alive, tied)
    payload: Dict[str, Any] = {
        "round": room["round"], "stage": stage, "outcome": res.outcome,
        "eliminated": res.eliminated, "tied": res.tied,
        "votes": [{"voter": v, "target": t} for v, t in sorted(votes.items())]}
    if res.eliminated is not None:
        payload["role"] = next(r["role"] for r in rows if r["seat"] == res.eliminated)
        conn.execute("UPDATE players SET alive=0 WHERE room_id=? AND seat=?",
                     (room_id, res.eliminated))
    store._bump(conn, room_id)
    append_event(room_id, "reveal", payload, "all", conn=conn)
    if res.outcome == "tiebreak":
        _enter_describe(conn, room_id, pend, "tiebreak_describe", room["round"])
        return
    seats = [{"seat": r["seat"], "role": r["role"],
              "alive": bool(r["alive"]) and r["seat"] != res.eliminated} for r in rows]
    cfg = json.loads(room["config_json"])
    winner = engine.check_win(seats, room["round"], cfg["max_rounds"])
    if winner:
        _finish(conn, room_id, pend, winner, moments)  # game_over narrates the final elimination
        return
    if res.eliminated is not None:
        moments.append((room_id, "elimination"))
    deadline = now_ms() + REVEAL_SECONDS * 1000
    seq = _set_phase(conn, room_id, pend, "reveal", deadline)
    append_event(room_id, "phase", {"phase": "reveal", "stage": stage, "round": room["round"],
                                    "phase_seq": seq, "deadline": deadline}, "all", conn=conn)


# ---- timers ----

def advance_phase(room_id: str, expected_phase_seq: int) -> bool:
    """The single function timers call. Acts only if `phase_seq` still matches;
    otherwise (stale or duplicate fire) returns False with no effect."""
    pend: List[tuple] = []
    moments: List[tuple] = []
    with store.tx(room_id) as conn:
        row = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if row is None or row["status"] != "playing" or row["phase_seq"] != expected_phase_seq:
            return False
        room = row
        if room["phase"] in DESCRIBE_PHASES:
            speaker = visibility._current_speaker(conn, room, _players(conn, room_id))
            if speaker is not None:
                lang = conn.execute("SELECT lang FROM players WHERE room_id=? AND seat=?",
                                    (room_id, speaker)).fetchone()["lang"]
                cur = conn.execute(
                    "INSERT INTO messages(room_id, game_no, round, stage, seat, kind, text,"
                    " lang, created_at) VALUES(?,?,?,?,?,'skipped',NULL,?,?)",
                    (room_id, room["game_no"], room["round"], _stage(room), speaker, lang,
                     now_ms()))
                msg = conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
                append_event(room_id, "statement", {"message": _msg_dict(msg)}, "all", conn=conn)
            store._bump(conn, room_id)
            _after_describe_step(conn, room_id, pend)
        elif room["phase"] in VOTE_PHASES:
            _resolve_vote(conn, room_id, pend, moments)
        elif room["phase"] == "reveal":
            store._bump(conn, room_id)
            _enter_describe(conn, room_id, pend, "describe", room["round"] + 1)
            moments.append((room_id, "round_start"))
        else:
            return False
    _notify(pend)
    _notify_host(moments)
    return True


# ---- leave ----

def leave(room_id: str, player_id: str) -> None:
    pend: List[tuple] = []
    with store.tx(room_id) as conn:
        room = _room(conn, room_id)
        seat = store.seat_of(room_id, player_id, conn)
        if seat is None:
            raise StoreError(403, "not_member", "You are not in this room.")
        if room["status"] == "playing":
            conn.execute(
                "UPDATE players SET player_id=?, is_bot=1, bot_persona=?, connected=1"
                " WHERE room_id=? AND seat=?",
                ("bot-" + secrets.token_hex(6), _rng.choice(BOT_PERSONA_KEYS), room_id, seat))
            player = _public(conn, room_id, None, seat)
        else:
            player = _public(conn, room_id, None, seat)
            conn.execute("DELETE FROM players WHERE room_id=? AND seat=?", (room_id, seat))
        store._bump(conn, room_id)
        append_event(room_id, "player_left", {"player": player}, "all", conn=conn)
        if room["status"] != "playing":
            for bseat in [r["seat"] for r in conn.execute(
                    "SELECT seat FROM players WHERE room_id=? AND bot_owner_id=?",
                    (room_id, player_id)).fetchall()]:
                bplayer = _public(conn, room_id, None, bseat)
                conn.execute("DELETE FROM players WHERE room_id=? AND seat=?", (room_id, bseat))
                append_event(room_id, "player_left", {"player": bplayer}, "all", conn=conn)

        humans = conn.execute(
            "SELECT * FROM players WHERE room_id=? AND is_bot=0 ORDER BY joined_at, rowid",
            (room_id,)).fetchall()
        if not humans:
            if room["status"] != "finished":
                conn.execute("UPDATE rooms SET status='finished', winner=NULL WHERE id=?",
                             (room_id,))
                _set_phase(conn, room_id, pend, None, None)
                append_event(room_id, "closed", {"reason": "no_humans"}, "all", conn=conn)
        elif room["host_player_id"] == player_id:
            new_host = humans[0]
            conn.execute("UPDATE rooms SET host_player_id=? WHERE id=?",
                         (new_host["player_id"], room_id))
            store._emit_player(conn, dict(_room(conn, room_id)), new_host["seat"],
                               "player_updated")
    _notify(pend)


# ---- rematch ----

def rematch(room_id: str, by_player: str) -> None:
    pend: List[tuple] = []
    with store.tx(room_id) as conn:
        room = _room(conn, room_id)
        if room["host_player_id"] != by_player:
            raise StoreError(403, "not_host", "Only the host can start a rematch.")
        if room["status"] != "finished":
            raise StoreError(409, "not_finished", "The game is not over.")
        conn.execute(
            "DELETE FROM players WHERE room_id=? AND bot_owner_id IS NOT NULL"
            " AND bot_owner_id NOT IN"
            " (SELECT player_id FROM players WHERE room_id=? AND is_bot=0)",
            (room_id, room_id))
        conn.execute("UPDATE players SET role=NULL, alive=1 WHERE room_id=?", (room_id,))
        conn.execute(
            "UPDATE rooms SET status='lobby', round=0, game_no=game_no+1, pair_id=NULL,"
            " civ_is_a=NULL, winner=NULL WHERE id=?", (room_id,))
        _set_phase(conn, room_id, pend, None, None)
        store._bump(conn, room_id)
        room = _room(conn, room_id)
        append_event(room_id, "rematch", {
            "game_no": room["game_no"],
            "players": _public_all(_players(conn, room_id), room["host_player_id"])},
            "all", conn=conn)
    _notify(pend)
