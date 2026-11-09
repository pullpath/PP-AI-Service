"""Real threads against the real Flask app and SQLite DB."""
from __future__ import annotations

import threading

import pytest

from ai_svc.spy_hunt import game, store, visibility
from ai_svc.spy_hunt.db import get_conn

API = "/api/spy-hunt"
WORDS = {"en": {"a": "lighthouse", "b": "windmill"}, "zh-Hans": {"a": "灯塔", "b": "风车"}}


@pytest.fixture(autouse=True)
def _pairs(temp_db):
    game.set_pair_source(lambda room_id: game.Pair("t-pair", WORDS))
    yield
    game.set_pair_source(None)


def guest(client):
    b = client.post(f"{API}/guests").get_json()
    return {"Authorization": f"Bearer {b['player_id']}.{b['token']}"}


def playing_room(client):
    hs = [guest(client) for _ in range(4)]
    code = client.post(f"{API}/rooms", json={"name": "H", "lang": "en"}, headers=hs[0]).get_json()["code"]
    for i, h in enumerate(hs[1:], 1):
        client.post(f"{API}/rooms/{code}/join", json={"name": f"P{i}", "lang": "en"}, headers=h)
    assert client.post(f"{API}/rooms/{code}/start", headers=hs[0]).status_code == 200
    seat_h = {client.get(f"{API}/rooms/{code}", headers=h).get_json()["me"]["seat"]: h for h in hs}
    return code, seat_h, store.get_room_by_code(code)["id"]


def race(app, n, fn):
    """Run fn(test_client) in n threads released together; return the results."""
    barrier = threading.Barrier(n)
    results = [None] * n

    def go(i):
        c = app.test_client()
        barrier.wait()
        results[i] = fn(c)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return results


def test_two_identical_votes_at_once(client):
    code, seat_h, rid = playing_room(client)
    while store.get_room(rid)["phase"] == "describe":
        s = visibility.build_snapshot(rid, store.get_room(rid)["host_player_id"])["current_speaker"]
        client.post(f"{API}/rooms/{code}/statement", json={"text": f"words {s}"}, headers=seat_h[s])
    assert store.get_room(rid)["phase"] == "vote"
    h = seat_h[0]
    codes = race(client.application, 2, lambda c: c.post(
        f"{API}/rooms/{code}/vote", json={"target_seat": 1}, headers=h).status_code)
    assert sorted(codes) == [200, 409]
    n = get_conn().execute("SELECT COUNT(*) FROM votes WHERE room_id=? AND voter_seat=0",
                           (rid,)).fetchone()[0]
    assert n == 1
    locked = get_conn().execute("SELECT COUNT(*) FROM events WHERE room_id=? AND type='vote_locked'",
                                (rid,)).fetchone()[0]
    assert locked == 1


def test_two_statements_same_turn_at_once(client):
    code, seat_h, rid = playing_room(client)
    s = visibility.build_snapshot(rid, store.get_room(rid)["host_player_id"])["current_speaker"]
    h = seat_h[s]
    seq = store.get_room(rid)["phase_seq"]
    codes = race(client.application, 2, lambda c: c.post(
        f"{API}/rooms/{code}/statement", json={"text": "same turn"}, headers=h).status_code)
    assert sorted(codes) == [200, 409]
    rows = get_conn().execute("SELECT seat FROM messages WHERE room_id=? AND kind='statement'", (rid,)).fetchall()
    assert [r["seat"] for r in rows] == [s]
    assert store.get_room(rid)["phase_seq"] == seq + 1
