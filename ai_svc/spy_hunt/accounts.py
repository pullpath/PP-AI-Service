"""Account/password logic: attaching an email+password to an existing guest."""
from __future__ import annotations

import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from ai_svc.spy_hunt import auth, store
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.store import StoreError

MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 1024
# Registered accounts only: an unregistered guest's token is their sole way back, so it never expires.
SESSION_TTL_SECONDS = 90 * 24 * 3600
MAX_SESSIONS = 20
# Failed-login budget per account, on top of the per-IP limit, so spreading attempts over many IPs doesn't help.
# Checked *before* the password, so a correct guess after the budget is spent is refused too.
# Trade-off: someone can lock a known email out of logging in for the window.
ACCOUNT_FAIL_LIMIT = 10
ACCOUNT_FAIL_WINDOW = 15 * 60
_fails: Dict[str, deque] = defaultdict(deque)
_fails_lock = threading.Lock()


def _locked(email: str) -> bool:
    with _fails_lock:
        hits = _fails[email]
        while hits and time.time() - hits[0] > ACCOUNT_FAIL_WINDOW:
            hits.popleft()
        if not hits:
            _fails.pop(email, None)
            return False
        return len(hits) >= ACCOUNT_FAIL_LIMIT


def _record_fail(email: str) -> None:
    with _fails_lock:
        _fails[email].append(time.time())


def reset_login_fails() -> None:
    with _fails_lock:
        _fails.clear()
MAX_EMAIL_LEN = 254
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Checked against when the email is unknown, so a miss costs the same as a wrong password.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def check_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def normalize_email(email: Any) -> str:
    if not isinstance(email, str):
        raise StoreError(400, "bad_email", "Email must be a string.")
    cleaned = email.strip().lower()
    if len(cleaned) > MAX_EMAIL_LEN or not _EMAIL_RE.match(cleaned):
        raise StoreError(400, "bad_email", "Email must be a valid address.")
    return cleaned


def register(player_id: str, email: Any, password: Any) -> Dict[str, str]:
    email = normalize_email(email)
    if (not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN
            or len(password) > MAX_PASSWORD_LEN):
        raise StoreError(400, "bad_password",
                         f"Password must be {MIN_PASSWORD_LEN} to {MAX_PASSWORD_LEN} characters.")
    conn = get_conn()
    rows = conn.execute(
        "SELECT player_id, email FROM guests WHERE player_id=? OR email=?",
        (player_id, email),
    ).fetchall()
    own = next((r for r in rows if r["player_id"] == player_id), None)
    taken_by_other = any(r["player_id"] != player_id and r["email"] == email for r in rows)
    if (own is not None and own["email"] is not None) or taken_by_other:
        raise StoreError(409, "conflict", "This guest or email is already registered.")
    conflict = StoreError(409, "conflict", "This guest or email is already registered.")
    try:
        # email IS NULL makes the write itself the check, so a concurrent request can't overwrite
        cur = conn.execute(
            "UPDATE guests SET email=?, password_hash=? WHERE player_id=? AND email IS NULL",
            (email, hash_password(password), player_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise conflict
    if cur.rowcount != 1:
        raise conflict
    return {"email": email}


def login(email: Any, password: Any) -> Dict[str, str]:
    email = normalize_email(email)
    if _locked(email):
        raise StoreError(429, "rate_limited", "Too many attempts, try again later.")
    conn = get_conn()
    row = conn.execute(
        "SELECT player_id, password_hash, preferred_lang FROM guests WHERE email=?", (email,)
    ).fetchone()
    # Never reveal whether the email or the password was wrong.
    stored = row["password_hash"] if row is not None and row["password_hash"] else _DUMMY_HASH
    ok = isinstance(password, str) and check_password(password, stored)
    bad = row is None or not row["password_hash"] or not ok
    if bad:
        _record_fail(email)
        raise StoreError(401, "unauthorized", "Invalid email or password.")
    player_id = row["player_id"]
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn.execute(
        "INSERT INTO sessions(token_hash, player_id, created_at) VALUES(?,?,?)",
        (auth.hash_token(token), player_id, now),
    )
    _prune_sessions(conn, player_id, now)
    conn.commit()
    return {"player_id": player_id, "token": token, "email": email,
            "preferred_lang": row["preferred_lang"]}


def _prune_sessions(conn, player_id: str, now: int) -> None:
    # Only reached through a successful login, so the player has an account.
    conn.execute("DELETE FROM sessions WHERE player_id=? AND created_at<?",
                 (player_id, now - SESSION_TTL_SECONDS))
    conn.execute(
        "DELETE FROM sessions WHERE player_id=? AND token_hash NOT IN ("
        " SELECT token_hash FROM sessions WHERE player_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
        (player_id, player_id, MAX_SESSIONS),
    )


def logout(token_hash: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    conn.commit()


def me(player_id: str) -> Dict[str, Optional[str]]:
    row = get_conn().execute(
        "SELECT email, preferred_lang FROM guests WHERE player_id=?", (player_id,)
    ).fetchone()
    return {"email": row["email"] if row else None,
            "preferred_lang": row["preferred_lang"] if row else None}


def update_me(player_id: str, lang: Any) -> Dict[str, Any]:
    lang = store.check_lang(lang)
    get_conn().execute("UPDATE guests SET preferred_lang=? WHERE player_id=?", (lang, player_id))
    get_conn().commit()
    return {"ok": True, "preferred_lang": lang}
