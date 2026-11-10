from __future__ import annotations

from ai_svc.spy_hunt import outfits

from .test_rooms import API, guest

AV = {"emoji": "🦊", "color": "#ff6b6b"}
OUT = {"voice": "dry", "style": "brief", "quirk": "emoji"}


def mk(client, h, name="Mochi", avatar=AV, outfit=OUT):
    return client.post(f"{API}/bots", json={"name": name, "avatar": avatar, "outfit": outfit}, headers=h)


def test_create_list_update_delete_roundtrip(client):
    h, _ = guest(client)
    r = mk(client, h)
    assert r.status_code == 201
    b = r.get_json()
    assert len(b["id"]) == 8 and all(c.isalnum() or c in "-_" for c in b["id"])
    assert b["record"] == {"games": 0, "wins": 0, "spy_games": 0, "spy_wins": 0}
    assert client.get(f"{API}/bots", headers=h).get_json()["bots"] == [b]
    r = client.patch(f"{API}/bots/{b['id']}", json={"name": "Mochi2"}, headers=h)
    assert r.status_code == 200
    assert r.get_json() == {**b, "name": "Mochi2"}
    assert client.delete(f"{API}/bots/{b['id']}", headers=h).get_json() == {"ok": True}
    assert client.get(f"{API}/bots", headers=h).get_json() == {"bots": []}


def test_fourth_bot_is_refused(client):
    h, _ = guest(client)
    ids = [mk(client, h, name=f"b{i}").get_json()["id"] for i in range(3)]
    r = mk(client, h)
    assert r.status_code == 409 and r.get_json()["error"] == "bot_limit"
    client.delete(f"{API}/bots/{ids[0]}", headers=h)
    assert mk(client, h).status_code == 201


def test_name_is_cleaned(client):
    h, _ = guest(client)
    assert mk(client, h, name="  Mo\u202e\nchi  ").get_json()["name"] == "Mochi"
    assert mk(client, h, name="  Mo  chi  ").get_json()["name"] == "Mo chi"
    assert mk(client, h, name="x" * 20).get_json()["name"] == "x" * 16
    for bad in ("", "\u200b", 123):
        r = mk(client, h, name=bad)
        assert r.status_code == 400 and r.get_json()["error"] == "bad_name"


def test_bad_avatar_and_outfit(client):
    h, _ = guest(client)
    for av in ({"emoji": "💩", "color": AV["color"]}, {"emoji": "🦊", "color": "#000000"}, {"emoji": "🦊"}):
        assert mk(client, h, avatar=av).get_json()["error"] == "bad_avatar"
    for out in ({"style": "brief", "quirk": "emoji"}, {**OUT, "style": "nope"}):
        r = mk(client, h, outfit=out)
        assert r.status_code == 400 and r.get_json()["error"] == "bad_outfit"
    bid = mk(client, h).get_json()["id"]
    r = client.patch(f"{API}/bots/{bid}", json={"avatar": {"emoji": "🐱"}}, headers=h)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_avatar"
    r = client.patch(f"{API}/bots/{bid}", json={"outfit": {"voice": "dry"}}, headers=h)
    assert r.get_json()["error"] == "bad_outfit"
    r = client.patch(f"{API}/bots/{bid}", json={"x": 1}, headers=h)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_request"


def test_other_guest_cannot_edit_or_delete(client):
    h, _ = guest(client)
    h2, _ = guest(client, ip="10.0.0.2")
    b = mk(client, h).get_json()
    r = client.patch(f"{API}/bots/{b['id']}", json={"name": "X"}, headers=h2)
    assert r.status_code == 404 and r.get_json()["error"] == "not_found"
    r = client.delete(f"{API}/bots/{b['id']}", headers=h2)
    assert r.status_code == 404 and r.get_json()["error"] == "not_found"
    assert client.get(f"{API}/bots", headers=h).get_json()["bots"] == [b]


def test_public_card_needs_no_token_and_hides_owner(client):
    h, pid = guest(client)
    b = mk(client, h).get_json()
    r = client.get(f"{API}/bots/{b['id']}")
    assert r.status_code == 200
    assert set(r.get_json()) == {"id", "name", "avatar", "outfit", "record"}
    assert pid not in r.get_data(as_text=True)
    client.delete(f"{API}/bots/{b['id']}", headers=h)
    assert client.get(f"{API}/bots/{b['id']}").status_code == 404
    assert client.get(f"{API}/bots/nope").status_code == 404
    assert client.get(f"{API}/bots/{'a' * 200}").status_code == 404


def test_requests_need_a_guest_token(client):
    assert client.get(f"{API}/bots").status_code == 401
    assert client.post(f"{API}/bots", json={}).status_code == 401
    assert client.get(f"{API}/bots/catalog").status_code == 401


def test_catalog_endpoint_matches_outfits_catalog(client):
    h, _ = guest(client)
    r = client.get(f"{API}/bots/catalog", headers=h)
    assert r.status_code == 200 and r.get_json() == outfits.catalog()


def test_public_card_is_rate_limited_per_ip_only(client):
    ip = {"X-Real-IP": "7.7.7.7"}
    for _ in range(200):
        assert client.get(f"{API}/bots/abcdefgh", headers=ip).status_code == 404
    r = client.get(f"{API}/bots/abcdefgh", headers=ip)
    assert r.status_code == 429 and r.get_json()["error"] == "rate_limited"
