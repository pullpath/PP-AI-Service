from __future__ import annotations

import itertools

from ai_svc.spy_hunt.tests.test_rooms import API, create, join

_n = itertools.count()


def registered(client):
    g = client.post(f"{API}/guests").get_json()
    h = {"Authorization": f"Bearer {g['player_id']}.{g['token']}"}
    r = client.post(f"{API}/register", json={"email": f"r{next(_n)}@example.com",
                                              "password": "longenough"}, headers=h)
    assert r.status_code == 200
    return h


def anon(client):
    g = client.post(f"{API}/guests").get_json()
    return {"Authorization": f"Bearer {g['player_id']}.{g['token']}"}


def test_create_mine_join_leave_roundtrip(client):
    a, b = registered(client), registered(client)
    assert client.get(f"{API}/clans/mine", headers=a).get_json() == {"clan": None}
    r = client.post(f"{API}/clans", json={"name": "Foxes", "badge": 1}, headers=a)
    assert r.status_code == 201
    clan = r.get_json()
    assert clan["name"] == "Foxes" and clan["members"] == 1
    r = client.post(f"{API}/clans/join", json={"code": clan["code"]}, headers=b)
    assert r.status_code == 200 and r.get_json()["members"] == 2
    mine = client.get(f"{API}/clans/mine", headers=b).get_json()
    assert mine["clan"]["name"] == "Foxes"
    assert mine["clan"]["code"] == clan["code"]
    assert mine["clan"]["is_leader"] is False
    assert set(mine["season"]) == {"this_week", "streak", "history", "members"}
    assert client.get(f"{API}/clans/mine", headers=a).get_json()["clan"]["is_leader"] is True
    assert client.post(f"{API}/clans/leave", headers=b).get_json() == {"ok": True}
    assert client.get(f"{API}/clans/mine", headers=b).get_json() == {"clan": None}


def test_open_list(client):
    a = registered(client)
    client.post(f"{API}/clans", json={"name": "Foxes", "badge": 0}, headers=a)
    r = client.get(f"{API}/clans/open", headers=anon(client))
    assert r.status_code == 200
    assert [c["name"] for c in r.get_json()["clans"]] == ["Foxes"]


def test_badges_listed(client):
    r = client.get(f"{API}/clans/badges")
    assert r.status_code == 200
    assert len(r.get_json()["badges"]) >= 6


def test_guest_gets_403_and_error_shape(client):
    r = client.post(f"{API}/clans", json={"name": "Foxes", "badge": 0}, headers=anon(client))
    assert r.status_code == 403
    assert r.get_json()["error"] == "register_required"
    assert "message" in r.get_json()


def test_requires_token(client):
    assert client.get(f"{API}/clans/mine").status_code == 401
    assert client.post(f"{API}/clans", json={"name": "Foxes", "badge": 0}).status_code == 401


def test_errors(client):
    a = registered(client)
    assert client.post(f"{API}/clans", json={"name": "x", "badge": 0}, headers=a).get_json()["error"] == "bad_name"
    assert client.post(f"{API}/clans/join", json={"code": "NOPE00"}, headers=a).status_code == 404
    assert client.post(f"{API}/clans/leave", headers=a).status_code == 409


def test_room_snapshot_players_carry_clan_badge(client):
    h, pid, snap = create(client)
    code = snap["code"]
    a = registered(client)
    clan = client.post(f"{API}/clans", json={"name": "Foxes", "badge": 2}, headers=a).get_json()
    hh, r = join(client, code, name="Ann", h=a)
    snap = client.get(f"{API}/rooms/{code}", headers=h).get_json()
    by = {p["name"]: p for p in snap["players"]}
    assert by["Ann"]["clan"] == {"name": "Foxes", **clan["badge"]}
    assert by["Host"]["clan"] is None
    assert "player_id" not in by["Ann"]


def test_joining_or_leaving_a_clan_refreshes_the_badge_in_open_rooms(client, conn):
    h, pid, snap = create(client)
    code = snap["code"]
    a = registered(client)
    join(client, code, name="Ann", h=a)
    clan = client.post(f"{API}/clans", json={"name": "Foxes", "badge": 0}, headers=a).get_json()
    rid = conn.execute("SELECT id FROM rooms WHERE code=?", (code,)).fetchone()["id"]

    def last_update():
        rows = conn.execute("SELECT payload_json FROM events WHERE room_id=? AND type='player_updated'"
                            " ORDER BY seq DESC LIMIT 1", (rid,)).fetchall()
        import json
        return json.loads(rows[0]["payload_json"])["player"] if rows else None

    assert last_update()["clan"] == {"name": "Foxes", **clan["badge"]}
    client.post(f"{API}/clans/leave", headers=a)
    assert last_update()["clan"] is None
    # finished rooms are left alone
    conn.execute("UPDATE rooms SET status='finished' WHERE id=?", (rid,))
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM events WHERE room_id=?", (rid,)).fetchone()[0]
    client.post(f"{API}/clans", json={"name": "Wolves", "badge": 0}, headers=a)
    assert conn.execute("SELECT COUNT(*) FROM events WHERE room_id=?", (rid,)).fetchone()[0] == n
