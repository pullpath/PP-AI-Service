"""Small shared worker pool (translation now, bots/host in Task 10).

4 daemon threads started lazily. `submit(fn, *a, **kw) -> Future`; an exception
in a job is logged (never swallowed silently) and stored on the Future.
Tests: `set_synchronous(True)` runs jobs inline in the caller's thread and
`reset()` drops queued jobs and stops the threads.
"""
from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, List

log = logging.getLogger("spy_hunt.workers")

POOL_SIZE = 4

_lock = threading.Lock()
_queue: "queue.Queue" = queue.Queue()
_threads: List[threading.Thread] = []
_synchronous = False


def set_synchronous(flag: bool) -> None:
    global _synchronous
    _synchronous = bool(flag)


def is_synchronous() -> bool:
    return _synchronous


def _run(fut: Future, fn: Callable, args: tuple, kwargs: dict) -> None:
    if not fut.set_running_or_notify_cancel():
        return
    try:
        fut.set_result(fn(*args, **kwargs))
    except BaseException as e:  # noqa: BLE001 - logged and kept on the future
        log.exception("worker job %s failed", getattr(fn, "__name__", fn))
        fut.set_exception(e)


def _loop(q: "queue.Queue") -> None:
    while True:
        item = q.get()
        if item is None:
            return
        _run(*item)


def _ensure_threads() -> None:
    with _lock:
        _threads[:] = [t for t in _threads if t.is_alive()]
        while len(_threads) < POOL_SIZE:
            t = threading.Thread(target=_loop, args=(_queue,), daemon=True,
                                 name=f"spy-hunt-worker-{len(_threads)}")
            t.start()
            _threads.append(t)


def submit(fn: Callable, *args: Any, **kwargs: Any) -> Future:
    fut: Future = Future()
    if _synchronous:
        _run(fut, fn, args, kwargs)
        return fut
    _ensure_threads()
    _queue.put((fut, fn, args, kwargs))
    return fut


def shutdown() -> None:
    """Stop the threads (they finish their current job) and drop queued jobs."""
    global _queue
    with _lock:
        old, threads = _queue, list(_threads)
        _threads.clear()
        _queue = queue.Queue()
    try:
        while True:
            old.get_nowait()
    except queue.Empty:
        pass
    for _ in threads:
        old.put(None)


def reset() -> None:
    shutdown()
    set_synchronous(False)
