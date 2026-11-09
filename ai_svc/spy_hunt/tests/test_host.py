from __future__ import annotations

import json

import pytest

from ai_svc.spy_hunt import bots, fake_llm, game, host, llm, store
from ai_svc.spy_hunt.config import GameConfig
from ai_svc.spy_hunt.db import get_conn

WORDS = {"en": {"a": "lighthouse", "b": "windmill"}, "zh-Hans": {"a": "灯塔", "b": "风车"}}


@pytest.fixture
def henv(temp_db):
    game.set_on_host_moment(None)
    game.set_pair_source(lambda room_id: game.Pair("t-pair", WORDS))
    yield
    host.reset()
    game.set_on_host_moment(None)
    game.set_pair_source(None)


def started_room():
    room = store.create_room("pid0", "P0", "en")
    rid = room["id"]
    for _ in range(3):
        game.add_bot(rid, "pid0")
    game.start_game(rid, "pid0")
    return rid


def host_msgs(rid):
    return [dict(r) for r in get_conn().execute(
        "SELECT * FROM messages WHERE room_id=? AND kind='host' ORDER BY id", (rid,))]


def test_prompt_has_no_roles_before_reveal(henv):
    rid = started_room()
    seen = []
    fake_llm.register("host", lambda p: seen.append(p) or {"text": "Welcome!"})
    host.narrate(rid, "round_start")
    assert len(host_msgs(rid)) == 1 and host_msgs(rid)[0]["text"] == "Welcome!"
    assert "spy" not in seen[0].lower().replace("social-deduction", "")
    assert "civilian" not in seen[0].lower()
    assert "lighthouse" not in seen[0] and "windmill" not in seen[0]
    assert "<<<DATA>>>" in seen[0]


def test_fallback_on_llm_error(henv):
    rid = started_room()
    host.narrate(rid, "game_over")  # no fake registered -> LlmError
    msgs = host_msgs(rid)
    assert len(msgs) == 1 and msgs[0]["text"] == host.CANNED["en"]["game_over"]
    assert msgs[0]["seat"] is None


def test_skipped_at_19_percent_but_bot_still_runs(henv):
    rid = started_room()
    total = GameConfig().room_ai_budget
    used = total - int(total * 0.19)
    get_conn().execute("UPDATE rooms SET ai_calls=? WHERE id=?", (used, rid))
    get_conn().commit()
    fake_llm.register("host", lambda p: {"text": "hi"})
    fake_llm.register("bot", lambda p: {"statement": "a vague clue"})
    host.narrate(rid, "round_start")
    assert host_msgs(rid) == []
    out = llm.call_json("bot", "p", bots._StatementOut, rid, 50, 5.0)
    assert out.statement == "a vague clue"


def test_hook_fires_moments(henv):
    seen = []
    game.set_on_host_moment(lambda r, m: seen.append(m))
    started_room()
    assert seen == ["round_start"]


def test_public_state_only_includes_the_current_games_reveals(henv):
    rid = started_room()
    with store.tx(rid) as c:
        old = {"round": 1, "stage": 0, "outcome": "eliminated", "eliminated": 3, "tied": [],
               "votes": [], "role": "spy"}
        store.append_event(rid, "reveal", old, "all", conn=c)
        store.append_event(rid, "game_started", {"seat": 0, "game_no": 2, "my_word": "x"},
                           "seat:0", conn=c)
        new = dict(old, eliminated=2, role="civilian")
        store.append_event(rid, "reveal", new, "all", conn=c)
    state = host.public_state(rid, "elimination")
    assert [r["eliminated_seat"] for r in state["reveals"]] == [2]


def test_final_vote_does_not_also_narrate_an_elimination(henv):
    seen = []
    game.set_on_host_moment(lambda r, m: seen.append(m))
    rid = started_room()
    seen.clear()
    from ai_svc.spy_hunt import engine
    # drive a vote where everyone votes the spy out: game over, so only game_over is narrated
    rows = {r["seat"]: dict(r) for r in get_conn().execute(
        "SELECT * FROM players WHERE room_id=?", (rid,))}
    spy = next(s for s, p in rows.items() if p["role"] == "spy")
    room = store.get_room(rid)
    with store.tx(rid) as c:
        c.execute("UPDATE rooms SET phase='vote' WHERE id=?", (rid,))
        for s, p in rows.items():
            if s != spy:
                c.execute("INSERT INTO votes(room_id, game_no, round, stage, voter_seat, target_seat)"
                          " VALUES(?,?,?,?,?,?)", (rid, room["game_no"], room["round"], 0, s, spy))
        moments = []
        game._resolve_vote(c, rid, [], moments)
    assert [m for _, m in moments] == ["game_over"]
