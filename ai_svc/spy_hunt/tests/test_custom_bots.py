from __future__ import annotations

import json

from ai_svc.spy_hunt import db, outfits

from .test_rooms import API, guest

AV = {"emoji": "🦊", "color": "#ff6b6b"}
RULE_PAIRS = [(t, d) for t, d in list(zip(sorted(outfits.TRIGGERS), sorted(outfits.ACTIONS)))[:2]]
OUT = {"voice": "dry", "style": "brief", "quirk": "emoji", "rules": []}


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
    assert set(r.get_json()) == {"id", "name", "avatar", "outfit", "record", "remix_of", "remixes",
                                "remixable", "ranked", "listed"}
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


RULES = [{"when": "accused", "do": "counter_accuse"}, {"when": "late_game", "do": "vote_leader"}]


def test_rules_roundtrip_through_create_list_update_public_card(client):
    h, _ = guest(client)
    b = mk(client, h, outfit={**OUT, "rules": RULES}).get_json()
    assert b["outfit"]["rules"] == RULES
    assert client.get(f"{API}/bots", headers=h).get_json()["bots"][0]["outfit"]["rules"] == RULES
    assert client.get(f"{API}/bots/{b['id']}", headers=h).get_json()["outfit"]["rules"] == RULES
    new = [{"when": "first_to_speak", "do": "go_vague"}]
    r = client.patch(f"{API}/bots/{b['id']}", json={"outfit": {**OUT, "rules": new}}, headers=h)
    assert r.get_json()["outfit"]["rules"] == new
    bare = {k: OUT[k] for k in ("voice", "style", "quirk")}
    r = client.patch(f"{API}/bots/{b['id']}", json={"outfit": bare}, headers=h)
    assert r.get_json()["outfit"]["rules"] == []


def test_bot_without_rules_json_reads_as_empty_rules(client, conn):
    h, pid = guest(client)
    conn.execute("INSERT INTO custom_bots(id, owner_player_id, name, avatar_emoji, avatar_color,"
                 " voice, style, quirk, created_at) VALUES('old1',?,'Old','🦊','#ff6b6b','dry','brief','emoji',1)",
                 (pid,))
    conn.commit()
    assert client.get(f"{API}/bots", headers=h).get_json()["bots"][0]["outfit"]["rules"] == []
    assert client.get(f"{API}/bots/old1", headers=h).get_json()["outfit"]["rules"] == []
    conn.execute("UPDATE custom_bots SET rules_json='{not json' WHERE id='old1'")
    conn.commit()
    assert client.get(f"{API}/bots/old1", headers=h).get_json()["outfit"]["rules"] == []


def test_bad_rules_are_400_bad_outfit(client):
    h, _ = guest(client)
    for bad in ("x", [1], [{"when": "accused"}], RULES + RULES, [RULES[0], RULES[0]]):
        r = mk(client, h, outfit={**OUT, "rules": bad})
        assert r.status_code == 400 and r.get_json()["error"] == "bad_outfit"
    bid = mk(client, h).get_json()["id"]
    r = client.patch(f"{API}/bots/{bid}", json={"outfit": {**OUT, "rules": "x"}}, headers=h)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_outfit"


def test_catalog_endpoint_lists_triggers_and_actions(client):
    h, _ = guest(client)
    c = client.get(f"{API}/bots/catalog", headers=h).get_json()
    assert c["triggers"] == list(outfits.TRIGGERS) and c["actions"] == list(outfits.ACTIONS)
    assert c["max_rules"] == 3


def test_old_custom_bots_table_is_migrated(temp_db, conn):
    conn.execute("DROP TABLE custom_bots")
    conn.execute("CREATE TABLE custom_bots(id TEXT PRIMARY KEY, owner_player_id TEXT, name TEXT,"
                 " avatar_emoji TEXT, avatar_color TEXT, voice TEXT, style TEXT, quirk TEXT,"
                 " games INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, spy_games INTEGER DEFAULT 0,"
                 " spy_wins INTEGER DEFAULT 0, created_at INTEGER)")
    conn.execute("INSERT INTO custom_bots(id, name) VALUES('a','A')")
    conn.commit()
    db.init_db()
    db.init_db()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(custom_bots)")}
    assert "rules_json" in cols
    assert conn.execute("SELECT name FROM custom_bots WHERE id='a'").fetchone()[0] == "A"


# ---- remix fields, listed ----

def _remix(client, h, src, name="Remix", outfit=None, **kw):
    body = {"name": name, "avatar": AV, "outfit": outfit or {**OUT, "voice": "pirate"}, "remix_of": src, **kw}
    return client.post(f"{API}/bots", json=body, headers=h)


def test_card_has_remix_fields_with_defaults(client):
    h, _ = guest(client)
    b = mk(client, h).get_json()
    assert b["remix_of"] is None and b["remixes"] == 0 and b["remixable"] is True
    assert b["ranked"] == {"games": 0, "wins": 0, "spy_games": 0, "spy_wins": 0}
    assert b["listed"] is True
    assert client.get(f"{API}/bots/{b['id']}").get_json() == b
    assert client.get(f"{API}/bots", headers=h).get_json()["bots"] == [b]


def test_listed_roundtrip(client):
    h, _ = guest(client)
    r = client.post(f"{API}/bots", json={"name": "M", "avatar": AV, "outfit": OUT, "listed": False}, headers=h)
    b = r.get_json()
    assert r.status_code == 201 and b["listed"] is False
    r = client.patch(f"{API}/bots/{b['id']}", json={"listed": True}, headers=h)
    assert r.status_code == 200 and r.get_json()["listed"] is True
    r = client.patch(f"{API}/bots/{b['id']}", json={"listed": "yes"}, headers=h)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_request"


def test_remix_credit_and_count(client):
    ha, _ = guest(client)
    hb, _ = guest(client)
    hc, _ = guest(client)
    a = mk(client, ha).get_json()
    b = _remix(client, hb, a["id"]).get_json()
    assert b["remix_of"] == {"id": a["id"], "name": "Mochi"}
    assert client.get(f"{API}/bots/{a['id']}").get_json()["remixes"] == 1
    _remix(client, hb, a["id"], name="Again")
    assert client.get(f"{API}/bots/{a['id']}").get_json()["remixes"] == 1
    client.delete(f"{API}/bots/{b['id']}", headers=hb)
    assert client.get(f"{API}/bots/{a['id']}").get_json()["remixes"] == 1
    _remix(client, hc, a["id"])
    assert client.get(f"{API}/bots/{a['id']}").get_json()["remixes"] == 2


def test_remix_of_own_bot_has_no_credit(client):
    h, _ = guest(client)
    a = mk(client, h).get_json()
    b = _remix(client, h, a["id"]).get_json()
    assert b["remix_of"] is None
    assert client.get(f"{API}/bots/{a['id']}").get_json()["remixes"] == 0


def test_remix_of_errors(client):
    ha, _ = guest(client)
    hb, _ = guest(client)
    a = mk(client, ha).get_json()
    r = _remix(client, hb, "nope")
    assert r.status_code == 404 and r.get_json()["error"] == "not_found"
    r = _remix(client, hb, 5)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_request"
    db.get_conn().execute("UPDATE custom_bots SET blocked=1 WHERE id=?", (a["id"],))
    db.get_conn().commit()
    r = _remix(client, hb, a["id"])
    assert r.status_code == 404 and r.get_json()["error"] == "not_found"
    assert client.get(f"{API}/bots", headers=hb).get_json() == {"bots": []}


def test_remix_credit_disappears_when_source_is_deleted_or_blocked(client):
    ha, _ = guest(client)
    hb, _ = guest(client)
    a = mk(client, ha).get_json()
    b = _remix(client, hb, a["id"]).get_json()
    db.get_conn().execute("UPDATE custom_bots SET blocked=1 WHERE id=?", (a["id"],))
    db.get_conn().commit()
    assert client.get(f"{API}/bots/{b['id']}").get_json()["remix_of"] is None
    assert client.get(f"{API}/bots/{a['id']}").get_json()["remixable"] is False
    client.delete(f"{API}/bots/{a['id']}", headers=ha)
    assert client.get(f"{API}/bots/{b['id']}").get_json()["remix_of"] is None


ZERO = {"games": 0, "wins": 0, "spy_games": 0, "spy_wins": 0}


def test_outfit_change_resets_ranked_but_not_plain(client, conn):
    r1, r2 = (outfits.clean_rules([{"when": t, "do": d}])[0] for t, d in RULE_PAIRS)
    cases = [{"voice": "chatty"}, {"rules": [r1]}, {"rules": [r1, r2]}, "reorder"]
    for new in cases:
        h, _ = guest(client)
        base = {**OUT, "rules": [r1, r2]} if new == "reorder" else OUT
        bid = mk(client, h, outfit=base).get_json()["id"]
        conn.execute("UPDATE custom_bots SET games=4, ranked_games=3, ranked_wins=2,"
                     " ranked_spy_games=1, ranked_spy_wins=1 WHERE id=?", (bid,))
        conn.commit()
        same = client.patch(f"{API}/bots/{bid}", json={"outfit": base}, headers=h).get_json()
        assert same["ranked"]["games"] == 3
        out = {**base, "rules": [r2, r1]} if new == "reorder" else {**base, **new}
        card = client.patch(f"{API}/bots/{bid}", json={"outfit": out}, headers=h).get_json()
        assert card["ranked"] == ZERO
        assert card["record"]["games"] == 4
