from __future__ import annotations

import json
import random
import time

import pytest

from ai_svc.spy_hunt import arena, custombots, fake_llm, outfits
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.llm import LlmError
from ai_svc.spy_hunt.scripts import arena_night
from ai_svc.spy_hunt.tests.test_arena_play import register

DAY = 86_400_000
TODAY = "2026-11-10"


def new_bot(i, **cols):
    card = custombots.create(f"owner{i}", f"Bot{i}", {"emoji": outfits.EMOJIS[0], "color": outfits.COLORS[0]},
                             {"voice": next(iter(outfits.VOICES)), "style": next(iter(outfits.STYLES)),
                              "quirk": next(iter(outfits.QUIRKS)), "rules": []})
    if cols:
        sets = ", ".join(f"{k}=?" for k in cols)
        get_conn().execute(f"UPDATE custom_bots SET {sets} WHERE id=?", (*cols.values(), card["id"]))
        get_conn().commit()
    return card["id"]


def seed_pair():
    words = {"en": {"a": "piano", "b": "organ"}, "zh-Hans": {"a": "钢琴", "b": "风琴"}}
    get_conn().execute("UPDATE pairs SET active=0")
    get_conn().execute(
        "INSERT INTO pairs(id, concept_a, concept_b, difficulty, theme, words_json, active, plays,"
        " spy_wins) VALUES('p-n','piano','organ',1,'t',?,1,0,0)", (json.dumps(words, ensure_ascii=False),))
    get_conn().commit()


def rec(bot_id):
    return tuple(get_conn().execute(
        "SELECT arena_games, arena_wins, arena_spy_games, arena_spy_wins FROM custom_bots WHERE id=?",
        (bot_id,)).fetchone())


def now():
    return int(time.time() * 1000)


def test_eligibility(temp_db):
    out = new_bot(1, arena=0)
    blocked = new_bot(2, blocked=1)
    old = new_bot(3, last_active=now() - 15 * DAY)
    old_created = new_bot(4, last_active=None, created_at=now() - 15 * DAY)
    new_null = new_bot(5, last_active=None)
    ok13 = new_bot(6, last_active=now() - 13 * DAY)
    done = new_bot(7)
    get_conn().execute("INSERT INTO arena_entries(match_id, bot_id, day) VALUES('m',?,?)", (done, TODAY))
    get_conn().commit()
    ids = {r["id"] for r in arena.eligible_bots(get_conn(), TODAY, now())}
    assert ids == {new_null, ok13}
    assert not ids & {out, blocked, old, old_created, done}


def test_groups_and_seats(temp_db):
    for i in range(7):
        new_bot(i)
    rows = arena.eligible_bots(get_conn(), TODAY, now())
    g = arena.make_groups(rows, 2, random.Random(1))
    assert sorted(len(x) for x in g) == [2, 5]
    assert len(arena.make_groups(rows, 1, random.Random(1))) == 1
    seats = arena.build_seats(g[-1], random.Random(2))
    assert len(seats) == 5
    custom = {s.bot_id: s.name for s in seats if s.bot_id}
    assert set(custom) == {r["id"] for r in g[-1]}
    builtin = [s.name for s in seats if not s.bot_id]
    assert len(set(builtin)) == len(builtin) and not set(builtin) & set(custom.values())


def entry(seat, bot_id, role="spy", won=True, share=0.0):
    return {"seat": seat, "bot_id": bot_id, "role": role, "won": won, "accused": 1,
            "out_round": None, "quote": "x", "fallback_share": share}


def n(table):
    return get_conn().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_store_match_is_atomic_and_updates_the_record(temp_db):
    a, b, c = new_bot(1), new_bot(2), new_bot(3)
    res = {"log": {"winner": "spies"}, "entries": [entry(0, a)]}
    mid = arena.store_match(get_conn(), TODAY, "en", "p", res)
    assert n("arena_matches") == 1 and n("arena_entries") == 1
    assert json.loads(get_conn().execute("SELECT log_json FROM arena_matches WHERE id=?", (mid,))
                      .fetchone()[0]) == {"winner": "spies"}
    assert rec(a) == (1, 1, 1, 1)
    res = {"log": {}, "entries": [entry(0, b, share=0.5), entry(1, "gone"), entry(2, c, "civilian", False)]}
    arena.store_match(get_conn(), TODAY, "en", "p", res)
    assert n("arena_entries") == 2 and rec(b) == (0, 0, 0, 0) and rec(c) == (1, 0, 0, 0)
    with pytest.raises(Exception):
        arena.store_match(get_conn(), TODAY, "en", "p",
                          {"log": {}, "entries": [entry(0, b), entry(1, a)]})
    assert n("arena_matches") == 2 and n("arena_entries") == 2
    assert rec(b) == (0, 0, 0, 0)


def test_run_night_twice_does_not_double_play(temp_db):
    seed_pair()
    register()
    ids = [new_bot(i) for i in range(5)]
    first = arena.run_night(1, random.Random(1), log=lambda *a: None, today=TODAY)
    assert first["played"] == 1
    before = [rec(i) for i in ids]
    second = arena.run_night(1, random.Random(1), log=lambda *a: None, today=TODAY)
    assert second == {"played": 0, "discarded": 0, "skipped": 0}
    assert [rec(i) for i in ids] == before and n("arena_matches") == 1


def test_run_night_with_no_bots_and_with_model_down(temp_db):
    seed_pair()
    assert arena.run_night(1, random.Random(1), log=lambda *a: None, today=TODAY) == \
        {"played": 0, "discarded": 0, "skipped": 0}
    new_bot(1)

    def down(prompt):
        raise LlmError("down")
    fake_llm.register("bot", down)
    res = arena.run_night(1, random.Random(1), log=lambda *a: None, today=TODAY)
    assert res["played"] == 0 and res["discarded"] >= 1
    assert n("arena_matches") == 0 and n("arena_entries") == 0


def test_night_stops_after_two_discards_in_a_row(temp_db):
    seed_pair()
    for i in range(15):
        new_bot(i)
    calls = []

    def down(prompt):
        calls.append(1)
        raise LlmError("down")
    fake_llm.register("bot", down)
    out = []
    res = arena.run_night(3, random.Random(1), log=out.append, today=TODAY)
    assert res == {"played": 0, "discarded": 2, "skipped": 15}
    assert "model down, stopping" in out


def test_default_day_is_the_utc_date(temp_db, monkeypatch):
    import datetime as real
    import types

    class FakeDT(real.datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is real.timezone.utc
            return cls(2030, 1, 2, 23, 59, tzinfo=tz)

        @classmethod
        def today(cls):
            return cls(2030, 1, 3)
    monkeypatch.setattr(arena, "datetime", types.SimpleNamespace(
        datetime=FakeDT, date=real.date, timedelta=real.timedelta, timezone=real.timezone))
    assert arena._utc_today() == "2030-01-02"


def test_prune_keeps_totals(temp_db):
    a = new_bot(1)
    for day in ("2026-10-26", "2026-10-28"):
        arena.store_match(get_conn(), day, "en", "p", {"log": {}, "entries": [entry(0, a)]})
    assert arena.prune(get_conn(), TODAY) == 1
    assert [r[0] for r in get_conn().execute("SELECT day FROM arena_matches")] == ["2026-10-28"]
    assert n("arena_entries") == 1 and rec(a)[0] == 2


def test_dry_run_makes_no_model_call(temp_db):
    seed_pair()
    calls = []
    fake_llm.register("bot", lambda p: calls.append(p) or {"statement": "hi"})
    new_bot(1)
    out = []
    res = arena.run_night(1, random.Random(1), log=out.append, today=TODAY, dry_run=True)
    assert calls == [] and out and res["played"] == 0
    assert n("arena_matches") == 0 and n("arena_entries") == 0


def test_arena_night_script_main(temp_db, capsys):
    seed_pair()
    register()
    new_bot(1)
    assert arena_night.main(["--matches", "1"]) == 0
    assert "played" in capsys.readouterr().out


def test_statements_are_stripped_of_control_characters(temp_db):
    from ai_svc.spy_hunt import store
    from ai_svc.spy_hunt.tests.test_arena_play import PAIR, seats
    register(statement=lambda seat, word, rnd: "hi\x00\u202e there\x07")
    room = store.create_room("arena", "builder", "en")["id"]
    res = arena.play_match(room, PAIR, "en", seats(), random.Random(3))
    texts = [s["text"] for r in res["log"]["rounds"] for s in r["statements"]]
    assert texts and all(t == "hi there" for t in texts)
