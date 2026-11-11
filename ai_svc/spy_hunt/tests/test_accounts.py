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
    for i in range(20):  # a different email each time, so only the IP budget is in play
        r = client.post(
            "/api/spy-hunt/login", json={"email": f"nobody{i}@b.com", "password": "whatever1"}
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


def _register(client, guest, email, password="longenough"):
    return client.post("/api/spy-hunt/register", json={"email": email, "password": password},
                       headers=_auth_header(guest))


def test_register_does_not_overwrite_when_the_same_guest_registers_concurrently(client, conn, monkeypatch):
    from ai_svc.spy_hunt import accounts

    guest = _make_guest(client)
    real = accounts.hash_password

    def hash_then_lose_the_race(pw):
        # a second tab's request lands between our check and our write
        conn.execute("UPDATE guests SET email='first@x.com', password_hash='h' WHERE player_id=?",
                     (guest["player_id"],))
        conn.commit()
        return real(pw)

    monkeypatch.setattr(accounts, "hash_password", hash_then_lose_the_race)
    assert _register(client, guest, "second@x.com").status_code == 409
    row = conn.execute("SELECT email FROM guests WHERE player_id=?", (guest["player_id"],)).fetchone()
    assert row["email"] == "first@x.com"


def test_register_concurrent_duplicate_email_is_409_not_500(client, conn, monkeypatch):
    from ai_svc.spy_hunt import accounts

    me, other = _make_guest(client), _make_guest(client)
    real = accounts.hash_password

    def hash_then_lose_the_race(pw):
        conn.execute("UPDATE guests SET email='dup@x.com', password_hash='h' WHERE player_id=?",
                     (other["player_id"],))
        conn.commit()
        return real(pw)

    monkeypatch.setattr(accounts, "hash_password", hash_then_lose_the_race)
    assert _register(client, me, "dup@x.com").status_code == 409


def test_login_checks_a_hash_even_for_an_unknown_email(client, monkeypatch):
    from ai_svc.spy_hunt import accounts

    calls = []
    real = accounts.check_password
    monkeypatch.setattr(accounts, "check_password", lambda pw, h: calls.append(h) or real(pw, h))
    r = client.post("/api/spy-hunt/login", json={"email": "nobody@x.com", "password": "whatever1"})
    assert r.status_code == 401
    assert len(calls) == 1


import pytest  # noqa: E402


@pytest.mark.parametrize("email", ["@", "a@", "@b.com", "a b@c.com", "a@@b.com", "a" * 250 + "@b.com"])
def test_register_rejects_malformed_or_oversized_email(client, email):
    assert _register(client, _make_guest(client), email).get_json()["error"] == "bad_email"


def test_register_rejects_an_oversized_password(client):
    r = _register(client, _make_guest(client), "a@b.com", password="x" * 1025)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_password"


def test_password_hash_round_trip():
    from ai_svc.spy_hunt import accounts

    h = accounts.hash_password("correct horse")
    assert h != "correct horse"
    assert accounts.check_password("correct horse", h) is True
    assert accounts.check_password("wrong horse", h) is False


def _registered(client):
    guest = _make_guest(client)
    assert _register(client, guest, "acct@x.com").status_code == 200
    return guest


def _login(client, password="longenough", ip="1.1.1.1", email="acct@x.com"):
    return client.post("/api/spy-hunt/login", json={"email": email, "password": password},
                       headers={"X-Real-IP": ip})


def test_login_is_limited_per_account_across_ips(client):
    _registered(client)
    codes = [_login(client, "wrong-pass1", ip=f"10.0.0.{i}").status_code for i in range(12)]
    assert codes[:10] == [401] * 10
    assert 429 in codes[10:]
    # other accounts and the right password from a fresh account bucket are unaffected
    assert _login(client, "longenough", email="other@x.com", ip="10.9.9.9").status_code == 401


def test_a_locked_account_rejects_even_the_correct_password(client):
    _registered(client)
    for i in range(10):
        _login(client, "wrong-pass1", ip=f"10.1.0.{i}")
    # the guess that would have been right must not get through once the budget is spent
    assert _login(client, "longenough", ip="10.1.1.1").status_code == 429


def test_login_keeps_only_the_newest_sessions(client, conn):
    guest = _registered(client)
    from ai_svc.spy_hunt import accounts
    import time
    recent = int(time.time()) - 3600
    for i in range(accounts.MAX_SESSIONS + 5):
        conn.execute("INSERT INTO sessions(token_hash, player_id, created_at) VALUES(?,?,?)",
                     (f"old{i}", guest["player_id"], recent + i))
    conn.commit()
    assert _login(client).status_code == 200
    n = conn.execute("SELECT COUNT(*) c FROM sessions WHERE player_id=?", (guest["player_id"],)).fetchone()["c"]
    assert n == accounts.MAX_SESSIONS


def test_login_drops_expired_sessions_of_registered_accounts_only(client, conn):
    from ai_svc.spy_hunt import accounts
    reg = _registered(client)
    plain = _make_guest(client)
    ancient = 1000
    for pid in (reg["player_id"], plain["player_id"]):
        conn.execute("INSERT INTO sessions(token_hash, player_id, created_at) VALUES(?,?,?)",
                     (f"ancient-{pid}", pid, ancient))
    conn.commit()
    assert _login(client).status_code == 200
    gone = conn.execute("SELECT 1 FROM sessions WHERE token_hash=?", (f"ancient-{reg['player_id']}",)).fetchone()
    kept = conn.execute("SELECT 1 FROM sessions WHERE token_hash=?", (f"ancient-{plain['player_id']}",)).fetchone()
    assert gone is None
    assert kept is not None  # an unregistered guest's token is their only way back; it never expires
    assert accounts.SESSION_TTL_SECONDS > 0
