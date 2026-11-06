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
}

_LIMITERS = {n: RateLimiter(m, 60) for n, (m, _) in _SPECS.items()}


def client_ip() -> str:
    return request.headers.get("X-Real-IP") or request.remote_addr or "unknown"


def reset_all() -> None:
    for lim in _LIMITERS.values():
        lim.reset()


def limit(name: str):
    """Rate-limit decorator. Per-guest limits need g.player_id (use after
    require_guest); they fall back to the IP if it is absent."""
    if name not in _SPECS:
        raise KeyError(name)
    limiter = _LIMITERS[name]
    scope = _SPECS[name][1]

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = client_ip()
            if scope == "guest":
                key = getattr(g, "player_id", None) or key
            if limiter.is_limited(key):
                return jsonify({
                    "error": "rate_limited",
                    "message": "Too many requests, slow down.",
                }), 429
            return fn(*args, **kwargs)
        return wrapper
    return deco
