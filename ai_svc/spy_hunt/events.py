"""SSE streaming and in-process wake-ups (impl spec §3, §7.1).

- `notify(room_id)`: called by store.tx AFTER the outermost transaction that
  appended an event commits (never before, never on rollback). Wakes every
  stream waiting on that room.
- `acquire_slot(player_id)`: stream caps (MAX_PER_GUEST per guest,
  MAX_TOTAL overall). Returns an idempotent release callable, or None when full.
- `stream(room_id, player_id, after, release)`: the generator behind
  `GET /rooms/<code>/events`.

The stream sends each event only if `visibility.visible_to(event, my_seat)`;
it has no audience logic of its own. It never holds a DB transaction across a
wait or a yield: each loop does one short read transaction (seat + events
read from the same snapshot) and ends it.

Valid only in one process (impl spec §3): the conditions live in memory.
Tests override PING_INTERVAL_S / MAX_STREAM_S / MAX_PER_GUEST / MAX_TOTAL.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from ai_svc.spy_hunt import store, timers, visibility
from ai_svc.spy_hunt.db import get_conn

log = logging.getLogger(__name__)

PING_INTERVAL_S = 15.0
MAX_STREAM_S = 30 * 60.0
MAX_PER_GUEST = 4
MAX_TOTAL = 200
BATCH = 200  # events read per query
_MAX_CURSOR = 2 ** 62  # keeps any cursor we ever bind to SQLite in range


# ---- wake-ups ----

class _Room:
    __slots__ = ("cond", "gen", "waiters")

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.gen = 0  # bumped by every notify; a waiter compares before sleeping
        self.waiters = 0  # open streams on this room


_rooms_guard = threading.Lock()
_rooms: Dict[str, _Room] = {}


def _join(room_id: str) -> _Room:
    with _rooms_guard:
        r = _rooms.get(room_id)
        if r is None:
            r = _rooms[room_id] = _Room()
        r.waiters += 1
        return r


def _part(room_id: str, r: _Room) -> None:
    with _rooms_guard:
        r.waiters -= 1
        if r.waiters <= 0 and _rooms.get(room_id) is r:
            del _rooms[room_id]


def notify(room_id: str) -> None:
    """New committed events for `room_id`: wake its streams. Never blocks long."""
    with _rooms_guard:
        r = _rooms.get(room_id)
    if r is None:
        return  # nobody listening
    with r.cond:
        r.gen += 1
        r.cond.notify_all()


# ---- stream caps ----

_slots_lock = threading.Lock()
_per_guest: Dict[str, int] = {}
_total = 0


def acquire_slot(player_id: str) -> Optional[Callable[[], None]]:
    """Reserve a stream slot. Returns a release function (safe to call many
    times; only the first call releases), or None if a cap is reached."""
    global _total
    with _slots_lock:
        if _total >= MAX_TOTAL or _per_guest.get(player_id, 0) >= MAX_PER_GUEST:
            return None
        _total += 1
        _per_guest[player_id] = _per_guest.get(player_id, 0) + 1

    done = [False]
    once = threading.Lock()

    def release() -> None:
        global _total
        with once:
            if done[0]:
                return
            done[0] = True
        with _slots_lock:
            _total -= 1
            left = _per_guest.get(player_id, 0) - 1
            if left > 0:
                _per_guest[player_id] = left
            else:
                _per_guest.pop(player_id, None)
    return release


def open_streams() -> Tuple[int, Dict[str, int]]:
    """(total, per-guest counts) of reserved slots. For tests and diagnostics."""
    with _slots_lock:
        return _total, dict(_per_guest)


# ---- cursor ----

def parse_cursor(*values: Any) -> int:
    """The largest valid non-negative integer among `values`; junk counts as 0."""
    best = 0
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if not s.isascii() or not s.isdigit():
            continue
        best = max(best, min(int(s), _MAX_CURSOR))
    return best


# ---- framing ----

def frame(seq: int, type: str, data_json: str) -> str:
    return f"id: {seq}\nevent: {type}\ndata: {data_json}\n\n"


PING = ": ping\n\n"
OPEN = ": connected\n\n"


# ---- DB reads (each one short; no transaction survives the call) ----

def _read(fn):
    conn = get_conn()
    if conn.in_transaction:  # joined an outer tx (not expected on a stream thread)
        return fn(conn)
    conn.execute("BEGIN")
    try:
        return fn(conn)
    finally:
        conn.rollback()  # read-only


def _batch(room_id: str, player_id: str, after: int) -> Tuple[Optional[int], List[Dict[str, Any]]]:
    """(my current seat or None, events with seq > after), from one snapshot.
    Seat is re-read every time: start_game compacts and shuffles seats."""
    def q(conn):
        seat = store.seat_of(room_id, player_id, conn)
        rows = conn.execute(
            "SELECT seq, type, payload_json, audience FROM events"
            " WHERE room_id=? AND seq>? ORDER BY seq LIMIT ?",
            (room_id, after, BATCH)).fetchall()
        return seat, [dict(r) for r in rows]
    return _read(q)


def _needs_state(room_id: str, after: int) -> bool:
    """True when `after` cannot be resumed from retained events.

    Seqs are global (AUTOINCREMENT over all rooms), so a room's first event is
    not seq 1, and a valid cursor is either 0 or the seq of one of THIS room's
    retained events. Pruning (Task 6 sweep) deletes a prefix, so:
    - after > 0 and not a retained seq of this room: too old (pruned), beyond
      the last seq (stale), or another room's cursor -> state.
    - after == 0 (full history): complete unless the room has no events left
      (all dropped) or may have been pruned. The sweep only ever trims a room
      to exactly timers.EVENTS_KEEP, so a room with fewer retained events was
      never trimmed; at or above it we send a state (always correct, just
      larger) rather than risk a gap. A room whose events were all dropped
      and then refilled (rematch) starts with something other than the
      room-creation `player_joined`, which also yields a state.
    """
    def q(conn):
        if after > 0:
            row = conn.execute("SELECT 1 FROM events WHERE room_id=? AND seq=?",
                               (room_id, after)).fetchone()
            return row is None
        count = conn.execute("SELECT COUNT(*) FROM events WHERE room_id=?",
                             (room_id,)).fetchone()[0]
        if count == 0 or count >= timers.EVENTS_KEEP:
            return True
        first = conn.execute("SELECT type FROM events WHERE room_id=? ORDER BY seq LIMIT 1",
                             (room_id,)).fetchone()
        # create_room's own tx always appends the host's player_joined first
        return first["type"] != "player_joined"
    return _read(q)


def _state_frame(room_id: str, player_id: str) -> Optional[Tuple[int, str]]:
    """(last_seq, frame) of a personal `state` event, or None if not a member."""
    try:
        snap = visibility.build_snapshot(room_id, player_id)
    except LookupError:
        return None
    seat = snap["me"]["seat"]
    event = {"seq": snap["last_seq"], "type": "state", "audience": f"seat:{seat}"}
    visibility.check_event_payload("state", snap, event["audience"])
    if not visibility.visible_to(event, seat):
        return None
    return snap["last_seq"], frame(snap["last_seq"], "state",
                                   json.dumps(snap, ensure_ascii=False))


def _mark_connected(room_id: str, player_id: str, noted: List[bool]) -> bool:
    """Count the stream in timers and set connected=1 (player_updated if it
    changed), under the room lock. False if the player is no longer a member.
    `noted[0]` becomes True as soon as timers.note_connected ran, so the
    caller's `finally` balances it even if the transaction then fails."""
    with store.tx(room_id) as conn:
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        seat = store.seat_of(room_id, player_id, conn)
        if room is None or seat is None:
            return False
        # inside the lock: timers._mark_disconnected re-checks under it
        timers.note_connected(room_id, player_id)
        noted[0] = True
        cur = conn.execute(
            "UPDATE players SET connected=1 WHERE room_id=? AND seat=? AND connected=0",
            (room_id, seat))
        if cur.rowcount:
            store._bump(conn, room_id)
            store._emit_player(conn, dict(room), seat, "player_updated")
    return True


# ---- the stream ----

def stream(room_id: str, player_id: str, after: int,
           release: Callable[[], None]) -> Iterator[str]:
    """SSE generator. `release` (from acquire_slot) is called exactly once in
    `finally`, also when the client vanishes (GeneratorExit / BrokenPipe)."""
    noted = [False]
    room = _join(room_id)
    try:
        deadline = time.monotonic() + MAX_STREAM_S
        cursor = after
        state = None
        if _needs_state(room_id, cursor):
            state = _state_frame(room_id, player_id)
            if state is None:
                return
            cursor = state[0]
        if not _mark_connected(room_id, player_id, noted):
            return
        yield OPEN
        if state is not None:
            yield state[1]
        while True:
            with room.cond:
                seen_gen = room.gen
            seat, rows = _batch(room_id, player_id, cursor)
            for ev in rows:
                cursor = ev["seq"]
                if visibility.visible_to(ev, seat):
                    yield frame(ev["seq"], ev["type"], ev["payload_json"])
            if seat is None:
                return  # left the room (or replaced by a bot): nothing more for us
            if len(rows) >= BATCH:
                continue  # more backlog
            left = deadline - time.monotonic()
            if left <= 0:
                return
            with room.cond:
                if room.gen == seen_gen:
                    room.cond.wait(min(PING_INTERVAL_S, left))
                woke = room.gen != seen_gen
            if not woke and time.monotonic() < deadline:
                yield PING  # a full interval with no wake-up
    finally:
        try:
            if noted[0]:
                timers.note_disconnected(room_id, player_id)
        except Exception:
            log.exception("events: note_disconnected failed for room %s", room_id)
        finally:
            _part(room_id, room)
            release()


class Body:
    """The WSGI response iterable for a stream. `close()` also releases the
    slot, which matters if the server closes the response before ever starting
    the generator (a never-started generator does not run its `finally`)."""

    def __init__(self, gen: Iterator[str], release: Callable[[], None]):
        self._gen = gen
        self._release = release

    def __iter__(self):
        return self._gen

    def close(self) -> None:
        try:
            self._gen.close()
        finally:
            self._release()


def reset() -> None:
    """Tests: forget wake-up state and slot counts."""
    global _total
    with _rooms_guard:
        _rooms.clear()
    with _slots_lock:
        _per_guest.clear()
        _total = 0
