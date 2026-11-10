"""Rule cards: pure evaluation of a bot's `when`/`do` rules over `bots.public_view`.
No DB, no model. Sentences name players by seat number only (names are untrusted)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import outfits

MAX_LINES = 3
_DESCRIBE = ("describe", "tiebreak_describe")
_STAGE1 = ("tiebreak_describe", "revote")

_COPY = "Stay as close as possible in meaning to the previous speaker's clue."
_VAGUE = "Make this clue vaguer and safer than usual, naming no distinguishing detail."


@dataclass(frozen=True)
class RuleContext:
    seat: int
    stage: int
    describing: bool
    accusers: Tuple[int, ...]
    leader: Optional[int]
    spoken_in_stage: int
    others_all_spoken: bool
    eliminated: bool
    late_game: bool


def _list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _dicts(v: Any) -> List[Dict[str, Any]]:
    return [x for x in _list(v) if isinstance(x, dict)]


def context(view: Dict[str, Any]) -> RuleContext:
    view = view if isinstance(view, dict) else {}
    seat = view.get("my_seat")
    phase = view.get("phase")
    rnd = view.get("round")
    stage = 1 if phase in _STAGE1 else 0
    describing = phase in _DESCRIBE

    history = _dicts(view.get("reveal_history"))
    latest = history[-1] if history else {}
    votes = [v for v in _dicts(latest.get("votes")) if isinstance(v.get("target"), int)]
    accusers = tuple(sorted({v["voter"] for v in votes
                             if v["target"] == seat and isinstance(v.get("voter"), int)}))
    counts: Dict[int, int] = {}
    for v in votes:
        counts[v["target"]] = counts.get(v["target"], 0) + 1
    top = max(counts.values()) if counts else 0
    tops = [s for s, c in counts.items() if c == top]
    leader = tops[0] if len(tops) == 1 else None

    stmts = [s for s in _dicts(view.get("statements")) if s.get("round") == rnd]
    spoken = sum(1 for s in stmts if s.get("stage") == stage)
    spoke0 = {s.get("seat") for s in stmts if s.get("stage") == 0}
    alive = [s for s in _list(view.get("alive_seats")) if s != seat]
    max_rounds = view.get("max_rounds")
    return RuleContext(
        seat=seat, stage=stage, describing=describing, accusers=accusers, leader=leader,
        spoken_in_stage=spoken,
        others_all_spoken=describing and stage == 0 and all(s in spoke0 for s in alive),
        eliminated=any(h.get("eliminated") is not None for h in history),
        late_game=(isinstance(max_rounds, int) and isinstance(rnd, int)
                   and rnd >= max_rounds - 1),
    )


def holds(when: str, ctx: RuleContext) -> bool:
    if when == "accused":
        return bool(ctx.accusers)
    if when == "first_to_speak":
        return ctx.describing and ctx.spoken_in_stage == 0
    if when == "last_to_speak":
        return ctx.describing and ctx.stage == 0 and ctx.others_all_spoken
    if when == "after_elimination":
        return ctx.eliminated
    if when == "late_game":
        return ctx.late_game
    return False


def _sentence(do: str, ctx: RuleContext) -> Optional[str]:
    if do == "counter_accuse":
        if not ctx.accusers:
            return None
        return (f"The players at seats {list(ctx.accusers)} voted for you last round. "
                "Voice suspicion toward them in the language of the statement, "
                "without revealing your word.")
    if do == "copy_previous":
        return _COPY if ctx.spoken_in_stage > 0 else None
    if do == "go_vague":
        return _VAGUE
    return None


def statement_lines(rules: List[Dict[str, str]], ctx: RuleContext) -> List[str]:
    lines: List[str] = []
    for r in rules:
        if r.get("do") not in outfits.STATEMENT_ACTIONS or not holds(r.get("when"), ctx):
            continue
        s = _sentence(r["do"], ctx)
        if s:
            lines.append(s)
        if len(lines) == MAX_LINES:
            break
    return lines


def vote_pick(rules: List[Dict[str, str]], ctx: RuleContext, valid_targets: List[int],
              rng) -> Optional[int]:
    for r in rules:
        if r.get("do") not in outfits.VOTE_ACTIONS or not holds(r.get("when"), ctx):
            continue
        if r["do"] == "vote_accuser":
            cands = [s for s in ctx.accusers if s in valid_targets and s != ctx.seat]
            if cands:
                return rng.choice(cands)
        elif (ctx.leader is not None and ctx.leader != ctx.seat
              and ctx.leader in valid_targets):
            return ctx.leader
    return None
