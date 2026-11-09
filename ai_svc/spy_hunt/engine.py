"""Pure game rules for spy-hunt. No I/O, no DB, no Flask."""
from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any, Dict, List, NamedTuple, Optional

Seat = Dict[str, Any]  # {"seat": int, "role": str, "alive": bool}

SPY = "spy"
CIVILIAN = "civilian"


class VoteResult(NamedTuple):
    eliminated: Optional[int]
    tied: List[int]
    outcome: str  # eliminated | tiebreak | nobody


def assign_roles(n_seats: int, spies: int, rng) -> List[str]:
    spy_seats = set(rng.sample(range(n_seats), spies))
    return [SPY if i in spy_seats else CIVILIAN for i in range(n_seats)]


def check_win(seats: List[Seat], round: int, max_rounds: int) -> Optional[str]:
    alive = [s for s in seats if s["alive"]]
    spies = sum(1 for s in alive if s["role"] == SPY)
    civilians = len(alive) - spies
    if spies == 0:
        return "civilians"
    if spies >= civilians:
        return "spies"
    if round >= max_rounds:
        return "spies"
    return None


def eligible_voters(alive: List[int], stage: int, tied: Optional[List[int]]) -> List[int]:
    if stage >= 1 and tied:
        return [a for a in alive if a not in tied]
    return list(alive)


def eligible_targets(alive: List[int], stage: int, tied: Optional[List[int]]) -> List[int]:
    if stage >= 1 and tied:
        return [a for a in alive if a in tied]
    return list(alive)


def resolve_vote(
    votes: Dict[int, Optional[int]],
    stage: int,
    alive: List[int],
    tied: Optional[List[int]],
) -> VoteResult:
    voters = set(eligible_voters(alive, stage, tied))
    targets = set(eligible_targets(alive, stage, tied))
    counts = Counter(
        t for v, t in votes.items()
        if t is not None and v in voters and t in targets and t != v
    )
    if not counts:
        return VoteResult(None, [], "nobody")
    top = max(counts.values())
    leaders = sorted(t for t, c in counts.items() if c == top)
    if len(leaders) == 1:
        return VoteResult(leaders[0], [], "eliminated")
    if stage == 0 and set(leaders) != set(alive):
        return VoteResult(None, leaders, "tiebreak")
    return VoteResult(None, [], "nobody")


def _norm(text: str) -> str:
    """Comparison form: NFKC, drop ALL format (Cf) chars (ZWJ/ZWNJ/ZWSP, word
    joiner, soft hyphen, bidi controls, BOM) and variation selectors, casefold.
    Used only for comparing; never stored or displayed."""
    t = unicodedata.normalize("NFKC", text or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Cf"
                and not (0xFE00 <= ord(c) <= 0xFE0F or 0xE0100 <= ord(c) <= 0xE01EF))
    return t.casefold()


def contains_own_word(text: str, words: Dict[str, str]) -> bool:
    """Case-insensitive substring test on normalised text (see _norm); the
    secret words are normalised the same way."""
    low = _norm(text)
    for w in words.values():
        w = _norm((w or "").strip())
        if w and w in low:
            return True
    return False


def next_speaker(
    order: List[int],
    alive: set,
    spoken: set,
    tied: Optional[List[int]],
) -> Optional[int]:
    for s in order:
        if s not in alive or s in spoken:
            continue
        if tied and s not in tied:
            continue
        return s
    return None
