from __future__ import annotations

import json

import pytest

from ai_svc.spy_hunt import db, fake_llm, game, store, words
from ai_svc.spy_hunt.db import get_conn


@pytest.fixture
def wenv(temp_db):
    yield
    words.reset()
    game.set_pair_source(None)
    game.set_pair_prepare(None)


def mkroom(n_humans=1):
    room = store.create_room("pid0", "P0", "en")
    for i in range(1, n_humans):
        store.add_player(room["id"], f"pid{i}", f"P{i}", "en")
    return room["id"]


def only_pairs(*ids):
    c = get_conn()
    c.execute("UPDATE pairs SET active=0")
    for i in ids:
        c.execute("UPDATE pairs SET active=1 WHERE id=?", (i,))
    c.commit()


def all_ids():
    return [r["id"] for r in get_conn().execute("SELECT id FROM pairs ORDER BY id")]


def test_seed_loads_once(wenv):
    n = get_conn().execute("SELECT COUNT(*) c FROM pairs").fetchone()["c"]
    assert n == len(json.load(open(db.SEED_PATH, encoding="utf-8")))
    get_conn().execute("UPDATE pairs SET plays=5")
    get_conn().commit()
    db.init_db()
    assert get_conn().execute("SELECT COUNT(*) c FROM pairs").fetchone()["c"] == n
    assert get_conn().execute("SELECT MAX(plays) m FROM pairs").fetchone()["m"] == 5


def test_draw_never_repeats_within_room(wenv):
    rid = mkroom()
    seen = []
    total = count()
    for _ in range(total):
        seen.append(words.draw_pair(rid).id)
        get_conn().commit()
    assert len(set(seen)) == total


def test_recently_seen_skipped_when_alternatives(wenv):
    ids = all_ids()
    only_pairs(ids[0], ids[1])
    rid = mkroom()
    get_conn().execute("INSERT INTO guest_recent_pairs VALUES('pid0',?,?)",
                       (ids[0], store.now_ms()))
    get_conn().commit()
    for _ in range(5):
        assert words.draw_pair(rid).id == ids[1]
        get_conn().execute("DELETE FROM room_pairs")
        get_conn().execute("DELETE FROM guest_recent_pairs WHERE pair_id=?", (ids[1],))
        get_conn().commit()


def test_recent_older_than_30_days_ignored(wenv):
    ids = all_ids()
    only_pairs(ids[0])
    rid = mkroom()
    get_conn().execute("INSERT INTO guest_recent_pairs VALUES('pid0',?,?)",
                       (ids[0], store.now_ms() - 31 * 86400 * 1000))
    get_conn().commit()
    assert words.draw_pair(rid).id == ids[0]


def test_fallback_to_any_pair_when_exhausted(wenv):
    ids = all_ids()
    only_pairs(ids[0])
    rid = mkroom()
    assert words.draw_pair(rid).id == ids[0]
    assert words.draw_pair(rid).id == ids[0]


GOOD_GEN = {"en": {"a": "sock", "b": "glove"}, "zh_hans": {"a": "袜子", "b": "手套"},
            "difficulty": 2, "theme": "clothes"}


def count():
    return get_conn().execute("SELECT COUNT(*) c FROM pairs").fetchone()["c"]


def test_generation_inserts_when_both_pass(wenv):
    rid = mkroom()
    before = count()
    fake_llm.register("pair_generate", lambda p: GOOD_GEN)
    fake_llm.register("pair_validate", lambda p: {"en": {"ok": True}, "zh_hans": {"ok": True}})
    pair = words.generate_pair(rid)
    assert pair is not None and pair.words["zh-Hans"]["a"] == "袜子"
    assert count() == before + 1


@pytest.mark.parametrize("bad", ["en", "zh_hans"])
def test_generation_rejected_when_either_language_fails(wenv, bad):
    rid = mkroom()
    before = count()
    verdict = {"en": {"ok": True}, "zh_hans": {"ok": True}}
    verdict[bad] = {"ok": False}
    fake_llm.register("pair_generate", lambda p: GOOD_GEN)
    fake_llm.register("pair_validate", lambda p: verdict)
    assert words.generate_pair(rid) is None
    assert count() == before


def test_ensure_available_generates_when_pool_exhausted(wenv):
    ids = all_ids()
    only_pairs(ids[0])
    rid = mkroom()
    before = count()
    words.draw_pair(rid)
    get_conn().commit()
    fake_llm.register("pair_generate", lambda p: GOOD_GEN)
    fake_llm.register("pair_validate", lambda p: {"en": {"ok": True}, "zh_hans": {"ok": True}})
    words.ensure_available(rid)
    fresh = words.draw_pair(rid)
    assert fresh.words["en"]["a"] == "sock"
    assert count() == before + 1


def test_ensure_available_never_raises_on_llm_failure(wenv):
    rid = mkroom()
    get_conn().execute("UPDATE pairs SET active=0")
    get_conn().commit()
    with pytest.raises(LookupError):
        words.draw_pair(rid)  # empty pool is the only hard failure
    words.ensure_available(rid)  # no fake registered: swallowed


def test_record_outcome(wenv):
    pid = all_ids()[0]
    words.record_outcome(pid, True)
    words.record_outcome(pid, False)
    r = get_conn().execute("SELECT plays, spy_wins FROM pairs WHERE id=?", (pid,)).fetchone()
    assert (r["plays"], r["spy_wins"]) == (2, 1)


def test_start_game_uses_pool_and_records_outcome(wenv):
    words.install()
    rid = mkroom()
    game.start_game(rid, "pid0")
    pid = store.get_room(rid)["pair_id"]
    assert get_conn().execute("SELECT 1 FROM room_pairs WHERE room_id=? AND pair_id=?",
                              (rid, pid)).fetchone()
