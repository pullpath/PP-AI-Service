"""Account/password logic: attaching an email+password to an existing guest."""
from __future__ import annotations

from typing import Any, Dict

from werkzeug.security import check_password_hash, generate_password_hash

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
