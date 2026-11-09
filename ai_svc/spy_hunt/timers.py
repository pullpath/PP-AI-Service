"""One scheduler thread for every delayed action (impl spec §3, §6.3, §6.4).

A min-heap of `(at_ms, kind, room_id, phase_seq, payload)` entries, served by
ONE daemon thread that sleeps on a `threading.Condition` until the earliest
entry is due (an earlier `schedule()` wakes it). Kinds:

- `phase_timeout`: `game.advance_phase(room_id, phase_seq)`; idempotent, a
  stale `phase_seq` is a no-op. Scheduled through `game.set_on_phase_change`
  (game.py never imports this module).
- `mark_disconnected`: set `players.connected=0` unless the player has
  reconnected since (see `note_connected` / `note_disconnected`).
- `bot_act`: no default handler; Task 10 registers one. Until then (or for any
  unknown kind) entries are logged and dropped.
- `sweep`: maintenance every 10 minutes, reschedules itself.

Lifecycle: nothing starts at import. `ensure_started()` (called from the
blueprint's before_request) installs the handlers and the phase hook, rebuilds
deadlines from SQLite and starts the thread, once (flag + lock). The debug
reloader's parent process imports the app but never serves a request, so it
never gets a thread.

Duplicates are harmless: an identical entry `(at_ms, kind, room_id, phase_seq,
payload)` is accepted once, and every handler re-checks state under the room
lock. A handler that raises is logged and retried with backoff (5/10/20 s); it
never kills the thread. After that a `phase_timeout` keeps retrying every 60 s
for as long as its room is still `playing` at that `phase_seq` (a game must
never stall); other kinds are dropped. As a second net, the sweep re-arms any
playing room overdue by more than 60 s that has no queued timeout.

Tests: `set_clock(fn)`, `run_due()`, `pending()`, `reset()`, `THREAD_ENABLED`.
"""
from __future__ import annotations

import heapq
import itertools
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

from ai_svc.spy_hunt import db, game, store
from ai_svc.spy_hunt.config import GameConfig

log = logging.getLogger(__name__)

THREAD_NAME = "spy-hunt-timers"
THREAD_ENABLED = True  # tests set False: ensure_started() then only installs hooks

SWEEP_INTERVAL_MS = 10 * 60 * 1000
FIRST_SWEEP_DELAY_MS = 60 * 1000
DISCONNECT_DELAY_MS = 10 * 1000
EVENTS_KEEP = 500
FINISHED_EVENTS_TTL_MS = 24 * 3600 * 1000
MAX_RETRIES = 3
RETRY_BASE_MS = 5 * 1000  # 5 s, 10 s, 20 s
PHASE_RETRY_MS = 60 * 1000  # phase_timeout retry interval after the backoff
REARM_GRACE_MS = 60 * 1000  # sweep re-arms rooms overdue by more than this
MAX_WAIT_S = 30.0  # re-check at least this often (wall-clock jumps)
_SEEN_CAP = 50_000
_RUN_CAP = 10_000
# idle limit is a maintenance policy, read from current GameConfig defaults
_IDLE_MS = GameConfig().room_idle_hours * 3600 * 1000

Handler = Callable[[str, int, Optional[Dict[str, Any]]], Any]
Key = Tuple[int, str, str, int, str]

_cond = threading.Condition()
_heap: List[tuple] = []  # (at_ms, counter, kind, room_id, phase_seq, payload, attempt, key)
_counter = itertools.count()
# Dedupe: keys of entries queued (incl. retrying) or fired successfully. A key is
# removed when its entry is dropped, so a legitimately needed re-arm is accepted.
_seen: "OrderedDict[Key, None]" = OrderedDict()
_handlers: Dict[str, Handler] = {}

_start_lock = threading.Lock()
_installed = False
_thread: Optional[threading.Thread] = None
_stop = threading.Event()  # replaced by a fresh Event on every thread start
_sweep_armed = False  # the permanent sweep chain has been scheduled

_conn_lock = threading.Lock()
_conn_gen: Dict[Tuple[str, str], int] = {}  # bumps on every connect
_conn_open: Dict[Tuple[str, str], int] = {}  # open streams per player


# ---- clock ----

def _default_clock() -> int:
    return int(time.time() * 1000)


_clock: Callable[[], int] = _default_clock


def set_clock(fn: Optional[Callable[[], int]]) -> None:
    """Inject `fn() -> epoch ms` (tests). None restores wall-clock time."""
    global _clock
    _clock = fn or _default_clock


def now() -> int:
    return _clock()


# ---- registry and heap ----

def register(kind: str, fn: Handler) -> None:
    """Register `fn(room_id, phase_seq, payload)` for `kind` (replaces any previous)."""
    _handlers[kind] = fn


def _key(at_ms: int, kind: str, room_id: str, phase_seq: int,
         payload: Optional[Dict[str, Any]]) -> Key:
    return (at_ms, kind, room_id, phase_seq,
            json.dumps(payload, sort_keys=True, default=str) if payload is not None else "")


def schedule(at_ms: int, kind: str, room_id: str, phase_seq: int,
             payload: Optional[Dict[str, Any]] = None) -> bool:
    """Queue an entry. An identical entry already queued or fired is ignored
    (returns False). Wakes the thread if this is the new earliest entry."""
    at_ms = int(at_ms)
    key = _key(at_ms, kind, room_id, phase_seq, payload)
    with _cond:
        if key in _seen:
            return False
        _seen[key] = None
        while len(_seen) > _SEEN_CAP:
            _seen.popitem(last=False)
        _push(at_ms, kind, room_id, phase_seq, payload, 0, key)
    return True


def _push(at_ms, kind, room_id, phase_seq, payload, attempt, key) -> None:
    # caller holds _cond
    earliest = _heap[0][0] if _heap else None
    heapq.heappush(_heap, (at_ms, next(_counter), kind, room_id, phase_seq, payload,
                           attempt, key))
    if earliest is None or at_ms < earliest:
        _cond.notify_all()


def pending() -> List[tuple]:
    """Queued entries as `(at_ms, kind, room_id, phase_seq, payload)`, earliest first."""
    with _cond:
        return [(e[0], e[2], e[3], e[4], e[5]) for e in sorted(_heap)]


def _has_pending(kind: str, room_id: str, phase_seq: Optional[int] = None) -> bool:
    with _cond:
        return any(e[2] == kind and e[3] == room_id and (phase_seq is None or e[4] == phase_seq)
                   for e in _heap)


def _retire(key: Key) -> None:
    with _cond:
        _seen.pop(key, None)


def _phase_still_due(room_id: str, phase_seq: int) -> bool:
    """True if the room is still playing at this phase_seq, or if we cannot tell."""
    try:
        row = db.get_conn().execute("SELECT status, phase_seq FROM rooms WHERE id=?",
                                    (room_id,)).fetchone()
    except Exception:
        return True
    return row is not None and row["status"] == "playing" and row["phase_seq"] == phase_seq


def _retry_delay(kind: str, room_id: str, phase_seq: int, attempt: int) -> Optional[int]:
    """Delay before the next attempt, or None to drop the entry."""
    if attempt < MAX_RETRIES:
        return RETRY_BASE_MS * (2 ** attempt)
    if kind == "phase_timeout" and _phase_still_due(room_id, phase_seq):
        return PHASE_RETRY_MS
    return None


def run_due() -> int:
    """Run every entry due now, in order, on the calling thread. Returns how many
    entries were handed to a handler (unknown kinds are dropped, not counted)."""
    executed = 0
    for _ in range(_RUN_CAP):
        with _cond:
            if not _heap or _heap[0][0] > now():
                break
            at_ms, _c, kind, room_id, phase_seq, payload, attempt, key = heapq.heappop(_heap)
        fn = _handlers.get(kind)
        if fn is None:
            log.warning("timers: no handler for %r (room %s), entry dropped", kind, room_id)
            _retire(key)
            continue
        executed += 1
        try:
            fn(room_id, phase_seq, payload)
        except Exception:
            delay = _retry_delay(kind, room_id, phase_seq, attempt)
            if delay is not None:
                log.exception("timers: %s for room %s failed (attempt %d), retry in %d ms",
                              kind, room_id, attempt + 1, delay)
                with _cond:
                    _push(now() + delay, kind, room_id, phase_seq, payload, attempt + 1, key)
            else:
                log.exception("timers: %s for room %s failed %d times, dropped",
                              kind, room_id, attempt + 1)
                _retire(key)
    return executed


# ---- built-in handlers ----

def _phase_timeout(room_id: str, phase_seq: int, payload) -> None:
    game.advance_phase(room_id, phase_seq)


def _on_phase_change(room_id: str, phase_seq: int, deadline: Optional[int]) -> None:
    """game.on_phase_change hook: runs after commit, on the mutating thread."""
    if deadline is not None:
        schedule(deadline, "phase_timeout", room_id, phase_seq)


def note_connected(room_id: str, player_id: str) -> None:
    """A stream for this player opened (Task 7 calls this, and sets connected=1)."""
    k = (room_id, player_id)
    with _conn_lock:
        _conn_gen[k] = _conn_gen.get(k, 0) + 1
        _conn_open[k] = _conn_open.get(k, 0) + 1


def note_disconnected(room_id: str, player_id: str) -> None:
    """A stream closed: schedule `mark_disconnected` DISCONNECT_DELAY_MS out.
    Never blocks the calling (stream) thread."""
    k = (room_id, player_id)
    with _conn_lock:
        _conn_open[k] = max(0, _conn_open.get(k, 0) - 1)
        gen = _conn_gen.get(k, 0)
    schedule(now() + DISCONNECT_DELAY_MS, "mark_disconnected", room_id, 0,
             {"player_id": player_id, "gen": gen})


def _still_disconnected(k: Tuple[str, str], payload: Dict[str, Any]) -> bool:
    with _conn_lock:
        if _conn_open.get(k, 0) > 0:
            return False  # a stream is open right now
        if "gen" in payload and _conn_gen.get(k, 0) != payload["gen"]:
            return False  # reconnected (and maybe left again) since this was scheduled
    return True


def _mark_disconnected(room_id: str, phase_seq: int, payload) -> None:
    player_id = (payload or {}).get("player_id")
    if not player_id:
        return
    k = (room_id, player_id)
    if not _still_disconnected(k, payload):
        return
    with store.tx(room_id) as conn:
        # again under the room lock: a reconnect may have landed since the check
        if not _still_disconnected(k, payload):
            return
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None:
            return
        cur = conn.execute(
            "UPDATE players SET connected=0 WHERE room_id=? AND player_id=? AND connected=1",
            (room_id, player_id))
        if cur.rowcount == 0:
            return
        seat = store.seat_of(room_id, player_id, conn)
        store._bump(conn, room_id)
        store._emit_player(conn, dict(room), seat, "player_updated")
    with _conn_lock:
        if _conn_open.get(k, 0) == 0:
            _conn_open.pop(k, None)
            _conn_gen.pop(k, None)


# ---- sweep ----

def _finish_idle(room_id: str, now_ms: int) -> None:
    """Close one idle room through store.tx (lock, version bump, phase_seq bump)."""
    pend: List[tuple] = []
    cutoff = now_ms - _IDLE_MS
    with store.tx(room_id) as conn:
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None or room["status"] not in ("lobby", "playing") \
                or (room["last_active"] or 0) >= cutoff:
            return  # touched since the scan
        conn.execute("UPDATE rooms SET status='finished', winner=NULL WHERE id=?", (room_id,))
        game._set_phase(conn, room_id, pend, None, None)
        store._bump(conn, room_id)
        store.append_event(room_id, "closed", {"reason": "idle"}, "all", conn=conn)
    game._notify(pend)


def _drop_events(room_id: str, keep: Optional[int],
                 finished_before: Optional[int] = None) -> None:
    """Delete a room's events under its lock: all but the newest `keep`, or (keep
    None) all of them if the room is still finished with last_active before
    `finished_before` (re-checked here: a rematch may have landed since the scan).
    No version bump: retention is not a state change."""
    with store.tx(room_id) as conn:
        if keep is None:
            conn.execute(
                "DELETE FROM events WHERE room_id=? AND EXISTS(SELECT 1 FROM rooms"
                " WHERE id=? AND status='finished' AND last_active<?)",
                (room_id, room_id, finished_before))
            return
        row = conn.execute(
            "SELECT seq FROM events WHERE room_id=? ORDER BY seq DESC LIMIT 1 OFFSET ?",
            (room_id, keep)).fetchone()
        if row is not None:
            conn.execute("DELETE FROM events WHERE room_id=? AND seq<=?", (room_id, row[0]))


def _each(label: str, fn: Callable[..., None], room_ids, *args) -> None:
    for rid in room_ids:
        try:
            fn(rid, *args)
        except Exception:
            log.exception("timers: sweep %s failed for room %s", label, rid)


def sweep() -> None:
    """Finish idle rooms, drop events of rooms finished over 24 h ago, prune the rest
    to the newest EVENTS_KEEP per room. One failing room never stops the others."""
    t = now()
    conn = db.get_conn()
    idle = [r[0] for r in conn.execute(
        "SELECT id FROM rooms WHERE status IN ('lobby','playing') AND last_active<?",
        (t - _IDLE_MS,))]
    _each("finish", _finish_idle, idle, t)
    old = [r[0] for r in conn.execute(
        "SELECT r.id FROM rooms r WHERE r.status='finished' AND r.last_active<?"
        " AND EXISTS(SELECT 1 FROM events e WHERE e.room_id=r.id)",
        (t - FINISHED_EVENTS_TTL_MS,))]
    _each("drop", _drop_events, old, None, t - FINISHED_EVENTS_TTL_MS)
    big = [r[0] for r in conn.execute(
        "SELECT room_id FROM events GROUP BY room_id HAVING COUNT(*)>?", (EVENTS_KEEP,))]
    _each("prune", _drop_events, big, EVENTS_KEEP)
    _rearm_overdue(t)


def _rearm_overdue(t: int) -> None:
    """Safety net: a playing room overdue by more than REARM_GRACE_MS with no
    queued timeout for its current phase_seq gets one now (fresh key)."""
    rows = db.get_conn().execute(
        "SELECT id, phase_seq FROM rooms WHERE status='playing'"
        " AND phase_deadline IS NOT NULL AND phase_deadline<?",
        (t - REARM_GRACE_MS,)).fetchall()
    for r in rows:
        if not _has_pending("phase_timeout", r["id"], r["phase_seq"]):
            log.warning("timers: re-arming overdue room %s (phase_seq %d)", r["id"],
                        r["phase_seq"])
            schedule(t, "phase_timeout", r["id"], r["phase_seq"])


def _sweep_handler(room_id: str, phase_seq: int, payload) -> None:
    # Errors are logged, not raised: a raise would add a retry on top of the
    # self-reschedule below and fork the sweep chain.
    global _sweep_armed
    try:
        sweep()
    except Exception:
        log.exception("timers: sweep failed")
    if not _has_pending("sweep", ""):  # never fork a second chain
        schedule(now() + SWEEP_INTERVAL_MS, "sweep", "", 0)
    _sweep_armed = True


# ---- lifecycle ----

def install() -> None:
    """Register the built-in handlers and the game phase hook. Idempotent."""
    global _installed
    for kind, fn in _DEFAULT_HANDLERS.items():
        _handlers.setdefault(kind, fn)
    if not _installed:
        game.set_on_phase_change(_on_phase_change)
        _installed = True


def _reset_connected(room_id: str) -> None:
    with store.tx(room_id) as conn:
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        seats = [r["seat"] for r in conn.execute(
            "SELECT seat FROM players WHERE room_id=? AND is_bot=0 AND connected=1",
            (room_id,))]
        if room is None or room["status"] == "finished" or not seats:
            return
        conn.execute("UPDATE players SET connected=0 WHERE room_id=? AND is_bot=0",
                     (room_id,))
        store._bump(conn, room_id)
        for seat in seats:
            store._emit_player(conn, dict(room), seat, "player_updated")


def rebuild_from_db() -> int:
    """Reschedule every playing room's current deadline (after a restart).
    Returns the number of rooms scheduled. Overdue deadlines fire at once.

    Also marks every human of a non-finished room disconnected: no stream
    survives a restart, and the stream route sets connected=1 again on connect."""
    stale = db.get_conn().execute(
        "SELECT DISTINCT p.room_id FROM players p JOIN rooms r ON r.id=p.room_id"
        " WHERE r.status!='finished' AND p.is_bot=0 AND p.connected=1").fetchall()
    for (rid,) in stale:
        _reset_connected(rid)
    rows = db.get_conn().execute(
        "SELECT id, phase_seq, phase_deadline FROM rooms"
        " WHERE status='playing' AND phase_deadline IS NOT NULL").fetchall()
    for r in rows:
        schedule(r["phase_deadline"], "phase_timeout", r["id"], r["phase_seq"])
    return len(rows)


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def ensure_started() -> None:
    """Lazy start, once per process: hooks, rebuild, first sweep, thread.
    Safe to call on every request and from many threads."""
    global _thread, _stop, _sweep_armed
    if is_running() or (_installed and not THREAD_ENABLED):
        return
    with _start_lock:
        if is_running():
            return
        install()
        if not THREAD_ENABLED:
            return
        try:
            db.init_db()  # idempotent (IF NOT EXISTS); nothing else creates the schema
            n = rebuild_from_db()
            log.info("timers: rebuilt %d room deadline(s)", n)
        except Exception:  # e.g. schema missing; the thread still serves new entries
            log.exception("timers: rebuild_from_db failed")
        if not _sweep_armed and not _has_pending("sweep", ""):
            schedule(now() + FIRST_SWEEP_DELAY_MS, "sweep", "", 0)
        _sweep_armed = True
        _stop = threading.Event()  # fresh per thread: an old thread can never revive
        _thread = threading.Thread(target=_loop, args=(_stop,), name=THREAD_NAME, daemon=True)
        _thread.start()


def _loop(stop: threading.Event) -> None:
    try:
        while not stop.is_set():
            with _cond:
                if stop.is_set():
                    break
                wait = MAX_WAIT_S
                if _heap:
                    wait = min(wait, max(0.0, (_heap[0][0] - now()) / 1000.0))
                if wait > 0:
                    _cond.wait(wait)
            if stop.is_set():
                break
            try:
                run_due()
            except Exception:  # run_due already isolates handlers; belt and braces
                log.exception("timers: loop iteration failed")
                stop.wait(1.0)
    finally:
        db.close_conn()


def reset() -> None:
    """Tests: stop the thread, clear the heap, dedupe and connection state, restore
    the default handlers and clock, and unhook game.py if the hook is ours."""
    global _thread, _installed, _counter, _sweep_armed
    t = _thread
    _stop.set()  # not cleared again; ensure_started makes a new Event
    with _cond:
        _cond.notify_all()
    if t is not None and t is not threading.current_thread():
        t.join(2.0)
    _thread = None
    with _cond:
        _heap.clear()
        _seen.clear()
        _counter = itertools.count()
    with _conn_lock:
        _conn_gen.clear()
        _conn_open.clear()
    _handlers.clear()
    _handlers.update(_DEFAULT_HANDLERS)
    if game._phase_hook is _on_phase_change:
        game.set_on_phase_change(None)
    _installed = False
    set_clock(None)
    _sweep_armed = False


_DEFAULT_HANDLERS: Dict[str, Handler] = {
    "phase_timeout": _phase_timeout,
    "mark_disconnected": _mark_disconnected,
    "sweep": _sweep_handler,
}
_handlers.update(_DEFAULT_HANDLERS)
