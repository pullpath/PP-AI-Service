from __future__ import annotations


def _make_guest(client, **kw):
    r = client.post("/api/spy-hunt/guests", **kw)
    assert r.status_code == 200
    return r.get_json()


def _auth_header(guest):
    return {"Authorization": f"Bearer {guest['player_id']}.{guest['token']}"}


def test_register_requires_guest_token(client):
    r = client.post("/api/spy-hunt/register", json={"email": "a@b.com", "password": "longenough"})
    assert r.status_code == 401


def test_register_attaches_email_to_the_current_guest(client, conn):
    guest = _make_guest(client)
    r = client.post(
        "/api/spy-hunt/register",
        json={"email": "A@Example.com ", "password": "longenough"},
        headers=_auth_header(guest),
    )
    assert r.status_code == 200
    assert r.get_json() == {"email": "a@example.com"}
    row = conn.execute(
        "SELECT email, password_hash FROM guests WHERE player_id=?", (guest["player_id"],)
    ).fetchone()
    assert row["email"] == "a@example.com"
    assert row["password_hash"]
    assert row["password_hash"] != "longenough"


def test_register_rejects_bad_email(client):
    guest = _make_guest(client)
    r = client.post(
        "/api/spy-hunt/register",
        json={"email": "not-an-email", "password": "longenough"},
        headers=_auth_header(guest),
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "bad_email"


def test_register_rejects_short_password(client):
    guest = _make_guest(client)
    r = client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "short"},
        headers=_auth_header(guest),
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "bad_password"


def test_register_conflict_on_duplicate_email(client):
    first, second = _make_guest(client), _make_guest(client)
    r1 = client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough"},
        headers=_auth_header(first),
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough2"},
        headers=_auth_header(second),
    )
    assert r2.status_code == 409
    assert r2.get_json()["error"] == "conflict"


def test_register_conflict_on_already_registered_guest(client):
    guest = _make_guest(client)
    r1 = client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough"},
        headers=_auth_header(guest),
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/spy-hunt/register",
        json={"email": "different@b.com", "password": "longenough2"},
        headers=_auth_header(guest),
    )
    assert r2.status_code == 409
    assert r2.get_json()["error"] == "conflict"
