from __future__ import annotations

import json

from ai_svc.spy_hunt import arena
from ai_svc.spy_hunt.db import get_conn

from .test_custom_bots import AV, OUT, mk
from .test_rooms import API, guest


def make_match(day, bots, lang="en", t=None, quote_prefix="hello"):
    """bots: list of (bot_id, role, won, accused, out_round); two built-in seats are added."""
    players = [{"seat": i, "name": f"B{i}", "avatar": AV, "bot_id": b[0], "role": b[1]}
               for i, b in enumerate(bots)]
    players.append({"seat": len(bots), "name": "Rex", "avatar": None, "bot_id": None, "role": "civilian"})
    rounds = [{"round": 1, "statements": [{"seat": i, "text": f"{quote_prefix} {i}"} for i in range(len(players))],
               "votes": [], "eliminated": None}]
    result = {"log": {"players": players, "rounds": rounds,
                      "words": {"civilian": "piano", "spy": "organ"}, "winner": "civilians"},
              "entries": [{"seat": i, "bot_id": b[0], "role": b[1], "won": b[2], "accused": b[3],
                           "out_round": b[4], "quote": None, "fallback_share": 0.0}
                          for i, b in enumerate(bots)]}
    mid = arena.store_match(get_conn(), day, lang, "p", result)
    if t is not None:
        get_conn().execute("UPDATE arena_matches SET created_at=? WHERE id=?", (t, mid))
        get_conn().commit()
    return mid


def setup(client, n=1):
    h, _ = guest(client)
    return h, [mk(client, h, name=f"b{i}").get_json()["id"] for i in range(n)]


def test_recaps_for_the_owner_only(client):
    ha, (a,) = setup(client)
    hb, _ = setup(client)
    mid = make_match("2026-11-10", [(a, "spy", True, 2, None)])
    r = client.get(f"{API}/bots/recaps", headers=ha).get_json()
    assert r["unseen"] == 1
    assert r["recaps"] == [{"match_id": mid, "bot_id": a, "bot_name": "B0", "avatar": AV,
                            "day": "2026-11-10", "lang": "en", "role": "spy", "won": True,
                            "accused": 2, "out_round": None, "quote": "hello 0", "seen": False}]
    assert client.get(f"{API}/bots/recaps", headers=hb).get_json() == {"recaps": [], "unseen": 0}
    assert client.get(f"{API}/bots/recaps").status_code == 401


def test_recap_fields_come_from_the_log(client):
    h, (a,) = setup(client)
    make_match("2026-11-10", [(a, "civilian", False, 3, 2)], quote_prefix="yo")
    rc = client.get(f"{API}/bots/recaps", headers=h).get_json()["recaps"][0]
    assert (rc["role"], rc["won"], rc["accused"], rc["out_round"], rc["quote"]) == ("civilian", False, 3, 2, "yo 0")


def test_mark_seen_is_per_owner(client):
    ha, (a,) = setup(client)
    hb, (b,) = setup(client)
    make_match("2026-11-10", [(a, "spy", True, 0, None), (b, "civilian", False, 0, 1)])
    assert client.post(f"{API}/bots/recaps/seen", headers=ha).get_json() == {"ok": True}
    ra = client.get(f"{API}/bots/recaps", headers=ha).get_json()
    assert ra["unseen"] == 0 and ra["recaps"][0]["seen"] is True
    rb = client.get(f"{API}/bots/recaps", headers=hb).get_json()
    assert rb["unseen"] == 1 and rb["recaps"][0]["seen"] is False


def test_recaps_limit_and_order(client):
    h, (a,) = setup(client)
    ids = [make_match(f"2026-10-{d:02d}", [(a, "spy", True, 0, None)], t=1000 + d) for d in range(1, 13)]
    r = client.get(f"{API}/bots/recaps", headers=h).get_json()
    assert len(r["recaps"]) == 10 and r["unseen"] == 12
    assert [x["match_id"] for x in r["recaps"]] == ids[::-1][:10]


def test_match_page_is_public_and_has_no_owner(client):
    h, (a,) = setup(client)
    mid = make_match("2026-11-10", [(a, "spy", True, 0, None)])
    r = client.get(f"{API}/arena/matches/{mid}")
    assert r.status_code == 200
    body = r.get_json()
    text = r.get_data(as_text=True)
    assert not any(k in text for k in ("owner", "owner_player_id", "player_id"))
    assert body["id"] == mid and body["winner"] == "civilians"
    assert body["words"] == {"civilian": "piano", "spy": "organ"}
    assert body["rounds"] and body["day"] == "2026-11-10" and body["lang"] == "en"
    p = body["players"]
    assert p[0] == {"seat": 0, "name": "B0", "avatar": AV, "bot_id": a, "role": "spy", "is_custom": True}
    assert p[1]["bot_id"] is None and p[1]["is_custom"] is False and p[1]["role"] == "civilian"


def test_unknown_or_pruned_match_is_404(client):
    r = client.get(f"{API}/arena/matches/nope")
    assert r.status_code == 404 and r.get_json()["error"] == "not_found"


def test_recaps_route_is_not_shadowed_by_bot_id(client):
    h, _ = guest(client)
    assert client.get(f"{API}/bots/recaps", headers=h).get_json() == {"recaps": [], "unseen": 0}


def test_get_recaps_does_not_touch_last_active(client):
    h, (a,) = setup(client)
    get_conn().execute("UPDATE custom_bots SET last_active=123 WHERE id=?", (a,))
    get_conn().commit()
    client.get(f"{API}/bots/recaps", headers=h)
    assert get_conn().execute("SELECT last_active FROM custom_bots WHERE id=?", (a,)).fetchone()[0] == 123


def test_mark_seen_requires_a_token(client):
    assert client.post(f"{API}/bots/recaps/seen").status_code == 401


def test_mark_seen_is_idempotent(client):
    h, (a,) = setup(client)
    make_match("2026-11-10", [(a, "spy", True, 0, None)])
    for _ in range(2):
        assert client.post(f"{API}/bots/recaps/seen", headers=h).get_json() == {"ok": True}
        assert client.get(f"{API}/bots/recaps", headers=h).get_json()["unseen"] == 0


def test_equal_created_at_orders_by_match_id_desc(client):
    h, (a,) = setup(client)
    ids = [make_match(f"2026-10-{d:02d}", [(a, "spy", True, 0, None)], t=5000) for d in range(1, 5)]
    got = [x["match_id"] for x in client.get(f"{API}/bots/recaps", headers=h).get_json()["recaps"]]
    assert got == sorted(ids, reverse=True)


def test_match_page_has_exactly_the_expected_keys(client):
    h, (a,) = setup(client)
    mid = make_match("2026-11-10", [(a, "spy", True, 0, None)])
    body = client.get(f"{API}/arena/matches/{mid}").get_json()
    assert set(body) == {"id", "day", "lang", "players", "rounds", "words", "winner"}
    for p in body["players"]:
        assert set(p) == {"seat", "name", "avatar", "bot_id", "role", "is_custom"}


def test_recap_and_match_page_keep_the_match_time_name_and_avatar(client):
    h, (a,) = setup(client)
    mid = make_match("2026-11-10", [(a, "spy", True, 0, None)])
    new_av = {"emoji": "🐱", "color": "#ffa94d"}
    r = client.patch(f"{API}/bots/{a}", json={"name": "Renamed", "avatar": new_av}, headers=h)
    assert r.status_code == 200
    rc = client.get(f"{API}/bots/recaps", headers=h).get_json()["recaps"][0]
    page = client.get(f"{API}/arena/matches/{mid}").get_json()["players"][0]
    assert rc["bot_name"] == "B0" == page["name"]
    assert rc["avatar"] == AV == page["avatar"]


def test_recap_falls_back_to_the_live_bot_when_the_log_lacks_it(client):
    h, (a,) = setup(client)
    mid = make_match("2026-11-10", [(a, "spy", True, 0, None)])
    row = get_conn().execute("SELECT log_json FROM arena_matches WHERE id=?", (mid,)).fetchone()
    log = json.loads(row[0])
    log["players"] = [p for p in log["players"] if p["bot_id"] != a]
    get_conn().execute("UPDATE arena_matches SET log_json=? WHERE id=?", (json.dumps(log), mid))
    get_conn().commit()
    r = client.get(f"{API}/bots/recaps", headers=h)
    assert r.status_code == 200
    rc = r.get_json()["recaps"][0]
    assert rc["bot_name"] == "b0" and rc["avatar"] == AV and rc["quote"] is None
