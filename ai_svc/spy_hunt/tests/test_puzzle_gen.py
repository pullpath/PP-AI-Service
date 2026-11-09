from __future__ import annotations

import json
import random
import re

import pytest

from ai_svc.spy_hunt import fake_llm, game, puzzle_gen, store
from ai_svc.spy_hunt.llm import LlmError

PAIR = game.Pair("p-t", {"en": {"a": "piano", "b": "organ"}, "zh-Hans": {"a": "钢琴", "b": "风琴"}})
SECRETS = ("piano", "organ", "钢琴", "风琴")


@pytest.fixture
def room(temp_db):
    return store.create_room("builder", "builder", "en")["id"]


def my_word(prompt):
    return re.search(r"is: (.*)\n", prompt).group(1)


def register_clean(prompts=None, translations=None):
    n = {"i": 0}

    def statement(prompt):
        if prompts is not None:
            prompts.append(prompt)
        n["i"] += 1
        return {"statement": f"clue {n['i'] - 1}"}

    fake_llm.register("puzzle_statement", statement)
    fake_llm.register("puzzle_translate",
                      lambda p: {"translations": translations or [f"线索{i}" for i in range(10)]})


def build(room, origin="en", seed=1):
    return puzzle_gen.build_candidate(room, PAIR, origin, random.Random(seed))


def test_candidate_has_five_players_ten_statements_in_speaking_order(room):
    register_clean()
    c = build(room)
    st = c["public"]["statements"]
    assert [m["seat"] for m in st] == [0, 1, 2, 3, 4] * 2
    assert [m["round"] for m in st] == [1] * 5 + [2] * 5
    assert [m["id"] for m in st] == list(range(1, 11))
    assert [p["seat"] for p in c["public"]["players"]] == [0, 1, 2, 3, 4]
    assert len({p["name"] for p in c["public"]["players"]}) == 5


def test_spy_word_given_only_to_the_spy(room):
    prompts = []
    register_clean(prompts)
    c = build(room)
    spy, spy_word, civ_word = (c["answer"]["spy_seat"], c["answer"]["spy_word"]["en"],
                               c["answer"]["civilian_word"]["en"])
    assert {spy_word, civ_word} == {"piano", "organ"}
    for i, p in enumerate(prompts):
        expected = spy_word if i % 5 == spy else civ_word
        assert my_word(p) == expected


def test_round_two_prompts_include_earlier_statements(room):
    prompts = []
    register_clean(prompts)
    build(room)
    assert "clue 0" not in prompts[0] and "clue 0" in prompts[5]


def test_statement_naming_a_secret_word_is_retried_then_rejected(room):
    calls = {"n": 0}

    def leaky_once(prompt):
        calls["n"] += 1
        return {"statement": "I love piano" if calls["n"] == 1 else f"clean {calls['n']}"}

    fake_llm.register("puzzle_statement", leaky_once)
    fake_llm.register("puzzle_translate", lambda p: {"translations": [f"线索{i}" for i in range(10)]})
    c = build(room)
    assert c is not None and all("piano" not in m["text"] for m in c["public"]["statements"])
    fake_llm.register("puzzle_statement", lambda p: {"statement": "a PIANO sound"})
    assert build(room) is None


def test_llm_error_rejects_candidate(room):
    def boom(prompt):
        raise LlmError("down")

    fake_llm.register("puzzle_statement", boom)
    assert build(room) is None


def test_translation_wrong_length_rejects(room):
    register_clean(translations=[f"t{i}" for i in range(9)])
    assert build(room) is None


def test_translation_naming_a_secret_word_rejects(room):
    register_clean(translations=["线索"] * 9 + ["这是钢琴"])
    assert build(room) is None


def test_translation_goes_into_the_other_language(room):
    register_clean(translations=[f"line {i}" for i in range(10)])
    c = build(room, origin="zh-Hans")
    m = c["public"]["statements"][0]
    assert m["lang"] == "zh-Hans" and m["translations"] == {"en": "line 0"}
    assert c["public"]["origin_lang"] == "zh-Hans"


def test_candidate_public_has_no_answer_keys(room):
    register_clean()
    c = build(room)
    text = json.dumps(c["public"], ensure_ascii=False)
    assert "spy_seat" not in text and "spy_word" not in text
    assert c["public"]["options"] == [] and c["answer"]["option_index"] is None
