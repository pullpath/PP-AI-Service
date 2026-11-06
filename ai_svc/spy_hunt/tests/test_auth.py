from __future__ import annotations

from flask import g, jsonify

from ai_svc.spy_hunt import auth, ratelimits


def _make_guest(client, **kw):
    r = client.post("/api/spy-hunt/guests", **kw)
    assert r.status_code == 200
    return r.get_json()


def test_create_guest_returns_ids(client):
    body = _make_guest(client)
    assert body["player_id"] and body["token"]


def test_token_not_stored_plain(client, conn):
    body = _make_guest(client)
    row = conn.execute(
        "SELECT token_hash FROM guests WHERE player_id=?", (body["player_id"],)
    ).fetchone()
    assert row["token_hash"] != body["token"]
    assert len(row["token_hash"]) == 64


def _protected_client(client):
    app = client.application

    @app.route("/_t/me")
    @auth.require_guest
    def me():
        return jsonify({"pid": g.player_id})

    return app.test_client()


def test_require_guest_ok_and_failures(client):
    c = _protected_client(client)
    body = _make_guest(client)
    ok = c.get("/_t/me", headers={
        "Authorization": f"Bearer {body['player_id']}.{body['token']}"})
    assert ok.status_code == 200 and ok.get_json()["pid"] == body["player_id"]
    for h in (
        {},
        {"Authorization": f"Bearer {body['player_id']}.wrong"},
        {"Authorization": f"Bearer nobody.{body['token']}"},
        {"Authorization": "Bearer garbage"},
        {"Authorization": f"Basic {body['player_id']}.{body['token']}"},
    ):
        r = c.get("/_t/me", headers=h)
        assert r.status_code == 401
        assert r.get_json() == {"error": "unauthorized"}


def test_token_in_url_rejected(client):
    c = _protected_client(client)
    body = _make_guest(client)
    r = c.get(f"/_t/me?token={body['player_id']}.{body['token']}")
    assert r.status_code == 401


def test_guest_create_rate_limit(client):
    for _ in range(40):
        assert client.post("/api/spy-hunt/guests").status_code == 200
    r = client.post("/api/spy-hunt/guests")
    assert r.status_code == 429
    assert r.get_json()["error"] == "rate_limited"
    # a different IP is unaffected
    r2 = client.post("/api/spy-hunt/guests", headers={"X-Real-IP": "9.9.9.9"})
    assert r2.status_code == 200


def test_per_guest_limit_and_reset(client):
    app = client.application

    @app.route("/_t/rc")
    @auth.require_guest
    @ratelimits.limit("room_create")
    def rc():
        return jsonify({"ok": True})

    a, b = _make_guest(client), _make_guest(client)
    c = app.test_client()
    ha = {"Authorization": f"Bearer {a['player_id']}.{a['token']}"}
    hb = {"Authorization": f"Bearer {b['player_id']}.{b['token']}"}
    for _ in range(5):
        assert c.get("/_t/rc", headers=ha).status_code == 200
    assert c.get("/_t/rc", headers=ha).status_code == 429
    assert c.get("/_t/rc", headers=hb).status_code == 200
    ratelimits.reset_all()
    assert c.get("/_t/rc", headers=ha).status_code == 200


def test_per_guest_limit_without_auth_fails_loudly(client):
    app = client.application

    @app.route("/_t/bad")
    @ratelimits.limit("action")
    @auth.require_guest
    def bad():
        return jsonify({"ok": True})

    app.testing = False
    r = app.test_client().get("/_t/bad", headers={"X-Real-IP": "1.1.1.1"})
    assert r.status_code == 500


def test_bucket_keys_are_scoped(client):
    app = client.application
    with app.test_request_context("/", headers={"X-Real-IP": "abc"}):
        assert ratelimits.bucket_key("ip") == "ip:abc"
        g.player_id = "abc"
        assert ratelimits.bucket_key("guest") == "guest:abc"
    with app.test_request_context("/"):
        try:
            ratelimits.bucket_key("guest")
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError")
