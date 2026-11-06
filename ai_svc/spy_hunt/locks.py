"""Per-room re-entrant locks. Valid only because the service is one process."""
from __future__ import annotations

import threading

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def room_lock(room_id: str) -> threading.RLock:
    with _guard:
        lock = _locks.get(room_id)
        if lock is None:
            lock = _locks[room_id] = threading.RLock()
        return lock


def forget(room_id: str) -> None:
    """Drop a finished room's lock (for the maintenance sweep)."""
    with _guard:
        _locks.pop(room_id, None)
