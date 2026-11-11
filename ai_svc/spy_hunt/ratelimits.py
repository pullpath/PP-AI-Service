from __future__ import annotations

from functools import wraps

from flask import g, jsonify, request

from ai_svc.rate_limit import RateLimiter

# name -> (max per minute, keyed by "ip" | "guest")
_SPECS = {
    "guest_create": (40, "ip"),
    "room_create": (5, "guest"),
    "action": (30, "guest"),
    "read": (60, "guest"),
    "flood": (200, "ip"),
    "login": (20, "ip"),
}

_LIMITERS = {n: RateLimiter(m, 60) for n, (m, _) in _SPECS.items()}


def client_ip() -> str:
    return request.headers.get("X-Real-IP") or request.remote_addr or "unknown"


def bucket_key(scope: str) -> str:
    if scope == "guest":
        player_id = getattr(g, "player_id", None)
        if not player_id:
            raise RuntimeError("per-guest limit used without require_guest")
        return f"guest:{player_id}"
    return f"ip:{client_ip()}"


def reset_all() -> None:
    from ai_svc.spy_hunt import accounts
    accounts.reset_login_fails()
    for lim in _LIMITERS.values():
        lim.reset()


def limit(name: str):
    """Rate-limit decorator. Per-guest limits need g.player_id, so place
    them below @require_guest; otherwise RuntimeError is raised."""
    if name not in _SPECS:
        raise KeyError(name)
    limiter = _LIMITERS[name]
    scope = _SPECS[name][1]

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = bucket_key(scope)
            if limiter.is_limited(key):
                return jsonify({
                    "error": "rate_limited",
                    "message": "Too many requests, slow down.",
                }), 429
            return fn(*args, **kwargs)
        return wrapper
    return deco
