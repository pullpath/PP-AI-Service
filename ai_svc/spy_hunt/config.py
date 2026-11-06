from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    min_players: int = 4
    max_players: int = 10
    two_spies_at: int = 8  # spy_count = 2 when players >= this
    turn_seconds: int = 45
    vote_seconds: int = 30
    statement_max_chars: int = 120
    extra_rounds: int = 2  # max_rounds = (players - 2*spies) + extra_rounds
    room_ai_budget: int = 300  # model calls per room
    room_idle_hours: int = 6

    def spy_count(self, players: int) -> int:
        return 2 if players >= self.two_spies_at else 1

    def max_rounds(self, players: int, spies: int) -> int:
        return (players - 2 * spies) + self.extra_rounds


LANGS = ("en", "zh-Hans")

BOT_PERSONA_KEYS = ("cheerful", "dry", "chatty", "terse")

BOT_NAMES = (
    "Milo", "Juno", "Pip", "Nova", "Remy", "Skye",
    "Otto", "Luna", "Finn", "Cleo", "Bram", "Wren",
)
