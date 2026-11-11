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


def test_login_returns_a_new_token_for_the_player(client):
    guest = _make_guest(client)
    client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough"},
        headers=_auth_header(guest),
    )
    r = client.post("/api/spy-hunt/login", json={"email": "a@b.com", "password": "longenough"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["player_id"] == guest["player_id"]
    assert body["token"] and body["token"] != guest["token"]
    me = client.get("/api/spy-hunt/me", headers=_auth_header(body))
    assert me.status_code == 200


def test_login_does_not_evict_the_original_token(client):
    guest = _make_guest(client)
    client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough"},
        headers=_auth_header(guest),
    )
    r = client.post("/api/spy-hunt/login", json={"email": "a@b.com", "password": "longenough"})
    assert r.status_code == 200
    original_still_works = client.get("/api/spy-hunt/me", headers=_auth_header(guest))
    assert original_still_works.status_code == 200


def test_login_wrong_password_or_unknown_email_is_401(client):
    guest = _make_guest(client)
    client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough"},
        headers=_auth_header(guest),
    )
    wrong_password = client.post(
        "/api/spy-hunt/login", json={"email": "a@b.com", "password": "nope-not-it"}
    )
    assert wrong_password.status_code == 401
    assert wrong_password.get_json()["error"] == "unauthorized"
    unknown_email = client.post(
        "/api/spy-hunt/login", json={"email": "nobody@b.com", "password": "longenough"}
    )
    assert unknown_email.status_code == 401
    assert unknown_email.get_json()["error"] == "unauthorized"


def test_login_rate_limit_is_by_ip(client):
    for _ in range(20):
        r = client.post(
            "/api/spy-hunt/login", json={"email": "nobody@b.com", "password": "whatever1"}
        )
        assert r.status_code == 401
    r = client.post(
        "/api/spy-hunt/login", json={"email": "nobody@b.com", "password": "whatever1"}
    )
    assert r.status_code == 429
    assert r.get_json()["error"] == "rate_limited"
    # a different IP is unaffected
    r2 = client.post(
        "/api/spy-hunt/login",
        json={"email": "nobody@b.com", "password": "whatever1"},
        headers={"X-Real-IP": "9.9.9.9"},
    )
    assert r2.status_code == 401


def test_logout_removes_only_the_calling_devices_session(client):
    guest = _make_guest(client)
    client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough"},
        headers=_auth_header(guest),
    )
    login = client.post(
        "/api/spy-hunt/login", json={"email": "a@b.com", "password": "longenough"}
    )
    second_token = login.get_json()
    r = client.post("/api/spy-hunt/logout", headers=_auth_header(guest))
    assert r.status_code == 200
    first_me = client.get("/api/spy-hunt/me", headers=_auth_header(guest))
    assert first_me.status_code == 401
    second_me = client.get("/api/spy-hunt/me", headers=_auth_header(second_token))
    assert second_me.status_code == 200


def test_logout_is_idempotent(client):
    guest = _make_guest(client)
    r1 = client.post("/api/spy-hunt/logout", headers=_auth_header(guest))
    assert r1.status_code == 200
    assert r1.get_json() == {"ok": True}
    r2 = client.post("/api/spy-hunt/logout", headers=_auth_header(guest))
    assert r2.status_code == 401


def test_me_reports_email_or_null(client):
    guest = _make_guest(client)
    r = client.get("/api/spy-hunt/me", headers=_auth_header(guest))
    assert r.status_code == 200
    assert r.get_json() == {"email": None}
    client.post(
        "/api/spy-hunt/register",
        json={"email": "a@b.com", "password": "longenough"},
        headers=_auth_header(guest),
    )
    r2 = client.get("/api/spy-hunt/me", headers=_auth_header(guest))
    assert r2.status_code == 200
    assert r2.get_json() == {"email": "a@b.com"}


def test_logged_out_token_stays_dead_after_init_db(client, conn):
    from ai_svc.spy_hunt import db

    guest = _make_guest(client)
    assert client.post("/api/spy-hunt/logout", headers=_auth_header(guest)).status_code == 200
    assert client.get("/api/spy-hunt/me", headers=_auth_header(guest)).status_code == 401
    db.init_db()  # runs on every process start and from the cron scripts
    assert client.get("/api/spy-hunt/me", headers=_auth_header(guest)).status_code == 401
