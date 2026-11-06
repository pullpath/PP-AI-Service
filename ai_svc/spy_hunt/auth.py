from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from functools import wraps

from flask import g, jsonify, request

from ai_svc.spy_hunt.db import get_conn


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_guest() -> tuple[str, str]:
    player_id = secrets.token_urlsafe(9)
    token = secrets.token_urlsafe(32)
    conn = get_conn()
    conn.execute(
        "INSERT INTO guests(player_id, token_hash, created_at) VALUES(?,?,?)",
        (player_id, hash_token(token), int(time.time())),
    )
    conn.commit()
    return player_id, token


def _unauthorized():
    return jsonify({"error": "unauthorized"}), 401


def require_guest(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, cred = header.partition(" ")
        if scheme != "Bearer":
            return _unauthorized()
        player_id, _, token = cred.partition(".")
        if not player_id or not token:
            return _unauthorized()
        row = get_conn().execute(
            "SELECT token_hash FROM guests WHERE player_id=?", (player_id,)
        ).fetchone()
        stored = row["token_hash"] if row else hash_token("")
        ok = hmac.compare_digest(stored, hash_token(token))
        if row is None or not ok:
            return _unauthorized()
        g.player_id = player_id
        return fn(*args, **kwargs)
    return wrapper
