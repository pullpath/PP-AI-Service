"""Superadmin surface for spy-hunt operational actions (design: admin-refill spec).

Shared-secret auth (reuses the existing ADMIN_TOKEN), token via the
X-Admin-Token header only. Actions run on the shared worker pool, never
blocking the request.
"""
from __future__ import annotations

import hmac
import logging
import threading
from functools import wraps

from flask import jsonify, request

from ai_svc.dictionary.cache_routes import get_admin_token
from ai_svc.spy_hunt import puzzle_gen, puzzles, workers

log = logging.getLogger("spy_hunt.admin")

MAX_REFILL = 50
DEFAULT_REFILL = 3

_lock = threading.Lock()
_refilling = False


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-Admin-Token", "").encode("utf-8")
        if not hmac.compare_digest(provided, get_admin_token().encode("utf-8")):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


def admin_status() -> dict:
    with _lock:
        refilling = _refilling
    return {"ready_count": puzzles.ready_count(),
            "total_count": puzzles.total_count(), "refilling": refilling}


def _run_fill(target: int) -> None:
    global _refilling
    try:
        puzzle_gen.fill_queue(target=target, log=log.info)
    finally:
        with _lock:
            _refilling = False


def start_refill(count: int = DEFAULT_REFILL) -> dict:
    global _refilling
    if type(count) is not int or not 1 <= count <= MAX_REFILL:
        raise ValueError(f"count must be an integer from 1 to {MAX_REFILL}")
    with _lock:
        if _refilling:
            return {"started": False, "refilling": True}
        _refilling = True
    target = puzzles.ready_count() + count
    workers.submit(_run_fill, target)
    return {"started": True}
