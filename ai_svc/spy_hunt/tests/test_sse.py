"""SSE stream tests (impl spec §7.1). Every blocking read has a timeout."""
from __future__ import annotations

import json
import queue
import threading
import time

import pytest

from ai_svc.spy_hunt import db, events, game, store, timers
from ai_svc.spy_hunt.db import get_conn

API = "/api/spy-hunt"
WORDS = {"en": {"a": "lighthouse", "b": "windmill"}, "zh-Hans": {"a": "灯塔", "b": "风车"}}
TIMEOUT = 3.0


@pytest.fixture(autouse=True)
def _sse_env(temp_db, monkeypatch):
    monkeypatch.setattr(events, "PING_INTERVAL_S", 0.05)
    events.reset()
    game.set_pair_source(lambda room_id: game.Pair("t-pair", WORDS))
    yield
    game.set_pair_source(None)
    game.set_on_phase_change(None)


# ---- helpers ----

def guest(client):
    r = client.post(f"{API}/guests")
    b = r.get_json()
    return {"Authorization": f"Bearer {b['player_id']}.{b['token']}"}, b["player_id"]


def make_room(client, n_joiners=1):
    """Host + n joiners via the API. Returns (code, room_id, [(headers, pid), ...])."""
    h, pid = guest(client)
    snap = client.post(f"{API}/rooms", json={"name": "Host", "lang": "en"}, headers=h).get_json()
    people = [(h, pid)]
    for i in range(n_joiners):
        hj, pj = guest(client)
        r = client.post(f"{API}/rooms/{snap['code']}/join", json={"name": f"P{i}", "lang": "en"},
                        headers=hj)
        assert r.status_code == 200
        people.append((hj, pj))
    return snap["code"], store.get_room_by_code(snap["code"])["id"], people


def last_seq(rid):
    return get_conn().execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE room_id=?",
                              (rid,)).fetchone()[0]


def emit(rid, type, payload, audience="all"):
    with store.tx(rid) as conn:
        return store.append_event(rid, type, payload, audience, conn=conn)


def parse(text):
    """One SSE block -> dict (comment-only blocks -> {"comment": ...})."""
    out = {}
    for line in text.split("\n"):
        if line.startswith(":"):
            out.setdefault("comment", line[1:].strip())
        elif line:
            k, _, v = line.partition(": ")
            out[k] = v
    if "data" in out:
        out["data"] = json.loads(out["data"])
    if "id" in out:
        out["id"] = int(out["id"])
    return out


class Stream:
    """An open SSE response read on a background thread into a queue."""

    def __init__(self, client, code, headers, after=None, last_event_id=None, query=None):
        url = f"{API}/rooms/{code}/events"
        if query is not None:
            url += query
        elif after is not None:
            url += f"?after={after}"
        hdrs = dict(headers)
        if last_event_id is not None:
            hdrs["Last-Event-ID"] = str(last_event_id)
        self.resp = client.get(url, headers=hdrs, buffered=False)
        self.status = self.resp.status_code
        self.q: "queue.Queue[dict]" = queue.Queue()
        self._stop = threading.Event()
        self._done = threading.Event()
        if self.status == 200:
            self._t = threading.Thread(target=self._read, daemon=True)
            self._t.start()
        else:
            self._done.set()

    def _read(self):
        buf = ""
        try:
            for chunk in self.resp.response:
                buf += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    self.q.put(parse(block))
                if self._stop.is_set():
                    break
        finally:
            self.resp.close()  # same thread that iterates: runs the generator's finally
            db.close_conn()
            self._done.set()

    def next(self, timeout=TIMEOUT):
        return self.q.get(timeout=timeout)

    def next_event(self, timeout=TIMEOUT):
        """Next real event (skip comments)."""
        end = time.monotonic() + timeout
        while True:
            f = self.q.get(timeout=max(0.01, end - time.monotonic()))
            if "event" in f:
                return f

    def events_until(self, pred, timeout=TIMEOUT):
        got = []
        end = time.monotonic() + timeout
        while True:
            f = self.next_event(max(0.01, end - time.monotonic()))
            got.append(f)
            if pred(f):
                return got

    def close(self):
        self._stop.set()
        assert self._done.wait(TIMEOUT), "stream did not stop"


@pytest.fixture
def streams():
    opened = []

    def _open(*a, **kw):
        s = Stream(*a, **kw)
        opened.append(s)
        return s
    yield _open
    for s in opened:
        s._stop.set()
    for s in opened:
        s._done.wait(TIMEOUT)


# ---- brief list ----

def test_events_in_order_after_cursor(client, streams):
    code, rid, people = make_room(client, n_joiners=1)
    cursor = last_seq(rid)
    seqs = [emit(rid, "settings", {"main_lang": "en", "bot_fill": True, "n": i}) for i in range(3)]
    s = streams(client, code, people[0][0], after=cursor)
    assert s.status == 200
    assert s.resp.headers["Content-Type"] == "text/event-stream; charset=utf-8"
    assert s.resp.headers["Cache-Control"] == "no-cache"
    assert s.resp.headers["X-Accel-Buffering"] == "no"
    got = [s.next_event() for _ in range(3)]
    assert [f["id"] for f in got] == seqs
    assert [f["data"]["n"] for f in got] == [0, 1, 2]
    assert all(f["event"] == "settings" for f in got)
    # connecting marks the player connected (player_updated) after the backlog
    f = s.next_event()
    assert f["event"] == "player_updated" and f["data"]["player"]["connected"] is True
    assert f["id"] > seqs[-1]


def test_reconnect_with_last_event_id_gets_only_newer(client, streams):
    code, rid, people = make_room(client)
    a = emit(rid, "settings", {"main_lang": "en", "bot_fill": True, "n": 1})
    b = emit(rid, "settings", {"main_lang": "en", "bot_fill": True, "n": 2})
    s = streams(client, code, people[0][0], after=0, last_event_id=a)
    f = s.next_event()
    assert f["id"] == b and f["data"]["n"] == 2
    # the larger of after / Last-Event-ID wins
    s2 = streams(client, code, people[1][0], after=b, last_event_id=a)
    f2 = s2.next_event()
    assert f2["id"] > b and f2["event"] == "player_updated"


def test_too_old_after_yields_one_state_then_streams(client, streams):
    code, rid, people = make_room(client)
    old = [emit(rid, "settings", {"main_lang": "en", "bot_fill": True}) for _ in range(5)]
    get_conn().execute("DELETE FROM events WHERE room_id=? AND seq<=?", (rid, old[2]))
    get_conn().commit()  # the Task 6 sweep pruned these
    s = streams(client, code, people[1][0], after=old[0])
    f = s.next_event()
    assert f["event"] == "state"
    assert f["data"]["code"] == code and f["data"]["me"]["seat"] == 1
    assert f["id"] == f["data"]["last_seq"] == old[-1]
    # then normal streaming from there, no second state
    nxt = s.next_event()
    assert nxt["event"] == "player_updated" and nxt["id"] > old[-1]
    new = emit(rid, "settings", {"main_lang": "en", "bot_fill": False})
    got = s.events_until(lambda e: e["id"] == new)
    assert all(e["event"] != "state" for e in got)


def test_after_zero_streams_full_history_without_state(client, streams):
    code, rid, people = make_room(client)
    first = get_conn().execute("SELECT MIN(seq) FROM events WHERE room_id=?", (rid,)).fetchone()[0]
    s = streams(client, code, people[0][0], after=0)
    f = s.next_event()
    assert f["event"] == "player_joined" and f["id"] == first


def test_after_zero_on_pruned_room_yields_state(client, streams):
    code, rid, people = make_room(client)
    keep = emit(rid, "settings", {"main_lang": "en", "bot_fill": True})
    get_conn().execute("DELETE FROM events WHERE room_id=? AND seq<?", (rid, keep))
    get_conn().commit()
    s = streams(client, code, people[0][0], after=0)
    f = s.next_event()
    assert f["event"] == "state" and f["id"] == keep


def test_after_greater_than_last_seq_yields_state(client, streams):
    code, rid, people = make_room(client)
    top = last_seq(rid)
    s = streams(client, code, people[0][0], after=top + 1000)
    f = s.next_event()
    assert f["event"] == "state" and f["id"] == top
    nxt = s.next_event()
    assert nxt["event"] == "player_updated" and nxt["id"] > top


def test_personal_event_reaches_only_that_seat(client, streams):
    code, rid, people = make_room(client, n_joiners=1)
    cursor = last_seq(rid)
    s0 = streams(client, code, people[0][0], after=cursor)
    s1 = streams(client, code, people[1][0], after=cursor)
    p = emit(rid, "host_line", {"text": "for seat 1 only"}, "seat:1")
    marker = emit(rid, "settings", {"main_lang": "en", "bot_fill": True})
    got0 = s0.events_until(lambda e: e["id"] == marker)
    got1 = s1.events_until(lambda e: e["id"] == marker)
    assert p not in [e["id"] for e in got0]
    assert [e for e in got1 if e["id"] == p][0]["data"] == {"text": "for seat 1 only"}


def test_idle_stream_yields_ping(client, streams):
    code, rid, people = make_room(client)
    s = streams(client, code, people[0][0], after=last_seq(rid))
    s.next_event()  # own player_updated
    end = time.monotonic() + TIMEOUT
    while True:
        f = s.next(max(0.01, end - time.monotonic()))
        if f.get("comment") == "ping":
            break
        assert "event" not in f


def test_fifth_stream_for_one_guest_is_429(client, streams):
    code, rid, people = make_room(client)
    h = people[0][0]
    opened = [streams(client, code, h) for _ in range(4)]
    assert all(s.status == 200 for s in opened)
    fifth = client.get(f"{API}/rooms/{code}/events", headers=h)
    assert fifth.status_code == 429
    assert fifth.get_json()["error"] == "too_many_streams"
    # another guest is unaffected
    assert streams(client, code, people[1][0]).status == 200


# ---- extra contract ----

def test_unknown_room_404_and_non_member_403_as_json(client):
    code, rid, people = make_room(client)
    h, _ = guest(client)
    r = client.get(f"{API}/rooms/ZZZZ/events", headers=h)
    assert r.status_code == 404 and r.get_json()["error"] == "not_found"
    r = client.get(f"{API}/rooms/{code}/events", headers=h)
    assert r.status_code == 403 and r.get_json()["error"] == "not_member"
    assert r.content_type.startswith("application/json")


def test_no_token_in_url(client):
    code, rid, people = make_room(client)
    cred = people[0][0]["Authorization"].split(" ", 1)[1]
    r = client.get(f"{API}/rooms/{code}/events?auth={cred}")
    assert r.status_code == 401


def test_event_appended_after_open_is_delivered_promptly(client, streams):
    code, rid, people = make_room(client)
    s = streams(client, code, people[0][0], after=last_seq(rid))
    s.next_event()  # own player_updated
    time.sleep(0.12)  # stream is now parked in its wait
    t0 = time.monotonic()
    seq = emit(rid, "settings", {"main_lang": "zh-Hans", "bot_fill": True})
    f = s.next_event(timeout=1.0)
    assert f["id"] == seq
    assert time.monotonic() - t0 < 1.0


def test_wakeup_is_immediate_with_long_ping(client, streams, monkeypatch):
    """With a 10 s ping interval the event must arrive via notify, not the timeout."""
    monkeypatch.setattr(events, "PING_INTERVAL_S", 10.0)
    code, rid, people = make_room(client)
    s = streams(client, code, people[0][0], after=last_seq(rid))
    s.next_event()
    time.sleep(0.05)
    seq = emit(rid, "settings", {"main_lang": "en", "bot_fill": False})
    assert s.next_event(timeout=1.0)["id"] == seq
    monkeypatch.setattr(events, "PING_INTERVAL_S", 0.05)  # let the fixture close it fast
    emit(rid, "settings", {"main_lang": "en", "bot_fill": True})


def test_notify_only_after_commit(temp_db):
    room = store.create_room("pidA", "A", "en")
    rid = room["id"]
    seen = []
    orig = events.notify

    def spy(room_id):
        row = db.get_conn().execute("SELECT 1 FROM events WHERE room_id=? AND type='host_line'",
                                    (room_id,)).fetchone()
        seen.append((room_id, row is not None, get_conn().in_transaction))
        orig(room_id)
    events.notify = spy
    try:
        with store.tx(rid) as conn:
            store.append_event(rid, "host_line", {"text": "x"}, "all", conn=conn)
            assert seen == []  # not before commit
        assert seen == [(rid, True, False)]
        seen.clear()
        with pytest.raises(RuntimeError):
            with store.tx(rid) as conn:
                store.append_event(rid, "host_line", {"text": "y"}, "all", conn=conn)
                raise RuntimeError("rollback")
        assert seen == []  # rolled back: nothing to announce
    finally:
        events.notify = orig


def test_visibility_gate_on_real_game_start(client, streams):
    code, rid, people = make_room(client, n_joiners=1)
    cursor = last_seq(rid)
    s = {pid: streams(client, code, h, after=cursor) for h, pid in people}
    game.start_game(rid, people[0][1])
    seat = {pid: store.seat_of(rid, pid) for _, pid in people}
    word = {r["seat"]: r for r in get_conn().execute(
        "SELECT seat, role, lang FROM players WHERE room_id=?", (rid,))}
    turn = get_conn().execute("SELECT MAX(seq) FROM events WHERE room_id=? AND type='turn'",
                              (rid,)).fetchone()[0]
    for pid, st in s.items():
        got = st.events_until(lambda e: e["id"] == turn)
        mine = [e for e in got if e["event"] == "game_started"]
        assert len(mine) == 1, (pid, got)
        assert mine[0]["data"]["seat"] == seat[pid]
        role = word[seat[pid]]["role"]
        civ_a = store.get_room(rid)["civ_is_a"]
        key = ("a" if civ_a else "b") if role == "civilian" else ("b" if civ_a else "a")
        assert mine[0]["data"]["my_word"] == WORDS["en"][key]
        for e in got:
            assert e["event"] != "state"
            if e["event"] == "game_started":
                assert e["data"]["seat"] == seat[pid]


def test_stream_caps_recover_after_abort(client, streams):
    code, rid, people = make_room(client)
    h = people[0][0]
    opened = [streams(client, code, h) for _ in range(4)]
    assert client.get(f"{API}/rooms/{code}/events", headers=h).status_code == 429
    opened[0].close()
    opened[1].close()
    again = [streams(client, code, h) for _ in range(2)]
    assert all(s.status == 200 for s in again)
    assert client.get(f"{API}/rooms/{code}/events", headers=h).status_code == 429
    for s in opened[2:] + again:
        s.close()
    assert events.open_streams() == (0, {})


def test_close_before_first_read_releases_slot(client):
    """A response closed without ever being iterated past the first chunk."""
    code, rid, people = make_room(client)
    h = people[0][0]
    for _ in range(6):
        r = client.get(f"{API}/rooms/{code}/events", headers=h, buffered=False)
        assert r.status_code == 200
        r.close()
    assert events.open_streams() == (0, {})


def test_total_cap(client, streams, monkeypatch):
    monkeypatch.setattr(events, "MAX_TOTAL", 2)
    code, rid, people = make_room(client, n_joiners=2)
    assert streams(client, code, people[0][0]).status == 200
    assert streams(client, code, people[1][0]).status == 200
    r = client.get(f"{API}/rooms/{code}/events", headers=people[2][0])
    assert r.status_code == 429 and r.get_json()["error"] == "too_many_streams"


def test_connect_and_disconnect_tracking(client, streams, monkeypatch):
    calls = []
    monkeypatch.setattr(timers, "note_connected", lambda r, p: calls.append(("on", r, p)))
    monkeypatch.setattr(timers, "note_disconnected", lambda r, p: calls.append(("off", r, p)))
    code, rid, people = make_room(client)
    pid = people[1][1]
    row = lambda: get_conn().execute(  # noqa: E731
        "SELECT connected FROM players WHERE room_id=? AND player_id=?", (rid, pid)).fetchone()[0]
    assert row() == 0
    s = streams(client, code, people[1][0])
    assert calls == [("on", rid, pid)]
    assert row() == 1
    s.close()
    assert calls == [("on", rid, pid), ("off", rid, pid)]


def test_disconnect_schedules_delayed_mark(client, streams):
    code, rid, people = make_room(client)
    s = streams(client, code, people[0][0])
    s.close()
    kinds = [e[1] for e in timers.pending()]
    assert kinds == ["mark_disconnected"]


def test_malformed_cursor_treated_as_zero(client, streams):
    code, rid, people = make_room(client)
    first = get_conn().execute("SELECT MIN(seq) FROM events WHERE room_id=?", (rid,)).fetchone()[0]
    s = streams(client, code, people[0][0], query="?after=abc", last_event_id="xyz")
    assert s.status == 200
    assert s.next_event()["id"] == first
    s2 = streams(client, code, people[1][0], query="?after=-5", last_event_id="1e3")
    assert s2.status == 200
    assert s2.next_event()["id"] == first
    s3 = streams(client, code, people[1][0], query="?after=" + "9" * 40)
    assert s3.status == 200
    assert s3.next_event()["event"] == "state"


def test_stream_ends_after_lifetime(client, monkeypatch):
    monkeypatch.setattr(events, "MAX_STREAM_S", 0.2)
    code, rid, people = make_room(client)
    s = Stream(client, code, people[0][0])
    assert s._done.wait(TIMEOUT), "stream did not end by itself"
    assert events.open_streams() == (0, {})


def test_stream_not_rate_limited(client, streams):
    code, rid, people = make_room(client)
    h = people[0][0]
    for _ in range(70):  # above the 60/min read limit
        r = client.get(f"{API}/rooms/{code}/events", headers=h, buffered=False)
        assert r.status_code == 200
        r.close()


def test_stream_stops_when_player_leaves(client, streams):
    code, rid, people = make_room(client)
    s = streams(client, code, people[1][0], after=last_seq(rid))
    s.next_event()
    client.post(f"{API}/rooms/{code}/leave", headers=people[1][0])
    got = s.events_until(lambda e: e["event"] == "player_left")
    assert got[-1]["event"] == "player_left"
    assert s._done.wait(TIMEOUT)
