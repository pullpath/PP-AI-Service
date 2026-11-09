from __future__ import annotations

import json
import random
import re
import types

import pytest

from ai_svc.spy_hunt import fake_llm, game, llm, puzzle_gen, puzzles, store
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.llm import LlmError

PAIR = game.Pair("p-t", {"en": {"a": "piano", "b": "organ"}, "zh-Hans": {"a": "钢琴", "b": "风琴"}})
SECRETS = ("piano", "organ", "钢琴", "风琴")


@pytest.fixture
def room(temp_db):
    return store.create_room("builder", "builder", "en")["id"]


def my_word(prompt):
    return re.search(r"is: (.*)\n", prompt).group(1)


def clue(i, prompt):
    return f"线索{i}" if "Simplified Chinese" in prompt else f"clue {i}"


def register_clean(prompts=None, translations=None):
    n = {"i": 0}

    def statement(prompt):
        if prompts is not None:
            prompts.append(prompt)
        n["i"] += 1
        return {"statement": clue(n["i"] - 1, prompt)}

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


def test_overlong_statement_is_retried_never_cut_off(room):
    calls = {"n": 0}

    def long_once(prompt):
        calls["n"] += 1
        return {"statement": "word " * 60 if calls["n"] == 1 else f"short clue {calls['n']}"}

    fake_llm.register("puzzle_statement", long_once)
    fake_llm.register("puzzle_translate", lambda p: {"translations": [f"线索{i}" for i in range(10)]})
    c = build(room)
    assert c is not None
    assert all(m["text"].startswith("short clue") for m in c["public"]["statements"])
    fake_llm.register("puzzle_statement", lambda p: {"statement": "word " * 60})
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


def test_statement_prompt_names_the_origin_language(room):
    prompts = []
    register_clean(prompts)
    build(room, origin="zh-Hans")
    assert all("Simplified Chinese" in p for p in prompts)
    prompts.clear()
    build(room, origin="en")
    assert all("English" in p and "Simplified Chinese" not in p for p in prompts)


def test_statement_in_the_wrong_language_is_retried_then_rejected(room):
    calls = {"n": 0}

    def english_first(prompt):
        calls["n"] += 1
        return {"statement": "A warm drink for the morning" if calls["n"] == 1 else f"线索{calls['n']}"}

    fake_llm.register("puzzle_statement", english_first)
    fake_llm.register("puzzle_translate", lambda p: {"translations": [f"line {i}" for i in range(10)]})
    c = build(room, origin="zh-Hans")
    assert c is not None and all("warm drink" not in m["text"] for m in c["public"]["statements"])
    fake_llm.register("puzzle_statement", lambda p: {"statement": "A warm drink for the morning"})
    assert build(room, origin="zh-Hans") is None


def test_candidate_public_has_no_answer_keys(room):
    register_clean()
    c = build(room)
    text = json.dumps(c["public"], ensure_ascii=False)
    assert "spy_seat" not in text and "spy_word" not in text
    assert c["public"]["options"] == [] and c["answer"]["option_index"] is None


# ---- part 2: options, gate, queue ----

def add_pair(pid, en_a, en_b, theme, zh_a=None, zh_b=None):
    words = {"en": {"a": en_a, "b": en_b}, "zh-Hans": {"a": zh_a or en_a + "中", "b": zh_b or en_b + "中"}}
    get_conn().execute(
        "INSERT INTO pairs(id, concept_a, concept_b, difficulty, theme, words_json, active, plays,"
        " spy_wins) VALUES(?,?,?,?,?,?,1,0,0)",
        (pid, en_a, en_b, 1, theme, json.dumps(words, ensure_ascii=False)))
    get_conn().commit()


def only_pool(*pids):
    get_conn().execute("UPDATE pairs SET active=0")
    for pid in pids:
        get_conn().execute("UPDATE pairs SET active=1 WHERE id=?", (pid,))
    get_conn().commit()


def test_pick_options_returns_four_distinct_options_with_spy_word_at_index(temp_db):
    opts, idx = puzzle_gen.pick_options(PAIR, "b", None, random.Random(3))
    assert len(opts) == 4 and 0 <= idx < 4
    assert opts[idx] == {"en": "organ", "zh-Hans": "风琴"}
    assert len({o["en"] for o in opts}) == 4


def test_pick_options_prefers_same_theme(temp_db):
    for i in range(3):
        add_pair(f"t{i}", f"alpha{i}", f"beta{i}", "zoo")
    add_pair("o1", "other1", "other2", "misc")
    only_pool("t0", "t1", "t2", "o1")
    opts, idx = puzzle_gen.pick_options(PAIR, "b", "zoo", random.Random(1))
    others = [o["en"] for i, o in enumerate(opts) if i != idx]
    assert all(w.startswith(("alpha", "beta")) for w in others)


def test_pick_options_never_repeats_pair_words(temp_db):
    add_pair("dup", "piano", "xylophone", "music", "钢琴", "木琴")
    add_pair("dup2", "ORGAN", "tuba", "music", "管风琴", "大号")
    for i in range(3):
        add_pair(f"f{i}", f"fill{i}", f"gill{i}", "music")
    only_pool("dup", "dup2", "f0", "f1", "f2")
    for seed in range(20):
        opts, idx = puzzle_gen.pick_options(PAIR, "b", "music", random.Random(seed))
        for i, o in enumerate(opts):
            if i != idx:
                assert o["en"].lower() not in ("piano", "organ") and o["zh-Hans"] not in ("钢琴", "风琴")


def test_pick_options_raises_on_tiny_pool(temp_db):
    add_pair("only", "solo1", "solo2", "x")
    only_pool("only")
    with pytest.raises(LookupError):
        puzzle_gen.pick_options(PAIR, "a", None, random.Random(1))


def register_world(full_conf=80, r1_conf=50, r1_right=False, full_right=lambda cand: True,
                   solve_error=False):
    st = {"words": [], "calls": 0, "cand": 0}

    def statement(prompt):
        i = st["calls"]
        st["calls"] += 1
        if i % 10 == 0:
            st["cand"] += 1
            st["words"] = []
        if i % 10 < 5:
            st["words"].append(my_word(prompt))
        return {"statement": clue(i, prompt)}

    def solve(prompt):
        if solve_error:
            raise LlmError("down")
        w = st["words"]
        spy = next(s for s, x in enumerate(w) if w.count(x) == 1)
        full = "Round 2" in prompt
        right = full_right(st["cand"]) if full else r1_right
        return {"spy_seat": spy if right else (spy + 1) % 5,
                "confidence": full_conf if full else r1_conf}

    fake_llm.register("puzzle_statement", statement)
    fake_llm.register("puzzle_solve", solve)
    fake_llm.register("puzzle_translate", lambda p: {"translations": [f"线索{i}" for i in range(10)]})
    return st


def gen(room, seed=1):
    return puzzle_gen.generate_puzzle(room, PAIR, "en", random.Random(seed))


def test_gate_accepts_solvable_puzzle(room):
    register_world()
    out = gen(room)
    assert out["difficulty"] == 2 and out["pair_id"] == "p-t"
    assert len(out["public"]["options"]) == 4
    assert out["public"]["options"][out["answer"]["option_index"]] == out["answer"]["spy_word"]


def test_gate_rejects_wrong_solver_answer(room):
    register_world(full_right=lambda cand: False)
    assert gen(room) is None


def test_gate_rejects_low_confidence(room):
    register_world(full_conf=30)
    assert gen(room) is None


def test_gate_rejects_too_easy_round_one(room):
    register_world(r1_right=True, r1_conf=98)
    assert gen(room) is None


def test_gate_allows_round_one_right_but_unsure(room):
    register_world(r1_right=True, r1_conf=70)
    assert gen(room) is not None


def test_gate_rejects_when_solver_errors(room):
    register_world(solve_error=True)
    assert gen(room) is None


@pytest.mark.parametrize("conf,expected", [(85, 1), (84, 2), (60, 2), (59, 3)])
def test_difficulty_boundaries(conf, expected):
    assert puzzle_gen.difficulty_of(conf) == expected


def test_generate_retries_with_a_new_candidate(room):
    st = register_world(full_right=lambda cand: cand > 1)
    out = gen(room)
    assert out is not None and st["cand"] == 2


def test_fill_queue_inserts_until_target_and_alternates_language(temp_db):
    register_world()
    n = puzzle_gen.fill_queue(2, random.Random(1), log=lambda *a: None)
    assert n == 2 and puzzles.ready_count() == 2
    origins = [json.loads(r["public_json"])["origin_lang"]
               for r in get_conn().execute("SELECT public_json FROM puzzles ORDER BY id")]
    assert set(origins) == {"en", "zh-Hans"}


def test_fill_queue_never_publishes_a_rejected_puzzle(temp_db):
    register_world(full_right=lambda cand: False)
    assert puzzle_gen.fill_queue(1, random.Random(1), log=lambda *a: None) == 0
    assert puzzles.ready_count() == 0


def test_fill_queue_resets_budget_per_pair(temp_db, monkeypatch):
    monkeypatch.setattr(llm, "GameConfig", lambda: types.SimpleNamespace(room_ai_budget=15))
    register_world()
    assert puzzle_gen.fill_queue(3, random.Random(1), log=lambda *a: None) == 3


def test_fill_queue_does_not_reuse_pairs(temp_db):
    register_world()
    puzzle_gen.fill_queue(4, random.Random(2), log=lambda *a: None)
    ids = [r["pair_id"] for r in get_conn().execute("SELECT pair_id FROM puzzles")]
    assert len(set(ids)) == 4


# ---- model-written distractors ----

def distractors(*pairs):
    return {"options": [{"en": en, "zh_hans": zh} for en, zh in pairs]}


GOOD = (("harpsichord", "拨弦键琴"), ("accordion", "手风琴"), ("synthesizer", "合成器"))


def test_model_distractors_are_used_when_valid(room):
    register_world()
    fake_llm.register("puzzle_options", lambda p: distractors(*GOOD))
    out = gen(room)
    got = {o["en"] for o in out["public"]["options"]}
    assert got == {"harpsichord", "accordion", "synthesizer", out["answer"]["spy_word"]["en"]}
    assert {"zh-Hans": "手风琴", "en": "accordion"} in out["public"]["options"]


@pytest.mark.parametrize("bad", [
    GOOD[:2],                                                    # too few
    GOOD[:2] + (("piano", "钢琴"),),                             # names the civilian word
    GOOD[:2] + (("ORGAN", "别的"),),                             # names the spy word
    GOOD[:2] + (("harpsichord", "又一个"),),                     # duplicate
    GOOD[:2] + (("", "空"),),                                    # empty
])
def test_bad_model_distractors_fall_back_to_the_pool(room, bad):
    register_world()
    fake_llm.register("puzzle_options", lambda p: distractors(*bad))
    out = gen(room)
    assert out is not None and len(out["public"]["options"]) == 4
    got = {o["en"] for o in out["public"]["options"]}
    assert "harpsichord" not in got and "ORGAN" not in got and "piano" not in got


def test_distractor_call_failure_falls_back_to_the_pool(room):
    register_world()

    def boom(prompt):
        raise LlmError("down")

    fake_llm.register("puzzle_options", boom)
    assert len(gen(room)["public"]["options"]) == 4


def test_distractor_prompt_shows_both_words_in_both_languages(room):
    register_world()
    seen = []
    fake_llm.register("puzzle_options", lambda p: (seen.append(p), distractors(*GOOD))[1])
    gen(room)
    for w in ("piano", "organ", "钢琴", "风琴"):
        assert w in seen[0]
