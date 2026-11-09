"""Timer thread, scheduler semantics and maintenance sweep (Task 6).

Everything runs through `timers.run_due()` with an injected clock; only
`test_thread_starts_lazily_and_runs_due_entry` uses the real thread.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading

import pytest

from ai_svc.spy_hunt import game, store, timers
from ai_svc.spy_hunt.config import GameConfig
from ai_svc.spy_hunt.db import get_conn

WORDS = {"en": {"a": "lighthouse", "b": "windmill"}, "zh-Hans": {"a": "灯塔", "b": "风车"}}
GC = GameConfig()
HOUR = 3600 * 1000


class FakeClock:
    def __init__(self, t: int = 1_800_000_000_000):
        self.t = t

    def __call__(self) -> int:
        return self.t


@pytest.fixture
def clock(temp_db, monkeypatch):
    """One fake time for timers AND game deadlines / last_active."""
    c = FakeClock()
    timers.set_clock(c)
    monkeypatch.setattr(store, "now_ms", c)
    monkeypatch.setattr(game, "now_ms", c)
    game.set_pair_source(lambda room_id: game.Pair("t-pair", WORDS))
    timers.install()
    yield c
    game.set_pair_source(None)


# ---- helpers ----

def lobby(n=4):
    room = store.create_room("pid0", "P0", "en")
    for i in range(1, n):
        store.add_player(room["id"], f"pid{i}", f"P{i}", "en")
    return room["id"]


def room(rid):
    return store.get_room(rid)


def messages(rid, kind=None):
    rows = get_conn().execute("SELECT * FROM messages WHERE room_id=? ORDER BY id", (rid,))
    return [dict(r) for r in rows if kind is None or r["kind"] == kind]


def events(rid):
    return [dict(r) | {"payload": json.loads(r["payload_json"])} for r in get_conn().execute(
        "SELECT * FROM events WHERE room_id=? ORDER BY seq", (rid,))]


def player(rid, player_id):
    return dict(get_conn().execute("SELECT * FROM players WHERE room_id=? AND player_id=?",
                                   (rid, player_id)).fetchone())


def current_speaker_pid(rid):
    from ai_svc.spy_hunt import visibility
    snap = visibility.build_snapshot(rid, "pid0")
    seat = snap["current_speaker"]
    return get_conn().execute("SELECT player_id FROM players WHERE room_id=? AND seat=?",
                              (rid, seat)).fetchone()[0]


def to_deadline(clock, rid):
    clock.t = room(rid)["phase_deadline"]


# ---- scheduler semantics ----

def test_stale_phase_seq_entry_is_discarded(clock):
    rid = lobby()
    game.start_game(rid, "pid0")
    seq0 = room(rid)["phase_seq"]
    assert [e[:4] for e in timers.pending()] == [
        (room(rid)["phase_deadline"], "phase_timeout", rid, seq0)]
    # the speaker talks: phase_seq moves on, the old entry is now stale
    game.submit_statement(rid, current_speaker_pid(rid), "it is tall and old")
    seq1 = room(rid)["phase_seq"]
    assert seq1 == seq0 + 1
    clock.t += GC.turn_seconds * 1000  # both the stale and the fresh entry are due
    assert timers.run_due() == 2
    skipped = messages(rid, "skipped")
    assert len(skipped) == 1  # only the fresh entry acted
    assert room(rid)["phase_seq"] == seq1 + 1


def test_same_entry_fired_twice_acts_once(clock):
    rid = lobby()
    game.start_game(rid, "pid0")
    r = room(rid)
    # duplicate scheduling (reloader, rebuild, hook) collapses to one entry
    timers.schedule(r["phase_deadline"], "phase_timeout", rid, r["phase_seq"])
    timers.schedule(r["phase_deadline"], "phase_timeout", rid, r["phase_seq"])
    assert len(timers.pending()) == 1
    to_deadline(clock, rid)
    assert timers.run_due() == 1
    # scheduling it again after it fired is also a no-op
    timers.schedule(r["phase_deadline"], "phase_timeout", rid, r["phase_seq"])
    assert timers.run_due() == 0
    assert len(messages(rid, "skipped")) == 1


def test_same_entry_fired_twice_handler_runs_once(clock):
    calls = []
    timers.register("probe", lambda room_id, seq, payload: calls.append((room_id, seq, payload)))
    for _ in range(3):
        timers.schedule(clock.t, "probe", "r1", 7, {"x": 1})
    timers.schedule(clock.t, "probe", "r1", 7, {"x": 2})  # different payload: distinct entry
    assert timers.run_due() == 2
    assert calls == [("r1", 7, {"x": 1}), ("r1", 7, {"x": 2})]


def test_language_change_and_rejoin_during_describe_do_not_cancel_timeout(clock):
    rid = lobby()
    game.start_game(rid, "pid0")
    seq = room(rid)["phase_seq"]
    v = room(rid)["version"]
    store.update_me(rid, "pid1", lang="zh-Hans")
    store.update_me(rid, "pid2", name="Renamed")
    assert store.add_player(rid, "pid3", "P3", "en")[1] is False  # existing member re-joins
    with pytest.raises(store.StoreError):
        store.add_player(rid, "newcomer", "New", "en")  # cannot join mid-game
    assert room(rid)["version"] > v and room(rid)["phase_seq"] == seq
    to_deadline(clock, rid)
    assert timers.run_due() == 1
    assert len(messages(rid, "skipped")) == 1
    assert room(rid)["phase_seq"] == seq + 1


def test_rebuild_from_db_after_restart_reschedules_playing_room(clock):
    rid = lobby()
    game.start_game(rid, "pid0")
    lobby_only = store.create_room("pidX", "X", "en")["id"]
    r = room(rid)
    timers.reset()  # simulated restart: heap, handlers' state and hook gone
    timers.set_clock(clock)
    assert timers.pending() == []
    timers.install()
    assert timers.rebuild_from_db() == 1
    pend = [e for e in timers.pending() if e[1] == "phase_timeout"]
    assert [e[:4] for e in pend] == [(r["phase_deadline"], "phase_timeout", rid, r["phase_seq"])]
    assert all(e[2] != lobby_only for e in pend)
    clock.t = r["phase_deadline"] - 1
    assert timers.run_due() == 0
    clock.t += 1
    assert timers.run_due() >= 1
    assert len(messages(rid, "skipped")) == 1
    # the game keeps going: the new phase was scheduled through the hook
    assert any(e[1] == "phase_timeout" and e[3] == r["phase_seq"] + 1 for e in timers.pending())


def test_unregistered_kind_is_dropped_without_crashing(clock):
    calls = []
    timers.register("probe", lambda *a: calls.append(a))
    timers.schedule(clock.t, "bot_act", "r1", 1, {"seat": 2})  # no handler until Task 10
    timers.schedule(clock.t, "no_such_kind", "r1", 1)
    timers.schedule(clock.t, "probe", "r1", 1)
    assert timers.run_due() == 1
    assert len(calls) == 1
    assert timers.pending() == []


def test_raising_handler_does_not_kill_loop_or_spin(clock):
    attempts = []

    def boom(room_id, seq, payload):
        attempts.append(clock.t)
        raise RuntimeError("handler bug")

    ok = []
    timers.register("boom", boom)
    timers.register("probe", lambda *a: ok.append(a))
    timers.schedule(clock.t, "boom", "r1", 1)
    timers.schedule(clock.t, "probe", "r1", 1)
    assert timers.run_due() == 2  # the raise did not stop the second entry
    assert len(attempts) == 1 and len(ok) == 1
    assert timers.run_due() == 0  # retry is backed off, not immediate: no spin
    for _ in range(10):
        clock.t += 60_000
        timers.run_due()
    assert len(attempts) == 1 + timers.MAX_RETRIES  # bounded, then dropped
    assert timers.pending() == []


def test_full_game_progresses_only_through_timeouts(clock):
    rid = lobby()
    game.start_game(rid, "pid0")
    steps = 0
    while room(rid)["status"] == "playing":
        before = room(rid)
        to_deadline(clock, rid)
        assert timers.run_due() == 1
        assert room(rid)["phase_seq"] == before["phase_seq"] + 1
        steps += 1
        assert steps < 100
    r = room(rid)
    cfg = json.loads(r["config_json"])
    rounds = cfg["max_rounds"]
    assert r["status"] == "finished" and r["winner"] == "spies" and r["round"] == rounds
    skipped = messages(rid, "skipped")
    assert len(skipped) == 4 * rounds and all(m["text"] is None for m in skipped)
    reveals = [e for e in events(rid) if e["type"] == "reveal"]
    assert len(reveals) == rounds and all(e["payload"]["outcome"] == "nobody" and
                                          e["payload"]["eliminated"] is None for e in reveals)
    phases = [e["payload"]["phase"] for e in events(rid) if e["type"] == "phase"]
    assert phases.count("vote") == rounds and phases.count("reveal") == rounds - 1
    # describe x4, vote, reveal per round; the last round ends at the vote
    assert steps == rounds * 6 - 1
    assert [e for e in timers.pending() if e[1] == "phase_timeout"] == []


# ---- mark_disconnected ----

def test_mark_disconnected_sets_flag_and_emits_event(clock):
    rid = lobby()
    get_conn().execute("UPDATE players SET connected=1 WHERE room_id=?", (rid,))
    get_conn().commit()
    timers.note_connected(rid, "pid1")
    timers.note_disconnected(rid, "pid1")
    assert timers.run_due() == 0  # delayed, the stream thread never waits
    clock.t += timers.DISCONNECT_DELAY_MS
    v = room(rid)["version"]
    assert timers.run_due() == 1
    assert player(rid, "pid1")["connected"] == 0
    assert room(rid)["version"] == v + 1
    ev = events(rid)[-1]
    assert ev["type"] == "player_updated" and ev["audience"] == "all"
    assert ev["payload"]["player"]["connected"] is False
    assert player(rid, "pid2")["connected"] == 1


def test_mark_disconnected_skipped_if_player_reconnected(clock):
    rid = lobby()
    get_conn().execute("UPDATE players SET connected=1 WHERE room_id=?", (rid,))
    get_conn().commit()
    timers.note_connected(rid, "pid1")
    timers.note_disconnected(rid, "pid1")
    clock.t += 3000
    timers.note_connected(rid, "pid1")  # reconnects before the delay is up
    n = len(events(rid))
    clock.t += timers.DISCONNECT_DELAY_MS
    timers.run_due()
    assert player(rid, "pid1")["connected"] == 1
    assert len(events(rid)) == n
    # reconnect then disconnect again: only the newest entry may act
    timers.note_disconnected(rid, "pid1")
    clock.t += timers.DISCONNECT_DELAY_MS
    assert timers.run_due() == 1
    assert player(rid, "pid1")["connected"] == 0


def test_mark_disconnected_kept_while_another_stream_is_open(clock):
    rid = lobby()
    get_conn().execute("UPDATE players SET connected=1 WHERE room_id=?", (rid,))
    get_conn().commit()
    timers.note_connected(rid, "pid1")  # two tabs
    timers.note_connected(rid, "pid1")
    timers.note_disconnected(rid, "pid1")
    clock.t += timers.DISCONNECT_DELAY_MS
    timers.run_due()
    assert player(rid, "pid1")["connected"] == 1


# ---- sweep ----

def _insert_events(rid, n):
    get_conn().executemany(
        "INSERT INTO events(room_id, type, payload_json, audience, created_at)"
        " VALUES(?,?,?,?,?)", [(rid, "ping", "{}", "all", 0)] * n)
    get_conn().commit()


def _age(rid, ms):
    get_conn().execute("UPDATE rooms SET last_active=? WHERE id=?", (store.now_ms() - ms, rid))
    get_conn().commit()


def test_sweep_prunes_events_and_finishes_idle_rooms(clock):
    idle_lobby = lobby()
    idle_game = lobby()
    game.start_game(idle_game, "pid0")
    busy = lobby()
    old_finished = lobby()
    recent_finished = lobby()
    for rid in (old_finished, recent_finished):
        get_conn().execute("UPDATE rooms SET status='finished' WHERE id=?", (rid,))
    get_conn().commit()
    _insert_events(busy, 600)
    _insert_events(old_finished, 20)
    _insert_events(recent_finished, 20)
    idle_ms = GC.room_idle_hours * HOUR
    _age(idle_lobby, idle_ms + 1)
    _age(idle_game, idle_ms + 1)
    _age(busy, idle_ms - 1)
    _age(old_finished, 24 * HOUR + 1)
    _age(recent_finished, 23 * HOUR)
    seq_before = room(idle_game)["phase_seq"]
    busy_last = get_conn().execute("SELECT MAX(seq) FROM events WHERE room_id=?",
                                   (busy,)).fetchone()[0]

    timers.schedule(clock.t, "sweep", "", 0)
    assert timers.run_due() == 1

    for rid in (idle_lobby, idle_game):
        r = room(rid)
        assert r["status"] == "finished" and r["winner"] is None and r["phase"] is None
        assert events(rid)[-1]["type"] == "closed"
        assert events(rid)[-1]["payload"] == {"reason": "idle"}
    # finishing bumps phase_seq so the idle game's pending timeout is stale
    assert room(idle_game)["phase_seq"] == seq_before + 1
    assert room(busy)["status"] == "lobby"
    busy_events = events(busy)
    assert len(busy_events) == 500 and busy_events[-1]["seq"] == busy_last
    assert events(old_finished) == []
    assert len(events(recent_finished)) > 20
    # the sweep reschedules itself 10 minutes out
    assert [(e[0], e[1]) for e in timers.pending() if e[1] == "sweep"] == [
        (clock.t + timers.SWEEP_INTERVAL_MS, "sweep")]
    # the stale timeout of the idle game fires harmlessly
    clock.t += GC.turn_seconds * 1000
    timers.run_due()
    assert room(idle_game)["status"] == "finished" and messages(idle_game, "skipped") == []


def test_sweep_survives_a_failing_room_and_still_reschedules(clock, monkeypatch):
    idle = lobby()
    _age(idle, GC.room_idle_hours * HOUR + 1)
    real = timers._finish_idle

    def flaky(rid, now):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(timers, "_finish_idle", flaky)
    timers.schedule(clock.t, "sweep", "", 0)
    timers.run_due()
    assert any(e[1] == "sweep" for e in timers.pending())
    monkeypatch.setattr(timers, "_finish_idle", real)
    clock.t += timers.SWEEP_INTERVAL_MS
    timers.run_due()
    assert room(idle)["status"] == "finished"


# ---- lazy start ----

def test_import_does_not_start_thread():
    code = (
        "import threading\n"
        "from flask import Flask\n"
        "from ai_svc.spy_hunt import spy_hunt_bp, timers\n"
        "app = Flask('x'); app.register_blueprint(spy_hunt_bp)\n"
        "assert not timers.is_running()\n"
        "assert timers.THREAD_NAME not in [t.name for t in threading.enumerate()]\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def test_request_installs_hook_without_thread_in_tests(client):
    assert not timers.is_running()
    client.get("/api/spy-hunt/health")
    assert game._phase_hook is timers._on_phase_change
    assert not timers.is_running()  # tests disable the real thread (conftest)


def test_thread_starts_lazily_and_runs_due_entry(temp_db, monkeypatch):
    monkeypatch.setattr(timers, "THREAD_ENABLED", True)
    assert not timers.is_running()
    fired = threading.Event()
    timers.register("probe", lambda *a: fired.set())

    barrier = threading.Barrier(8)

    def start():
        barrier.wait()
        timers.ensure_started()

    ts = [threading.Thread(target=start) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert timers.is_running()
    timers.ensure_started()
    assert [t.name for t in threading.enumerate()].count(timers.THREAD_NAME) == 1
    # an entry scheduled after the thread is asleep wakes it
    timers.schedule(timers.now() + 5, "probe", "r1", 1)
    assert fired.wait(2.0)
    timers.reset()
    assert not timers.is_running()


# ---- fix round 1: no permanent stall, races, restart state ----

def _failing_advance(monkeypatch, fail_rooms):
    real = game.advance_phase
    attempts = []

    def flaky(room_id, seq):
        if room_id in fail_rooms:
            attempts.append(timers.now())
            raise RuntimeError("db hiccup")
        return real(room_id, seq)

    monkeypatch.setattr(game, "advance_phase", flaky)
    return attempts


def _exhaust_backoff(clock):
    for i in range(timers.MAX_RETRIES):
        clock.t += timers.RETRY_BASE_MS * (2 ** i)
        timers.run_due()


def test_phase_timeout_never_dropped_while_room_playing(clock, monkeypatch):
    rid = lobby()
    game.start_game(rid, "pid0")
    seq = room(rid)["phase_seq"]
    fail = {rid}
    attempts = _failing_advance(monkeypatch, fail)
    to_deadline(clock, rid)
    timers.run_due()
    _exhaust_backoff(clock)
    assert len(attempts) == 1 + timers.MAX_RETRIES
    # past the backoff: re-queued at +60 s, never dropped
    pend = [e for e in timers.pending() if e[1] == "phase_timeout"]
    assert [(e[0], e[3]) for e in pend] == [(clock.t + timers.PHASE_RETRY_MS, seq)]
    fail.clear()  # the problem goes away
    clock.t += timers.PHASE_RETRY_MS
    timers.run_due()
    assert len(messages(rid, "skipped")) == 1 and room(rid)["phase_seq"] == seq + 1


def test_failing_room_requeued_every_60s_without_starving_others(clock, monkeypatch):
    bad = lobby()
    game.start_game(bad, "pid0")
    attempts = _failing_advance(monkeypatch, {bad})
    to_deadline(clock, bad)
    timers.run_due()
    _exhaust_backoff(clock)
    good = store.create_room("g0", "G0", "en")["id"]
    for i in range(1, 4):
        store.add_player(good, f"g{i}", f"G{i}", "en")
    game.start_game(good, "g0")
    n = len(attempts)
    for minute in range(1, 6):
        clock.t += timers.PHASE_RETRY_MS
        timers.run_due()
        assert len(attempts) == n + minute  # exactly one attempt per 60 s, no spin
        assert timers.run_due() == 0
    # the healthy room kept advancing on its own timeouts meanwhile
    assert len(messages(good, "skipped")) >= 1
    assert messages(bad, "skipped") == []


def test_retry_stops_once_phase_moved_on(clock, monkeypatch):
    rid = lobby()
    game.start_game(rid, "pid0")
    seq = room(rid)["phase_seq"]
    with timers._cond:  # only our entry
        timers._heap.clear()
        timers._seen.clear()
    timers.register("phase_timeout", lambda r, s, p: (_ for _ in ()).throw(RuntimeError()))
    timers.schedule(clock.t, "phase_timeout", rid, seq)
    timers.run_due()
    _exhaust_backoff(clock)  # still playing at seq: kept
    assert any(e[3] == seq for e in timers.pending())
    get_conn().execute("UPDATE rooms SET phase_seq=phase_seq+1 WHERE id=?", (rid,))
    get_conn().commit()
    clock.t += timers.PHASE_RETRY_MS
    timers.run_due()
    assert timers.pending() == []  # dropped: the room moved on


def test_sweep_rearms_overdue_room_with_dropped_entry(clock, monkeypatch):
    rid = lobby()
    game.start_game(rid, "pid0")
    seq = room(rid)["phase_seq"]
    # the entry vanished (lost/dropped): heap emptied, its dedupe key retired
    with timers._cond:
        for e in timers._heap:
            timers._seen.pop(e[7], None)
        timers._heap.clear()
    clock.t = room(rid)["phase_deadline"] + timers.REARM_GRACE_MS - 1
    timers.schedule(clock.t, "sweep", "", 0)
    timers.run_due()
    assert not any(e[1] == "phase_timeout" for e in timers.pending())  # within grace
    clock.t += 2
    timers.sweep()
    timers.run_due()
    assert len(messages(rid, "skipped")) == 1 and room(rid)["phase_seq"] == seq + 1
    # a room with a queued timeout is not re-armed twice
    clock.t = room(rid)["phase_deadline"] + timers.REARM_GRACE_MS + 1
    before = len(timers.pending())
    timers.sweep()
    assert len(timers.pending()) == before


def test_dropped_entry_can_be_rescheduled(clock):
    timers.register("boom", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    timers.schedule(clock.t, "boom", "r1", 1)
    timers.run_due()
    _exhaust_backoff(clock)
    assert timers.pending() == []
    ok = []
    timers.register("boom", lambda *a: ok.append(a))
    first_at = clock.t - sum(timers.RETRY_BASE_MS * 2 ** i for i in range(timers.MAX_RETRIES))
    assert timers.schedule(first_at, "boom", "r1", 1) is True  # same key, not refused
    timers.run_due()
    assert len(ok) == 1


def test_mark_disconnected_rechecks_under_lock(clock, monkeypatch):
    rid = lobby()
    get_conn().execute("UPDATE players SET connected=1 WHERE room_id=?", (rid,))
    get_conn().commit()
    timers.note_connected(rid, "pid1")
    timers.note_disconnected(rid, "pid1")
    real_tx = store.tx
    from contextlib import contextmanager

    @contextmanager
    def tx_with_reconnect(room_id):
        timers.note_connected(room_id, "pid1")  # lands between pre-check and lock
        with real_tx(room_id) as c:
            yield c

    monkeypatch.setattr(store, "tx", tx_with_reconnect)
    n = len(events(rid))
    clock.t += timers.DISCONNECT_DELAY_MS
    timers.run_due()
    assert player(rid, "pid1")["connected"] == 1
    assert len(events(rid)) == n


def test_rebuild_marks_humans_of_live_rooms_disconnected(clock):
    playing = lobby()
    game.start_game(playing, "pid0")
    lob = store.create_room("l0", "L0", "en")["id"]
    done = store.create_room("d0", "D0", "en")["id"]
    get_conn().execute("UPDATE players SET connected=1")
    get_conn().execute("UPDATE rooms SET status='finished' WHERE id=?", (done,))
    get_conn().commit()
    timers.reset()
    timers.set_clock(clock)
    timers.install()
    timers.rebuild_from_db()
    rows = get_conn().execute("SELECT room_id, is_bot, connected FROM players").fetchall()
    for r in rows:
        if r["room_id"] == done or r["is_bot"]:
            assert r["connected"] == 1
        else:
            assert r["connected"] == 0
    ev = events(lob)[-1]
    assert ev["type"] == "player_updated" and ev["payload"]["player"]["connected"] is False


def test_only_one_sweep_chain(clock, temp_db, monkeypatch):
    monkeypatch.setattr(timers, "THREAD_ENABLED", True)
    monkeypatch.setattr(timers, "_loop", lambda stop: stop.wait())  # inert thread
    timers.ensure_started()
    timers.rebuild_from_db()
    timers._stop.set()
    timers._thread.join(1)
    clock.t += 1234  # a later start must not schedule a second chain at a new time
    timers.ensure_started()  # restart of the thread in the same process
    sweeps = [e for e in timers.pending() if e[1] == "sweep"]
    assert len(sweeps) == 1
    clock.t = sweeps[0][0]
    timers.run_due()
    clock.t += 1
    timers._sweep_handler("", 0, None)  # a stray extra sweep run
    assert len([e for e in timers.pending() if e[1] == "sweep"]) == 1


def test_sweep_does_not_drop_events_after_rematch(clock, monkeypatch):
    rid = lobby()
    get_conn().execute("UPDATE rooms SET status='finished' WHERE id=?", (rid,))
    get_conn().commit()
    _age(rid, 24 * HOUR + 1)
    real = timers._drop_events

    def rematch_first(room_id, keep, *a):
        if keep is None:
            game.rematch(room_id, "pid0")  # lands between the scan and the delete
        return real(room_id, keep, *a)

    monkeypatch.setattr(timers, "_drop_events", rematch_first)
    timers.sweep()
    assert room(rid)["status"] == "lobby"
    assert any(e["type"] == "rematch" for e in events(rid))
    assert len(events(rid)) > 1


def test_reset_never_revives_old_thread(temp_db, monkeypatch):
    monkeypatch.setattr(timers, "THREAD_ENABLED", True)
    timers.ensure_started()
    old_stop = timers._stop
    timers.reset()
    assert old_stop.is_set()
    timers.ensure_started()
    assert timers._stop is not old_stop and old_stop.is_set()
    timers.reset()
