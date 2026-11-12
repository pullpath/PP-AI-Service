"""Superadmin surface for spy-hunt operational actions (design: admin-refill spec).

Shared-secret auth (reuses the existing ADMIN_TOKEN), token via the
X-Admin-Token header only. Actions run on the shared worker pool, never
blocking the request.
"""
from __future__ import annotations

import hmac
import logging
from functools import wraps

from flask import jsonify, request

from ai_svc.dictionary.cache_routes import get_admin_token

log = logging.getLogger("spy_hunt.admin")


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(provided, get_admin_token()):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper
