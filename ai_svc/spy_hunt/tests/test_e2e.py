"""End-to-end backend test: HTTP only for player actions, SSE for observation,
fake LLM (no network)."""
from __future__ import annotations

import json

import pytest

from ai_svc.spy_hunt import bots, engine, fake_llm, game, store, timers, visibility, words
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.tests.test_sse import API, Stream, guest

DESCRIBE = game.DESCRIBE_PHASES
VOTE = game.VOTE_PHASES


class Clock:
    t = 1_800_000_000_000

    def __call__(self):
        return self.t


@pytest.fixture
def e2e(temp_db, monkeypatch):
    monkeypatch.setenv("SPY_HUNT_FAKE_LLM", "1")
    clock = Clock()
    timers.set_clock(clock)
    fake_llm.register("bot", lambda p: {"statement": "a vague clue", "vote_for": None,
                                        "reason": "n/a"})
    fake_llm.register("translate", lambda p: {
        "lang": "en", "translations": {"zh-Hans": "一个普通的线索"}})
    yield clock
    timers.set_clock(None)
    words.reset()
    game.set_pair_source(None)
    game.set_pair_prepare(None)


def test_full_game_over_http_and_stream(client, e2e):
    clock = e2e
    hh, host_pid = guest(client)
    hz, zh_pid = guest(client)
    snap = client.post(f"{API}/rooms", json={"name": "Host", "lang": "en"}, headers=hh).get_json()
    code = snap["code"]
    assert client.post(f"{API}/rooms/{code}/join", json={"name": "Zed", "lang": "zh-Hans"},
                       headers=hz).status_code == 200
    rid = store.get_room_by_code(code)["id"]

    zh_stream = Stream(client, code, hz, after=0)
    try:
        assert client.post(f"{API}/rooms/{code}/start", headers=hh).status_code == 200
        people = {r["seat"]: dict(r) for r in get_conn().execute(
            "SELECT * FROM players WHERE room_id=?", (rid,))}
        human = {p["player_id"]: (seat, hh if p["player_id"] == host_pid else hz)
                 for seat, p in people.items() if not p["is_bot"]}

        for _ in range(400):
            room = store.get_room(rid)
            if room["status"] != "playing":
                break
            phase = room["phase"]
            alive = [s for s, p in
                     {r["seat"]: dict(r) for r in get_conn().execute(
                         "SELECT * FROM players WHERE room_id=?", (rid,))}.items() if p["alive"]]
            if phase in DESCRIBE:
                sp = visibility.build_snapshot(rid, host_pid)["current_speaker"]
                mine = [h for (seat, h) in human.values() if seat == sp]
                if mine:
                    r = client.post(f"{API}/rooms/{code}/statement",
                                    json={"text": "a plain human clue"}, headers=mine[0])
                    assert r.status_code == 200, r.get_json()
                else:
                    clock.t += bots.DELAY_MAX_MS + 1
                    timers.run_due()
            elif phase in VOTE:
                stage = 1 if phase in visibility.STAGE1_PHASES else 0
                tied = bots._tied_seats(get_conn(), room, alive)
                voted = {r["voter_seat"] for r in get_conn().execute(
                    "SELECT voter_seat FROM votes WHERE room_id=? AND game_no=? AND round=?"
                    " AND stage=?", (rid, room["game_no"], room["round"], stage))}
                voters = engine.eligible_voters(alive, stage, tied)
                pending = [(s, h) for (s, h) in human.values()
                           if s in voters and s not in voted]
                if pending:
                    seat, h = pending[0]
                    targets = [t for t in engine.eligible_targets(alive, stage, tied)
                               if t != seat]
                    r = client.post(f"{API}/rooms/{code}/vote",
                                    json={"target_seat": targets[0] if targets else None},
                                    headers=h)
                    assert r.status_code == 200, r.get_json()
                else:
                    clock.t += bots.DELAY_MAX_MS + 1
                    timers.run_due()
            elif phase == "reveal":
                game.advance_phase(rid, room["phase_seq"])
        assert store.get_room(rid)["status"] == "finished"

        got = zh_stream.events_until(lambda f: f["event"] == "game_over", timeout=10)
    finally:
        zh_stream._stop.set()

    def has_key(obj, names):
        if isinstance(obj, dict):
            return any(k in names or has_key(v, names) for k, v in obj.items())
        if isinstance(obj, list):
            return any(has_key(v, names) for v in obj)
        return False

    for f in got[:-1]:
        assert not has_key(f["data"], {"roles", "words"}), f["event"]
    last = got[-1]["data"]
    assert last["roles"] and last["words"] and last["winner"] in ("civilians", "spies")
    assert any(f["event"] == "translation" and f["data"]["target_lang"] == "zh-Hans"
               for f in got)
