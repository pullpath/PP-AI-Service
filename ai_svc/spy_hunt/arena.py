"""Arena: a bot-only match played on paper (no room state, timers or transactions).

Reuses the pure rules in `engine` and the bot prompts in `bots`/`rules`. The only
side effect is the model-call budget counter `llm.call_json` keeps on `room_id`.
Each bot sees the same firewalled view shape as `bots._public_view`: its own word,
never a role and never another seat's word."""
from __future__ import annotations

import datetime
import json
import logging
import random
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import bots, custombots, engine, game, llm, outfits, rules, store, words
from .config import BOT_NAMES, BOT_PERSONA_KEYS, LANGS, GameConfig
from .db import get_conn

log = logging.getLogger("spy_hunt.arena")

MAX_FALLBACK_SHARE = 1 / 3
ARENA_SEATS = 5
ARENA_MATCHES_PER_DAY = 20
ARENA_ACTIVE_DAYS = 14
ARENA_KEEP_DAYS = 14
ENTRY_MAX_FALLBACK_SHARE = 0.5


@dataclass
class ArenaSeat:
    name: str
    bot_id: Optional[str]
    avatar: Optional[dict]
    outfit: Optional[dict]
    persona_key: Optional[str]


class _Match:
    def __init__(self, room_id: str, pair: game.Pair, lang: str, seats: List[ArenaSeat],
                 rng: random.Random):
        gc = GameConfig()
        self.room_id, self.lang, self.seats, self.rng = room_id, lang, seats, rng
        self.max_rounds = gc.max_rounds(5, 1)
        self.max_chars = gc.statement_max_chars
        self.roles = engine.assign_roles(len(seats), 1, rng)
        words = pair.words[lang]
        civ, spy = ("a", "b") if rng.randint(0, 1) else ("b", "a")
        self.words = {"civilian": words[civ], "spy": words[spy]}
        self.alive = [True] * len(seats)
        self.statements: List[Dict[str, Any]] = []
        self.reveals: List[Dict[str, Any]] = []
        self.actions = [0] * len(seats)
        self.fallbacks = [0] * len(seats)

    def word(self, seat: int) -> str:
        return self.words[self.roles[seat]]

    def alive_seats(self) -> List[int]:
        return [i for i, a in enumerate(self.alive) if a]

    def view(self, seat: int, rnd: int, phase: str, persona: bots.BotProfile) -> Dict[str, Any]:
        return {
            "my_seat": seat,
            "max_rounds": self.max_rounds,
            "my_word": self.word(seat),
            "persona": persona.style,
            "alive_seats": self.alive_seats(),
            "players": [{"seat": i, "name": s.name, "alive": self.alive[i], "is_bot": True}
                        for i, s in enumerate(self.seats)],
            "statements": [dict(s) for s in self.statements],
            "reveal_history": [dict(r) for r in self.reveals],
            "round": rnd,
            "phase": phase,
            "status": "playing",
        }

    def persona(self, seat: int, extra=()) -> bots.BotProfile:
        s = self.seats[seat]
        if s.outfit is not None:
            try:
                return bots.compile_outfit(s.outfit, extra)
            except (TypeError, ValueError):
                return bots.PERSONAS["cheerful"]
        return bots.PERSONAS.get(s.persona_key or "") or bots.PERSONAS["cheerful"]

    def rules_of(self, seat: int) -> List[Dict[str, str]]:
        outfit = self.seats[seat].outfit
        if outfit is None:
            return []
        try:
            return outfits.clean_rules(outfit.get("rules"))
        except (TypeError, ValueError, AttributeError):
            return []

    def describe(self, seat: int, rnd: int, stage: int) -> str:
        phase = "tiebreak_describe" if stage else "describe"
        persona = self.persona(seat)
        view = self.view(seat, rnd, phase, persona)
        if self.seats[seat].outfit is not None:
            lines = rules.statement_lines(self.rules_of(seat), rules.context(view))
            if lines:
                persona = self.persona(seat, lines)
        prompt = bots._prompt_describe(view, persona, self.lang)
        text: Optional[str] = None
        try:
            out = llm.call_json("bot", prompt, bots._StatementOut, self.room_id,
                                bots.STATEMENT_MAX_TOKENS, llm.TASK_TIMEOUTS["bot"])
            text = game._clean_text(out.statement, self.max_chars)
        except Exception:
            log.info("arena describe fallback room_id=%s seat=%s", self.room_id, seat)
        self.actions[seat] += 1
        if (not text or len(text) > self.max_chars
                or engine.contains_own_word(text, {self.lang: self.word(seat)})):
            self.fallbacks[seat] += 1
            text = bots._canned_statement(self.lang)
        self.statements.append({"seat": seat, "name": self.seats[seat].name, "round": rnd,
                                "stage": stage, "text": text})
        return text

    def vote(self, seat: int, rnd: int, stage: int, targets: List[int]) -> Optional[int]:
        phase = "revote" if stage else "vote"
        valid = [t for t in targets if t != seat]
        persona = self.persona(seat)
        view = self.view(seat, rnd, phase, persona)
        self.actions[seat] += 1
        if self.seats[seat].outfit is not None:
            pick = rules.vote_pick(self.rules_of(seat), rules.context(view), valid, self.rng)
            if pick is not None:
                return pick
        prompt = bots._prompt_vote(view, persona, valid)
        try:
            out = llm.call_json("bot", prompt, bots._VoteOut, self.room_id,
                                bots.VOTE_MAX_TOKENS, llm.TASK_TIMEOUTS["bot"])
            target = out.vote_for
            if target is None or (isinstance(target, int) and target in valid):
                return target
        except Exception:
            log.info("arena vote fallback room_id=%s seat=%s", self.room_id, seat)
        self.fallbacks[seat] += 1
        return self.rng.choice(valid) if valid else None


def play_match(room_id: str, pair: game.Pair, lang: str, seats: List[ArenaSeat],
               rng: random.Random) -> Optional[dict]:
    m = _Match(room_id, pair, lang, seats, rng)
    rounds: List[Dict[str, Any]] = []
    out_round: Dict[int, int] = {}
    winner: Optional[str] = None
    rnd = 0
    while winner is None:
        rnd += 1
        entry: Dict[str, Any] = {"round": rnd, "statements": [], "votes": [], "eliminated": None}
        rounds.append(entry)
        tied: Optional[List[int]] = None
        for stage in (0, 1):
            alive = m.alive_seats()
            spoken: set = set()
            while True:
                s = engine.next_speaker(alive, set(alive), spoken, tied)
                if s is None:
                    break
                spoken.add(s)
                entry["statements"].append({"seat": s, "stage": stage,
                                            "text": m.describe(s, rnd, stage)})
            targets = engine.eligible_targets(alive, stage, tied)
            votes: Dict[int, Optional[int]] = {}
            for v in engine.eligible_voters(alive, stage, tied):
                votes[v] = m.vote(v, rnd, stage, targets)
                entry["votes"].append({"voter": v, "target": votes[v], "stage": stage})
            res = engine.resolve_vote(votes, stage, alive, tied)
            m.reveals.append({"round": rnd, "stage": stage, "outcome": res.outcome,
                              "eliminated": res.eliminated, "tied": res.tied,
                              "votes": [{"voter": v, "target": t}
                                        for v, t in sorted(votes.items())]})
            if res.eliminated is not None:
                m.alive[res.eliminated] = False
                out_round[res.eliminated] = rnd
                entry["eliminated"] = res.eliminated
            if res.outcome != "tiebreak":
                break
            tied = res.tied
        winner = engine.check_win(
            [{"seat": i, "role": m.roles[i], "alive": m.alive[i]} for i in range(len(seats))],
            rnd, m.max_rounds)

    if sum(m.fallbacks) > sum(m.actions) * MAX_FALLBACK_SHARE:
        return None

    accused: Dict[int, int] = {}
    for r in rounds:
        for v in r["votes"]:
            if v["target"] is not None:
                accused[v["target"]] = accused.get(v["target"], 0) + 1
    entries = []
    for i, s in enumerate(seats):
        if not s.bot_id:
            continue
        role = m.roles[i]
        entries.append({
            "seat": i, "bot_id": s.bot_id, "role": role,
            "won": (role == engine.SPY) == (winner == "spies"),
            "accused": accused.get(i, 0),
            "out_round": out_round.get(i),
            "quote": next((st["text"] for st in m.statements if st["seat"] == i), None),
            "fallback_share": m.fallbacks[i] / m.actions[i] if m.actions[i] else 0.0,
        })
    return {
        "log": {
            "players": [{"seat": i, "name": s.name, "avatar": s.avatar, "bot_id": s.bot_id,
                         "role": m.roles[i]} for i, s in enumerate(seats)],
            "rounds": rounds,
            "words": dict(m.words),
            "winner": winner,
        },
        "entries": entries,
    }


def eligible_bots(conn: sqlite3.Connection, day: str, now_ms: int) -> List[sqlite3.Row]:
    cutoff = now_ms - ARENA_ACTIVE_DAYS * 86_400_000
    return list(conn.execute(
        "SELECT * FROM custom_bots WHERE COALESCE(arena, 1) != 0 AND COALESCE(blocked, 0) = 0"
        " AND COALESCE(last_active, created_at) >= ?"
        " AND id NOT IN (SELECT bot_id FROM arena_entries WHERE day=?) ORDER BY id",
        (cutoff, day)))


def make_groups(bots_: list, matches: int, rng: random.Random) -> List[list]:
    pool = list(bots_)
    rng.shuffle(pool)
    groups = [pool[i:i + ARENA_SEATS] for i in range(0, len(pool), ARENA_SEATS)]
    return groups[:max(matches, 0)]


def build_seats(group: list, rng: random.Random) -> List[ArenaSeat]:
    seats = [ArenaSeat(r["name"], r["id"], {"emoji": r["avatar_emoji"], "color": r["avatar_color"]},
                       {"voice": r["voice"], "style": r["style"], "quirk": r["quirk"],
                        "rules": custombots.stored_rules(r)}, None) for r in group]
    taken = {s.name for s in seats}
    names = [n for n in BOT_NAMES if n not in taken]
    rng.shuffle(names)
    for n in names[:ARENA_SEATS - len(seats)]:
        seats.append(ArenaSeat(n, None, None, None, rng.choice(BOT_PERSONA_KEYS)))
    rng.shuffle(seats)
    return seats


def store_match(conn: sqlite3.Connection, day: str, lang: str, pair_id: str, result: dict) -> str:
    match_id = secrets.token_urlsafe(6)
    now = int(time.time() * 1000)
    with custombots._tx():
        conn.execute("INSERT INTO arena_matches(id, day, lang, pair_id, log_json, created_at)"
                     " VALUES(?,?,?,?,?,?)",
                     (match_id, day, lang, pair_id, json.dumps(result["log"], ensure_ascii=False), now))
        for e in result["entries"]:
            if e["fallback_share"] >= ENTRY_MAX_FALLBACK_SHARE:
                continue
            spy = e["role"] == engine.SPY
            won = bool(e["won"])
            cur = conn.execute(
                "UPDATE custom_bots SET arena_games=COALESCE(arena_games,0)+1,"
                " arena_wins=COALESCE(arena_wins,0)+?, arena_spy_games=COALESCE(arena_spy_games,0)+?,"
                " arena_spy_wins=COALESCE(arena_spy_wins,0)+? WHERE id=?",
                (int(won), int(spy), int(spy and won), e["bot_id"]))
            if cur.rowcount == 0:
                continue
            conn.execute("INSERT INTO arena_entries(match_id, bot_id, day, role, won, accused, out_round)"
                         " VALUES(?,?,?,?,?,?,?)",
                         (match_id, e["bot_id"], day, e["role"], int(won), e["accused"], e["out_round"]))
    return match_id


def prune(conn: sqlite3.Connection, today: str) -> int:
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=ARENA_KEEP_DAYS)).isoformat()
    with custombots._tx():
        ids = [r[0] for r in conn.execute("SELECT id FROM arena_matches WHERE day < ?", (cutoff,))]
        for i in ids:
            conn.execute("DELETE FROM arena_entries WHERE match_id=?", (i,))
            conn.execute("DELETE FROM arena_matches WHERE id=?", (i,))
    return len(ids)


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def run_night(matches: int = ARENA_MATCHES_PER_DAY, rng: Optional[random.Random] = None,
              log=print, today: Optional[str] = None, dry_run: bool = False) -> Dict[str, int]:
    rng = rng or random.Random()
    today = today or _utc_today()
    conn = get_conn()
    eligible = eligible_bots(conn, today, int(time.time() * 1000))
    result = {"played": 0, "discarded": 0, "skipped": 0}
    if not eligible:
        log("no eligible bots")
        return result
    groups = make_groups(eligible, matches, rng)
    placed = sum(len(g) for g in groups)
    if dry_run:
        for i, g in enumerate(groups):
            log(f"match {i + 1} ({LANGS[i % 2]}): {', '.join(r['name'] for r in g)}")
        result["skipped"] = len(eligible) - placed
        log(f"dry run: {len(groups)} matches planned, {result['skipped']} bots left out")
        return result
    room_id = store.create_room("arena", "builder", "en")["id"]
    matched = 0
    streak = 0
    for i, group in enumerate(groups):
        pool = list(conn.execute("SELECT * FROM pairs WHERE active=1"))
        if not pool:
            log("no active pairs")
            break
        pair = words._row_to_pair(rng.choice(pool))
        lang = LANGS[i % 2]
        conn.execute("UPDATE rooms SET ai_calls=0 WHERE id=?", (room_id,))
        conn.commit()
        res = play_match(room_id, pair, lang, build_seats(group, rng), rng)
        if res is None:
            result["discarded"] += 1
            log(f"match {i + 1} ({lang}, {pair.id}): discarded")
            streak += 1
            if streak >= 2:
                log("model down, stopping")
                break
            continue
        streak = 0
        try:
            store_match(conn, today, lang, pair.id, res)
        except sqlite3.IntegrityError:
            result["discarded"] += 1
            log(f"match {i + 1} ({lang}, {pair.id}): not stored")
            continue
        result["played"] += 1
        matched += len(group)
        log(f"match {i + 1} ({lang}, {pair.id}): {res['log']['winner']} won")
    result["skipped"] = len(eligible) - matched
    prune(conn, today)
    log(f"played {result['played']}, discarded {result['discarded']}, skipped {result['skipped']}")
    return result


def _quote(log: Dict[str, Any], bot_id: str) -> Optional[str]:
    seat = next((p["seat"] for p in log.get("players", []) if p.get("bot_id") == bot_id), None)
    if seat is None:
        return None
    for r in log.get("rounds", []):
        for st in r.get("statements", []):
            if st.get("seat") == seat:
                return st.get("text")
    return None


def recaps_for(owner: str, limit: int = 10) -> Dict[str, Any]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT e.match_id, e.bot_id, e.day, e.role, e.won, e.accused, e.out_round, e.seen,"
        " b.name, b.avatar_emoji, b.avatar_color, m.lang, m.log_json"
        " FROM arena_entries e JOIN custom_bots b ON b.id=e.bot_id"
        " JOIN arena_matches m ON m.id=e.match_id WHERE b.owner_player_id=?"
        " ORDER BY m.created_at DESC, e.match_id DESC LIMIT ?", (owner, limit)).fetchall()
    unseen = conn.execute(
        "SELECT COUNT(*) FROM arena_entries e JOIN custom_bots b ON b.id=e.bot_id"
        " WHERE b.owner_player_id=? AND COALESCE(e.seen,0)=0", (owner,)).fetchone()[0]
    return {"recaps": [{
        "match_id": r["match_id"], "bot_id": r["bot_id"], "bot_name": r["name"],
        "avatar": {"emoji": r["avatar_emoji"], "color": r["avatar_color"]},
        "day": r["day"], "lang": r["lang"], "role": r["role"], "won": bool(r["won"]),
        "accused": r["accused"], "out_round": r["out_round"],
        "quote": _quote(json.loads(r["log_json"]), r["bot_id"]), "seen": bool(r["seen"]),
    } for r in rows], "unseen": unseen}


def mark_seen(owner: str) -> None:
    conn = get_conn()
    with custombots._tx():
        conn.execute("UPDATE arena_entries SET seen=1 WHERE bot_id IN"
                     " (SELECT id FROM custom_bots WHERE owner_player_id=?)", (owner,))


def match_view(match_id: str) -> Optional[Dict[str, Any]]:
    row = get_conn().execute("SELECT id, day, lang, log_json FROM arena_matches WHERE id=?",
                             (match_id,)).fetchone()
    if row is None:
        return None
    log_ = json.loads(row["log_json"])
    return {
        "id": row["id"], "day": row["day"], "lang": row["lang"],
        "players": [{"seat": p["seat"], "name": p["name"], "avatar": p["avatar"],
                     "bot_id": p["bot_id"], "role": p["role"], "is_custom": p["bot_id"] is not None}
                    for p in log_["players"]],
        "rounds": log_["rounds"], "words": log_["words"], "winner": log_["winner"],
    }
