from __future__ import annotations

import threading

from ai_svc.spy_hunt import locks, ratelimits, store
from ai_svc.spy_hunt.config import GameConfig

API = "/api/spy-hunt"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def guest(client, ip="10.0.0.1"):
    r = client.post(f"{API}/guests", headers={"X-Real-IP": ip})
    assert r.status_code == 200
    b = r.get_json()
    return {"Authorization": f"Bearer {b['player_id']}.{b['token']}"}, b["player_id"]


def create(client, name="Host", lang="en"):
    h, pid = guest(client)
    r = client.post(f"{API}/rooms", json={"name": name, "lang": lang}, headers=h)
    assert r.status_code == 201, r.get_json()
    return h, pid, r.get_json()


def join(client, code, name="P", lang="en", h=None):
    if h is None:
        h, _ = guest(client)
    return h, client.post(f"{API}/rooms/{code}/join", json={"name": name, "lang": lang}, headers=h)


def room_row(conn, code):
    return conn.execute("SELECT * FROM rooms WHERE code=?", (code,)).fetchone()


# ---- create / join / snapshot ----

def test_create_join_snapshot_flow(client, conn):
    h, pid, snap = create(client, name="Alice", lang="zh-Hans")
    code = snap["code"]
    assert len(code) == 4 and all(c in ALPHABET for c in code)
    assert snap["status"] == "lobby"
    assert snap["main_lang"] == "zh-Hans"
    assert snap["me"]["seat"] == 0 and snap["me"]["is_host"] is True
    assert snap["host_seat"] == 0
    assert snap["players"] == [{
        "seat": 0, "name": "Alice", "lang": "zh-Hans", "is_bot": False,
        "alive": True, "connected": False, "is_host": True}]
    assert snap["config"]["max_players"] == GameConfig().max_players
    assert snap["config"]["bot_fill"] is True
    assert isinstance(snap["server_time"], int) and snap["server_time"] > 1_600_000_000_000
    v0 = snap["version"]

    h2, r = join(client, code, name="Bob")
    assert r.status_code == 200
    s2 = r.get_json()
    assert s2["me"]["seat"] == 1 and s2["me"]["is_host"] is False
    assert [p["name"] for p in s2["players"]] == ["Alice", "Bob"]
    assert s2["version"] > v0

    g = client.get(f"{API}/rooms/{code}", headers=h)
    assert g.status_code == 200
    gs = g.get_json()
    assert len(gs["players"]) == 2
    last = conn.execute("SELECT MAX(seq) FROM events WHERE room_id=?",
                        (room_row(conn, code)["id"],)).fetchone()[0]
    assert gs["last_seq"] == last and last >= 1


def test_lowercase_code_accepted(client):
    h, _, snap = create(client)
    r = client.get(f"{API}/rooms/{snap['code'].lower()}", headers=h)
    assert r.status_code == 200


def test_join_emits_player_joined_event(client, conn):
    _, _, snap = create(client)
    join(client, snap["code"], name="Bob")
    rid = room_row(conn, snap["code"])["id"]
    rows = conn.execute("SELECT type, payload_json, audience FROM events WHERE room_id=? ORDER BY seq",
                        (rid,)).fetchall()
    types = [r["type"] for r in rows]
    assert types.count("player_joined") == 2
    assert all(r["audience"] == "all" for r in rows)


def test_unknown_code_404(client):
    h, _ = guest(client)
    assert client.get(f"{API}/rooms/ZZZZ", headers=h).status_code == 404
    _, r = join(client, "ZZZZ", h=h)
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_non_member_snapshot_403(client):
    _, _, snap = create(client)
    h2, _ = guest(client)
    r = client.get(f"{API}/rooms/{snap['code']}", headers=h2)
    assert r.status_code == 403
    assert r.get_json()["error"] == "not_member"


def test_requires_auth(client):
    _, _, snap = create(client)
    assert client.post(f"{API}/rooms", json={"name": "x", "lang": "en"}).status_code == 401
    assert client.get(f"{API}/rooms/{snap['code']}").status_code == 401


def test_eleventh_join_409(client):
    _, _, snap = create(client)
    code = snap["code"]
    for i in range(GameConfig().max_players - 1):
        _, r = join(client, code, name=f"P{i}")
        assert r.status_code == 200
    _, r = join(client, code, name="Late")
    assert r.status_code == 409
    assert r.get_json()["error"] == "room_full"


def test_full_counts_bot_seats(client, conn):
    _, _, snap = create(client)
    rid = room_row(conn, snap["code"])["id"]
    for seat in range(1, GameConfig().max_players):
        conn.execute("INSERT INTO players(room_id, player_id, seat, name, lang, is_bot, alive, connected, joined_at)"
                     " VALUES(?,?,?,?,?,1,1,1,0)", (rid, f"bot{seat}", seat, f"B{seat}", "en"))
    conn.commit()
    _, r = join(client, snap["code"])
    assert r.status_code == 409


def test_join_after_start_409(client, conn):
    _, _, snap = create(client)
    conn.execute("UPDATE rooms SET status='playing', phase='describe' WHERE code=?", (snap["code"],))
    conn.commit()
    _, r = join(client, snap["code"])
    assert r.status_code == 409
    assert r.get_json()["error"] == "game_started"


def test_rejoin_is_idempotent(client, conn):
    _, _, snap = create(client)
    h2, r1 = join(client, snap["code"], name="Bob")
    v1 = r1.get_json()["version"]
    # even after start, a member rejoining gets the snapshot
    conn.execute("UPDATE rooms SET status='playing', phase='describe' WHERE code=?", (snap["code"],))
    conn.commit()
    _, r2 = join(client, snap["code"], name="Bobby", h=h2)
    assert r2.status_code == 200
    s2 = r2.get_json()
    assert s2["me"]["seat"] == 1
    assert [p["name"] for p in s2["players"]] == ["Host", "Bob"]
    assert s2["version"] == v1
    n = conn.execute("SELECT COUNT(*) FROM players WHERE room_id=?",
                     (room_row(conn, snap["code"])["id"],)).fetchone()[0]
    assert n == 2


def test_host_rejoin_own_room(client):
    h, _, snap = create(client)
    _, r = join(client, snap["code"], h=h)
    assert r.status_code == 200
    assert r.get_json()["me"]["seat"] == 0


def test_freed_seat_is_reused(client, conn):
    _, _, snap = create(client)
    rid = room_row(conn, snap["code"])["id"]
    join(client, snap["code"], name="A")
    join(client, snap["code"], name="B")
    conn.execute("DELETE FROM players WHERE room_id=? AND seat=1", (rid,))
    conn.commit()
    _, r = join(client, snap["code"], name="C")
    assert r.get_json()["me"]["seat"] == 1


def test_concurrent_joins_never_exceed_max(client, conn):
    _, _, snap = create(client)
    code = snap["code"]
    heads = [guest(client)[0] for _ in range(14)]
    app = client.application
    results = []

    def go(h):
        c = app.test_client()
        results.append(c.post(f"{API}/rooms/{code}/join", json={"name": "x", "lang": "en"},
                              headers=h).status_code)

    ts = [threading.Thread(target=go, args=(h,)) for h in heads]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count(200) == GameConfig().max_players - 1
    assert results.count(409) == 14 - (GameConfig().max_players - 1)
    rid = room_row(conn, code)["id"]
    seats = [r[0] for r in conn.execute("SELECT seat FROM players WHERE room_id=?", (rid,))]
    assert sorted(seats) == list(range(GameConfig().max_players))


# ---- input validation ----

def test_long_name_capped_and_control_chars_stripped(client):
    _, _, snap = create(client, name="x" * 10_000)
    assert snap["players"][0]["name"] == "x" * 16
    _, r = join(client, snap["code"], name="Bo\x00b\n\t‮​by\x7f")
    assert r.status_code == 200
    assert r.get_json()["players"][1]["name"] == "Bobby"
    _, r = join(client, snap["code"], name="  " + "中" * 20 + "  ")
    assert r.get_json()["players"][2]["name"] == "中" * 16


def test_empty_after_strip_name_400(client):
    h, _ = guest(client)
    for name in ("", "   ", "\x00\x01\n", None, 123, ["a"]):
        ratelimits.reset_all()
        r = client.post(f"{API}/rooms", json={"name": name, "lang": "en"}, headers=h)
        assert r.status_code == 400, name
        assert r.get_json()["error"] == "bad_name"


def test_invalid_lang_400(client):
    h, _ = guest(client)
    for lang in ("fr", "", None, 5, "EN"):
        r = client.post(f"{API}/rooms", json={"name": "a", "lang": lang}, headers=h)
        assert r.status_code == 400
        assert r.get_json()["error"] == "bad_lang"
    _, _, snap = create(client)
    _, r = join(client, snap["code"], lang="de")
    assert r.status_code == 400


def test_malformed_json_400(client):
    h, _, snap = create(client)
    code = snap["code"]
    bad_bodies = [
        dict(data="{not json", content_type="application/json"),
        dict(data="[1,2]", content_type="application/json"),
        dict(data='"str"', content_type="application/json"),
        dict(data="null", content_type="application/json"),
        dict(data="name=a", content_type="application/x-www-form-urlencoded"),
        dict(),
    ]
    for kw in bad_bodies:
        ratelimits.reset_all()
        for method, path in (("post", "/rooms"), ("post", f"/rooms/{code}/join"),
                             ("patch", f"/rooms/{code}/me"), ("patch", f"/rooms/{code}/settings")):
            r = getattr(client, method)(f"{API}{path}", headers=h, **kw)
            assert r.status_code == 400, (path, kw)
            assert r.get_json()["error"] == "bad_json"


def test_code_collision_retries(client, monkeypatch, conn):
    seq = iter(["AAAA", "AAAA", "BBBB"])
    monkeypatch.setattr(store, "_random_code", lambda: next(seq))
    _, _, s1 = create(client)
    _, _, s2 = create(client)
    assert (s1["code"], s2["code"]) == ("AAAA", "BBBB")


# ---- settings ----

def test_settings_host_lobby_only(client, conn):
    h, _, snap = create(client)
    code = snap["code"]
    h2, _ = join(client, code)
    r = client.patch(f"{API}/rooms/{code}/settings", json={"main_lang": "zh-Hans"}, headers=h2)
    assert r.status_code == 403
    assert r.get_json()["error"] == "not_host"
    r = client.patch(f"{API}/rooms/{code}/settings",
                     json={"main_lang": "zh-Hans", "bot_fill": False}, headers=h)
    assert r.status_code == 200
    s = r.get_json()
    assert s["main_lang"] == "zh-Hans" and s["config"]["bot_fill"] is False
    rid = room_row(conn, code)["id"]
    ev = conn.execute("SELECT * FROM events WHERE room_id=? AND type='settings'", (rid,)).fetchall()
    assert len(ev) == 1 and ev[0]["audience"] == "all"
    # bad values
    for body in ({"main_lang": "fr"}, {"bot_fill": "yes"}, {}, {"nope": 1}):
        r = client.patch(f"{API}/rooms/{code}/settings", json=body, headers=h)
        assert r.status_code == 400, body
    # non-member
    h3, _ = guest(client)
    assert client.patch(f"{API}/rooms/{code}/settings", json={"bot_fill": True},
                        headers=h3).status_code == 403
    # after start
    conn.execute("UPDATE rooms SET status='playing' WHERE id=?", (rid,))
    conn.commit()
    r = client.patch(f"{API}/rooms/{code}/settings", json={"bot_fill": True}, headers=h)
    assert r.status_code == 409


# ---- me ----

def test_patch_me(client, conn):
    h, _, snap = create(client)
    code = snap["code"]
    r = client.patch(f"{API}/rooms/{code}/me", json={"name": "New\x00Name", "lang": "zh-Hans"}, headers=h)
    assert r.status_code == 200
    me = r.get_json()["players"][0]
    assert me["name"] == "NewName" and me["lang"] == "zh-Hans"
    assert r.get_json()["version"] > snap["version"]
    rid = room_row(conn, code)["id"]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE room_id=? AND type='player_updated'",
                        (rid,)).fetchone()[0] == 1
    for body in ({"lang": "xx"}, {"name": "\n"}, {}, {"name": 3}):
        assert client.patch(f"{API}/rooms/{code}/me", json=body, headers=h).status_code == 400
    h2, _ = guest(client)
    assert client.patch(f"{API}/rooms/{code}/me", json={"lang": "en"}, headers=h2).status_code == 403
    assert client.patch(f"{API}/rooms/QQQQ/me", json={"lang": "en"}, headers=h2).status_code == 404


# ---- rate limits ----

def test_room_create_rate_limited(client):
    h, _ = guest(client)
    for _ in range(5):
        assert client.post(f"{API}/rooms", json={"name": "a", "lang": "en"}, headers=h).status_code == 201
    assert client.post(f"{API}/rooms", json={"name": "a", "lang": "en"}, headers=h).status_code == 429


def test_flood_limit_shared_across_room_routes(client):
    ip = {"X-Real-IP": "6.6.6.6"}
    routes = [("get", "/rooms/ZZZZ"), ("post", "/rooms"), ("post", "/rooms/ZZZZ/join"),
              ("patch", "/rooms/ZZZZ/me"), ("patch", "/rooms/ZZZZ/settings")]
    for i in range(200):
        m, p = routes[i % len(routes)]
        assert getattr(client, m)(f"{API}{p}", headers=ip).status_code == 401
    for m, p in routes:
        r = getattr(client, m)(f"{API}{p}", headers=ip)
        assert r.status_code == 429 and r.get_json()["error"] == "rate_limited"
    # another IP is unaffected
    assert client.get(f"{API}/rooms/ZZZZ", headers={"X-Real-IP": "8.8.8.8"}).status_code == 401


def test_read_limit_on_snapshot(client):
    h, _, snap = create(client)
    for _ in range(60):
        assert client.get(f"{API}/rooms/{snap['code']}", headers=h).status_code == 200
    assert client.get(f"{API}/rooms/{snap['code']}", headers=h).status_code == 429


# ---- store / locks units ----

def test_room_lock_is_shared_rlock():
    a = locks.room_lock("r1")
    assert a is locks.room_lock("r1")
    assert a is not locks.room_lock("r2")
    with a:
        with a:  # re-entrant
            pass


def test_append_event_returns_increasing_seq(temp_db):
    s1 = store.append_event("r", "player_joined", {"seat": 0}, "all")
    s2 = store.append_event("r", "player_joined", {"seat": 1}, "seat:1")
    assert s2 > s1


def test_append_event_rejects_bad_audience(temp_db):
    import pytest
    for aud in ("everyone", "seat:", "seat:x", None):
        with pytest.raises(ValueError):
            store.append_event("r", "player_joined", {}, aud)


def test_state_changes_bump_version(client, conn):
    h, _, snap = create(client)
    code = snap["code"]
    v = room_row(conn, code)["version"]
    h2, _ = join(client, code)
    v2 = room_row(conn, code)["version"]
    client.patch(f"{API}/rooms/{code}/me", json={"lang": "zh-Hans"}, headers=h2)
    v3 = room_row(conn, code)["version"]
    client.patch(f"{API}/rooms/{code}/settings", json={"bot_fill": False}, headers=h)
    v4 = room_row(conn, code)["version"]
    assert v < v2 < v3 < v4
    assert room_row(conn, code)["phase_seq"] == 0
