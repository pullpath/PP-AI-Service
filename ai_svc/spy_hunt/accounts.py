"""Account/password logic: attaching an email+password to an existing guest."""
from __future__ import annotations

import secrets
import time
from typing import Any, Dict, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from ai_svc.spy_hunt import auth
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.store import StoreError

MIN_PASSWORD_LEN = 8


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def check_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def normalize_email(email: Any) -> str:
    if not isinstance(email, str):
        raise StoreError(400, "bad_email", "Email must be a string.")
    cleaned = email.strip().lower()
    if not cleaned or "@" not in cleaned:
        raise StoreError(400, "bad_email", "Email must be a valid address.")
    return cleaned


def register(player_id: str, email: Any, password: Any) -> Dict[str, str]:
    email = normalize_email(email)
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise StoreError(400, "bad_password",
                         f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    conn = get_conn()
    rows = conn.execute(
        "SELECT player_id, email FROM guests WHERE player_id=? OR email=?",
        (player_id, email),
    ).fetchall()
    own = next((r for r in rows if r["player_id"] == player_id), None)
    taken_by_other = any(r["player_id"] != player_id and r["email"] == email for r in rows)
    if (own is not None and own["email"] is not None) or taken_by_other:
        raise StoreError(409, "conflict", "This guest or email is already registered.")
    conn.execute(
        "UPDATE guests SET email=?, password_hash=? WHERE player_id=?",
        (email, hash_password(password), player_id),
    )
    conn.commit()
    return {"email": email}


def login(email: Any, password: Any) -> Dict[str, str]:
    email = normalize_email(email)
    conn = get_conn()
    row = conn.execute(
        "SELECT player_id, password_hash FROM guests WHERE email=?", (email,)
    ).fetchone()
    # Never reveal whether the email or the password was wrong.
    bad = (
        row is None
        or not isinstance(password, str)
        or not check_password(password, row["password_hash"])
    )
    if bad:
        raise StoreError(401, "unauthorized", "Invalid email or password.")
    player_id = row["player_id"]
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions(token_hash, player_id, created_at) VALUES(?,?,?)",
        (auth.hash_token(token), player_id, int(time.time())),
    )
    conn.commit()
    return {"player_id": player_id, "token": token, "email": email}


def logout(token_hash: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    conn.commit()


def me(player_id: str) -> Dict[str, Optional[str]]:
    row = get_conn().execute(
        "SELECT email FROM guests WHERE player_id=?", (player_id,)
    ).fetchone()
    return {"email": row["email"] if row else None}
