from __future__ import annotations

import json
import random
import re

import pytest

from ai_svc.spy_hunt import arena, fake_llm, game, store
from ai_svc.spy_hunt.arena import ArenaSeat
from ai_svc.spy_hunt.llm import LlmError

PAIR = game.Pair("p-arena", {"en": {"a": "piano", "b": "organ"},
                             "zh-Hans": {"a": "钢琴", "b": "风琴"}})


@pytest.fixture
def room(temp_db):
    return store.create_room("arena", "builder", "en")["id"]


def seats(n=5, custom=None):
    out = []
    for i in range(n):
        if custom and i in custom:
            out.append(ArenaSeat(f"Bot{i}", f"b{i}", {"emoji": "x"},
                                 {"voice": "dry", "rules": custom[i]}, None))
        else:
            out.append(ArenaSeat(f"Bot{i}", None if i == 1 else f"b{i}", None, None, "dry"))
    return out


def info(prompt):
    seat = int(re.search(r'"my_seat": (\d+)', prompt).group(1))
    m = re.search(r'"round": (\d+), "phase": "(\w+)"', prompt)
    assert m is not None, "round and phase must always reach the model"
    return seat, int(m.group(1)), m.group(2)


def register(vote=None, statement=None, prompts=None):
    """vote(seat, round, phase, targets) -> target; statement(seat, word, round) -> text."""
    def factory(prompt):
        if prompts is not None:
            prompts.append(prompt)
        seat, rnd, phase = info(prompt)
        if "vote_for" in prompt:
            targets = json.loads(re.search(r"vote for: (\[[^\]]*\])", prompt).group(1))
            pick = vote(seat, rnd, phase, targets) if vote else targets[0]
            return {"vote_for": pick, "reason": ""}
        word = re.search(r"is: (.*)\n", prompt).group(1)
        text = statement(seat, word, rnd) if statement else None
        return {"statement": text or f"hm {seat}"}
    fake_llm.register("bot", factory)


def play(room, s=None):
    return arena.play_match(room, PAIR, "en", s or seats(), random.Random(3))


def test_match_plays_to_a_winner(room):
    register()
    res = play(room)
    log = res["log"]
    assert log["winner"] in ("spies", "civilians")
    assert [r["round"] for r in log["rounds"]] == list(range(1, len(log["rounds"]) + 1))
    alive = {p["seat"] for p in log["players"]}
    for r in log["rounds"]:
        spoke0 = [s["seat"] for s in r["statements"] if s["stage"] == 0]
        assert sorted(spoke0) == sorted(alive)
        if r["eliminated"] is not None:
            alive.discard(r["eliminated"])
    assert sorted(e["seat"] for e in res["entries"]) == [0, 2, 3, 4]
    assert all(e["bot_id"] for e in res["entries"])


def test_civilian_prompt_never_contains_the_spy_word(room):
    prompts = []
    register(prompts=prompts)
    res = play(room)
    roles = {p["seat"]: p["role"] for p in res["log"]["players"]}
    spy_word = res["log"]["words"]["spy"]
    assert spy_word != res["log"]["words"]["civilian"]
    assert prompts
    checked = 0
    for p in prompts:
        seat, _, _ = info(p)
        if roles[seat] == "civilian":
            assert spy_word not in p
            checked += 1
        assert '"role"' not in p
    assert checked > 0


def test_firewall_across_seeds(room):
    spy_seats = set()
    for seed in range(1, 7):
        prompts = []
        register(prompts=prompts)
        res = arena.play_match(room, PAIR, "en", seats(), random.Random(seed))
        roles = {p["seat"]: p["role"] for p in res["log"]["players"]}
        spy_seats |= {s for s, r in roles.items() if r == "spy"}
        spy_word = res["log"]["words"]["spy"]
        checked = 0
        for p in prompts:
            if roles[info(p)[0]] == "civilian":
                assert spy_word not in p
                checked += 1
        assert checked > 0
    assert len(spy_seats) >= 2


def test_reveal_history_has_no_role(room):
    prompts = []
    register(prompts=prompts)
    res = play(room)
    round2 = [p for p in prompts if "vote_for" in p and info(p)[1] == 2]
    if len(res["log"]["rounds"]) >= 2:
        assert round2
    assert prompts and any("vote_for" in p for p in prompts)
    for p in round2:
        assert '"reveal_history": [{' in p
        assert '"role"' not in p


def _spy_of(words):
    """seat -> word seen so far; the spy is the seat whose word is in the minority."""
    if len(words) < 3:
        return None
    counts = {}
    for w in words.values():
        counts[w] = counts.get(w, 0) + 1
    return next((s for s, w in words.items() if counts[w] == 1), None)


def test_rule_vote_skips_the_model(room):
    words, vote_prompts = {}, []

    def statement(seat, word, rnd):
        words[seat] = word
        return None

    def vote(seat, rnd, phase, targets):
        vote_prompts.append((seat, rnd))
        spy = _spy_of(words)
        e = next(s for s in (2, 3, 4) if s != spy)  # a civilian is eliminated
        a = next(s for s in (2, 3, 4, 1) if s not in (e,))  # the accuser
        if rnd == 1:
            if seat == a:
                return 0
            if seat == e:
                return a
            return e
        return targets[0]

    register(vote=vote, statement=statement)
    s = seats(custom={0: [{"when": "accused", "do": "vote_accuser"}]})
    res = play(room, s)
    r1, r2 = res["log"]["rounds"][0], res["log"]["rounds"][1]
    assert sum(1 for v in r1["votes"] if v["target"] == 0) == 1
    accuser = next(v["voter"] for v in r1["votes"] if v["target"] == 0)
    assert r1["eliminated"] not in (None, 0, accuser)
    assert not any(seat == 0 and rnd == 2 for seat, rnd in vote_prompts)
    assert {"voter": 0, "target": accuser, "stage": 0} in r2["votes"]
    entry0 = next(e for e in res["entries"] if e["seat"] == 0)
    assert entry0["fallback_share"] == 0


def test_own_word_statement_falls_back_to_canned(room):
    register(statement=lambda seat, word, rnd: f"my {word}!" if seat == 2 and rnd == 1 else None)
    res = play(room)
    st = next(s for s in res["log"]["rounds"][0]["statements"] if s["seat"] == 2)
    assert "piano" not in st["text"] and "organ" not in st["text"]
    assert next(e for e in res["entries"] if e["seat"] == 2)["fallback_share"] > 0
    assert next(e for e in res["entries"] if e["seat"] == 3)["fallback_share"] == 0


def test_tie_triggers_tiebreak_then_nobody(room):
    def cycle(seat, rnd, phase, targets):
        alive = sorted(targets + [seat])
        return alive[(alive.index(seat) + 1) % len(alive)]

    register(vote=cycle)
    res = play(room)
    r1 = res["log"]["rounds"][0]
    assert r1["eliminated"] is None
    assert all(s["stage"] == 0 for s in r1["statements"])
    assert all(v["stage"] == 0 for v in r1["votes"])
    assert res["log"]["rounds"][1]["round"] == 2


def test_partial_tie_revotes_among_tied(room):
    plan = {0: 1, 2: 1, 1: 2, 3: 2, 4: 3}

    def vote(seat, rnd, phase, targets):
        if rnd == 1 and phase == "vote":
            return plan[seat]
        return targets[0]

    register(vote=vote)
    res = play(room)
    r1 = res["log"]["rounds"][0]
    assert sorted(s["seat"] for s in r1["statements"] if s["stage"] == 1) == [1, 2]
    revotes = [v for v in r1["votes"] if v["stage"] == 1]
    assert sorted(v["voter"] for v in revotes) == [0, 3, 4]
    assert all(v["target"] in (1, 2) for v in revotes)
    assert r1["eliminated"] == 1


def test_model_down_discards_the_match(room):
    def down(prompt):
        raise LlmError("down")
    fake_llm.register("bot", down)
    assert play(room) is None


def test_half_fallbacks_for_one_bot_is_reported(room):
    register(statement=lambda seat, word, rnd: f"{word}!" if seat == 4 else None)
    res = play(room)
    assert res is not None
    assert next(e for e in res["entries"] if e["seat"] == 4)["fallback_share"] >= 0.5
