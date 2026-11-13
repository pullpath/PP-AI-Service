from __future__ import annotations

from ai_svc.spy_hunt import looks
from ai_svc.spy_hunt.tests.test_clans_routes import registered
from ai_svc.spy_hunt.tests.test_rooms import API, create, guest, join


def seed(conn, pid, n):
    conn.execute("INSERT OR REPLACE INTO player_total_credits(player_id, credits, updated_at) VALUES(?,?,0)",
                 (pid, n))
    conn.commit()


def test_catalog_marks_rank_and_starts_empty(client):
    h, _ = guest(client)
    body = client.get(f"{API}/looks", headers=h).get_json()
    assert body["rank"] == 0 and body["mine"] is None
    assert body["emojis"][0] == {"emoji": looks.FREE_EMOJIS[0], "rank": 0}
    assert {e["rank"] for e in body["emojis"]} == {0, 1, 2, 3, 4, 5}
    assert [f["key"] for f in body["frames"]] == ["none", "leaf", "ribbon", "star", "gold", "crown"]
    assert body["colors"] == list(looks.COLORS)
    assert client.get(f"{API}/looks").status_code == 401


def test_save_free_look_and_reject_locked(client, conn):
    h, pid = guest(client)
    ok = {"emoji": looks.FREE_EMOJIS[3], "color": looks.COLORS[1], "frame": "none"}
    r = client.put(f"{API}/looks", json=ok, headers=h)
    assert r.status_code == 200 and r.get_json()["mine"] == ok
    locked_frame = {**ok, "frame": "crown"}
    r = client.put(f"{API}/looks", json=locked_frame, headers=h)
    assert r.status_code == 403 and r.get_json()["error"] == "look_locked"
    locked_emoji = {**ok, "emoji": looks.RANK_EMOJIS[5][0]}
    assert client.put(f"{API}/looks", json=locked_emoji, headers=h).status_code == 403
    seed(conn, pid, 12000)
    assert client.put(f"{API}/looks", json={**locked_emoji, "frame": "crown"}, headers=h).status_code == 200


def test_bad_values_are_400(client):
    h, _ = guest(client)
    for body in ({"emoji": "💩", "color": looks.COLORS[0], "frame": "none"},
                 {"emoji": looks.FREE_EMOJIS[0], "color": "#000000", "frame": "none"},
                 {"emoji": looks.FREE_EMOJIS[0], "color": looks.COLORS[0], "frame": "lol"},
                 {"emoji": looks.FREE_EMOJIS[0]}):
        r = client.put(f"{API}/looks", json=body, headers=h)
        assert r.status_code == 400, body
        assert r.get_json()["error"] == "bad_look"


def test_saved_look_is_worn_on_join_and_updates_live_rooms(client, conn):
    h, pid, room = create(client, "Ann")
    code = room["code"]
    snap = client.get(f"{API}/rooms/{code}", headers=h).get_json()
    assert snap["players"][0]["avatar"] is None
    seed(conn, pid, 300)
    look = {"emoji": looks.RANK_EMOJIS[1][0], "color": looks.COLORS[2], "frame": "leaf"}
    assert client.put(f"{API}/looks", json=look, headers=h).status_code == 200
    snap = client.get(f"{API}/rooms/{code}", headers=h).get_json()
    assert snap["players"][0]["avatar"] == look

    h2, _ = guest(client)
    client.put(f"{API}/looks", json={"emoji": looks.FREE_EMOJIS[0], "color": looks.COLORS[0],
                                     "frame": "none"}, headers=h2)
    _, r = join(client, code, "Ben", h=h2)
    assert r.status_code in (200, 201)
    snap = client.get(f"{API}/rooms/{code}", headers=h).get_json()
    ben = next(p for p in snap["players"] if p["name"] == "Ben")
    assert ben["avatar"] == {"emoji": looks.FREE_EMOJIS[0], "color": looks.COLORS[0], "frame": "none"}


def test_clan_badge_builder_and_leader_change(client):
    a, b = registered(client), registered(client)
    badge = {"emoji": looks.CLAN_EMOJIS[-1], "color": looks.COLORS[3]}
    r = client.post(f"{API}/clans", json={"name": "Moths", "badge": badge}, headers=a)
    assert r.status_code == 201 and r.get_json()["badge"] == badge
    # legacy index form still works
    assert client.post(f"{API}/clans", json={"name": "Owls", "badge": 2}, headers=b).status_code == 201
    bad = client.post(f"{API}/clans", json={"name": "Nope", "badge": {"emoji": "💩", "color": "#fff"}},
                      headers=registered(client))
    assert bad.status_code == 400

    new = {"emoji": looks.CLAN_EMOJIS[0], "color": looks.COLORS[0]}
    r = client.put(f"{API}/clans/badge", json={"badge": new}, headers=a)
    assert r.status_code == 200 and r.get_json()["badge"] == new
    assert client.get(f"{API}/clans/mine", headers=a).get_json()["clan"]["badge"] == new
    # not the leader of Moths, and not in it
    code = client.get(f"{API}/clans/mine", headers=a).get_json()["clan"]["code"]
    c = registered(client)
    client.post(f"{API}/clans/join", json={"code": code}, headers=c)
    r = client.put(f"{API}/clans/badge", json={"badge": new}, headers=c)
    assert r.status_code == 403 and r.get_json()["error"] == "not_leader"


def test_badge_catalog_lists_emojis_and_colors(client):
    body = client.get(f"{API}/clans/badges").get_json()
    assert len(body["badges"]) == 12  # legacy presets kept
    assert body["emojis"] == list(looks.CLAN_EMOJIS) and body["colors"] == list(looks.COLORS)
