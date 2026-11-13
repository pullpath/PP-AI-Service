from __future__ import annotations

from ai_svc.spy_hunt import credits, visibility
from ai_svc.spy_hunt.tests.test_rooms import API, create, guest, join


def seed(conn, pid, n):
    conn.execute("INSERT INTO player_total_credits(player_id, credits, updated_at) VALUES(?,?,0)", (pid, n))
    conn.commit()


def test_credits_endpoint_shape(client, conn):
    h, pid = guest(client)
    seed(conn, pid, 5000)
    r = client.get(f"{API}/credits", headers=h)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"credits", "today", "rank", "next", "rules"}
    assert body["rules"]["game"]["played"] == credits.GAME_PLAY and body["rules"]["daily_cap"] == credits.CREDITS_DAILY_CAP
    assert body["credits"] == 5000
    assert body["rank"] == credits.rank_for(5000)
    assert client.get(f"{API}/credits").status_code == 401


def test_credits_endpoint_zero(client):
    h, _ = guest(client)
    body = client.get(f"{API}/credits", headers=h).get_json()
    assert body["credits"] == 0 and body["rank"]["index"] == 0


def test_credit_ranks_batched(conn):
    assert visibility.credit_ranks([]) == {}
    seed(conn, "p1", 10 ** 7)
    out = visibility.credit_ranks(["p1", "p2"])
    assert out["p1"] == credits.rank_for(10 ** 7)["index"] > 0
    assert out.get("p2", 0) == 0


def _row(conn, is_bot):
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _t(x)")
    return {"seat": 1, "name": "N", "lang": "en", "is_bot": is_bot, "alive": 1, "connected": 1,
            "avatar_emoji": None, "avatar_color": None, "bot_id": None, "player_id": "p1"}


def test_public_player_rank(conn):
    seed(conn, "p1", 10 ** 7)
    idx = credits.rank_for(10 ** 7)["index"]
    assert visibility.public_player(_row(conn, 0), None, {}, {"p1": 3})["rank"] == 3
    assert visibility.public_player(_row(conn, 0), None)["rank"] == idx
    assert visibility.public_player(_row(conn, 0), None, {}, {})["rank"] == 0
    assert visibility.public_player(_row(conn, 1), None, {}, {"p1": 3})["rank"] is None


def test_snapshot_players_carry_rank(client, conn):
    h, pid, snap = create(client)
    seed(conn, pid, 10 ** 7)
    snap = client.get(f"{API}/rooms/{snap['code']}", headers=h).get_json()
    assert snap["players"][0]["rank"] == credits.rank_for(10 ** 7)["index"]
