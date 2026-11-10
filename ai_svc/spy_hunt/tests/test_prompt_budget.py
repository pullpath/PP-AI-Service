from __future__ import annotations

import json

from ai_svc.spy_hunt import bots, prompts

TEXT = "It is the sort of thing you keep close by the door and shake dry afterwards, honestly."
NAMES = ["Milo", "Juno", "Pip", "Nova", "Remy", "Skye", "Otto", "Luna", "Finn", "Cleo"]


def make_view(players: int, rounds: int) -> dict:
    alive = list(range(players))
    statements, history = [], []
    for rnd in range(1, rounds + 1):
        for s in alive:
            statements.append({"seat": s, "name": NAMES[s], "round": rnd, "stage": 0, "text": TEXT})
        out = alive[-1]
        history.append({"round": rnd, "stage": 0, "outcome": "eliminated", "eliminated": out,
                        "tied": [], "votes": [{"voter": a, "target": out} for a in alive if a != out]})
        if rnd < rounds:
            alive = [a for a in alive if a != out]
    return {
        "my_seat": 0, "max_rounds": players, "my_word": "umbrella", "persona": "Dry and understated. " * 15,
        "alive_seats": alive,
        "players": [{"seat": i, "name": NAMES[i], "alive": i in alive, "is_bot": True} for i in range(players)],
        "statements": statements, "reveal_history": history, "round": rounds, "phase": "vote",
        "status": "playing",
    }


def block_json(prompt: str) -> dict:
    inner = prompt.split(prompts.DATA_OPEN, 1)[1].split(prompts.DATA_CLOSE, 1)[0]
    return json.loads(inner)


def test_long_view_is_valid_json_and_keeps_what_matters():
    view = make_view(10, 6)
    assert len(json.dumps(view)) > prompts.MAX_DATA_CHARS * 3
    for prompt in (bots._prompt_vote(view, bots.PERSONAS["dry"], [1, 2]),
                   bots._prompt_describe(view, bots.PERSONAS["dry"], "en")):
        assert "[truncated]" not in prompt
        data = block_json(prompt)
        for key in ("my_seat", "my_word", "round", "phase", "status", "alive_seats", "reveal_history", "players"):
            assert data[key] == view[key]
        kept = data["statements"]
        assert 0 < len(kept) < len(view["statements"])
        assert kept == view["statements"][-len(kept):]
        assert data["omitted_statements"] == len(view["statements"]) - len(kept)


def test_view_that_fits_is_passed_whole():
    view = make_view(5, 1)
    data = block_json(bots._prompt_vote(view, bots.PERSONAS["dry"], [1]))
    assert data == view
    assert "omitted_statements" not in data


def test_building_the_prompt_does_not_change_the_view():
    view = make_view(10, 6)
    before = json.dumps(view)
    bots._prompt_vote(view, bots.PERSONAS["dry"], [1])
    bots._prompt_describe(view, bots.PERSONAS["dry"], "en")
    assert json.dumps(view) == before


def test_round_and_phase_stay_adjacent_for_log_readers():
    prompt = bots._prompt_vote(make_view(10, 6), bots.PERSONAS["dry"], [1])
    assert '"round": 6, "phase": "vote"' in prompt


def test_view_without_statements_key_is_tolerated():
    data = block_json(bots._prompt_describe({"my_word": "x", "round": 1}, bots.PERSONAS["dry"], "en"))
    assert data == {"my_word": "x", "round": 1}


def test_data_block_limit_is_per_call():
    long = "x" * 3000
    assert "[truncated]" in prompts.data_block(long)
    assert "[truncated]" not in prompts.data_block(long, limit=5000)
    inner = prompts.data_block(long, limit=100).split(prompts.DATA_OPEN, 1)[1].split(prompts.DATA_CLOSE, 1)[0]
    assert inner.strip() == "x" * 100 + prompts.TRUNCATED
