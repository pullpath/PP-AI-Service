"""Arena: a bot-only match played on paper (no room state, timers or transactions).

Reuses the pure rules in `engine` and the bot prompts in `bots`/`rules`. The only
side effect is the model-call budget counter `llm.call_json` keeps on `room_id`.
Each bot sees the same firewalled view shape as `bots._public_view`: its own word,
never a role and never another seat's word."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import bots, engine, game, llm, outfits, rules
from .config import GameConfig

log = logging.getLogger("spy_hunt.arena")

MAX_FALLBACK_SHARE = 1 / 3


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
            text = " ".join(out.statement.split())
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
