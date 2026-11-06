from __future__ import annotations

import dataclasses

import pytest

from ai_svc.spy_hunt.config import GameConfig, LANGS


def test_spy_count():
    c = GameConfig()
    assert c.spy_count(7) == 1
    assert c.spy_count(8) == 2


def test_max_rounds():
    c = GameConfig()
    assert c.max_rounds(4, 1) == 4
    assert c.max_rounds(6, 1) == 6
    assert c.max_rounds(10, 2) == 8


def test_defaults_and_frozen():
    c = GameConfig()
    assert (c.min_players, c.max_players, c.turn_seconds, c.vote_seconds) == (4, 10, 45, 30)
    assert LANGS == ("en", "zh-Hans")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.min_players = 3
