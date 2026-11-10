from __future__ import annotations

import json
import sqlite3

from ai_svc.spy_hunt import db, game
from ai_svc.spy_hunt.config import GameConfig

from .test_rooms import API, create, guest, join, room_row

AV = {"emoji": "🦊", "color": "#ff6b6b"}
OUT = {"voice": "dry", "style": "brief", "quirk": "emoji"}


def mk(client, h, name="Mochi"):
    r = client.post(f"{API}/bots", json={"name": name, "avatar": AV, "outfit": OUT}, headers=h)
    assert r.status_code == 201
    return r.get_json()["id"]


def bots(client, code, h, **body):
    return client.post(f"{API}/rooms/{code}/bots", json=body, headers=h)


def err(r):
    return r.status_code, r.get_json()["error"]


def room_with(client, n_members=1):
    h, pid, snap = create(client)
    code = snap["code"]
    members = [(h, pid)]
    for i in range(n_members):
        hh, r = join(client, code, name=f"M{i}")
        members.append((hh, r.get_json()["players"][-1] and None))
    return code, h, [m[0] for m in members[1:]]


def bot_players(snap):
    return [p for p in snap["players"] if p["is_bot"]]


def test_member_adds_own_bot_and_snapshot_shows_avatar_not_owner(client, conn):
    code, h, (h2,) = room_with(client)
    bid = mk(client, h2)
    owner_pid = conn.execute("SELECT owner_player_id FROM custom_bots WHERE id=?", (bid,)).fetchone()[0]
    r = bots(client, code, h2, action="add", bot_id=bid)
    assert r.status_code == 200
    (b,) = bot_players(r.get_json())
    assert b["is_bot"] is True and b["avatar"] == AV and b["bot_id"] == bid and b["name"] == "Mochi"
    for bad in ("bot_owner_id", "outfit_json", owner_pid):
        assert bad not in r.get_data(as_text=True)
    rid = room_row(conn, code)["id"]
    ev = [json.loads(e["payload_json"]) for e in conn.execute(
        "SELECT payload_json FROM events WHERE room_id=? AND type='player_joined'", (rid,))]
    assert ev[-1]["player"] == {k: b[k] for k in b}
    row = conn.execute("SELECT * FROM players WHERE room_id=? AND is_bot=1", (rid,)).fetchone()
    assert row["bot_persona"] == "custom" and row["bot_owner_id"] == owner_pid
    assert json.loads(row["outfit_json"]) == OUT


def test_second_custom_bot_from_the_same_owner_is_refused(client):
    code, h, (h2, h3) = room_with(client, 2)
    a, b = mk(client, h2, "A"), mk(client, h2, "B")
    assert bots(client, code, h2, action="add", bot_id=a).status_code == 200
    assert err(bots(client, code, h2, action="add", bot_id=b)) == (409, "bot_in_room")
    assert bots(client, code, h3, action="add", bot_id=mk(client, h3)).status_code == 200


def test_cannot_add_someone_elses_or_missing_bot(client):
    code, h, (h2,) = room_with(client)
    other = mk(client, h)
    assert err(bots(client, code, h2, action="add", bot_id=other)) == (404, "not_found")
    assert err(bots(client, code, h2, action="add", bot_id="nope1234")) == (404, "not_found")


def test_non_member_and_non_host_random_add(client):
    code, h, (h2,) = room_with(client)
    h3, _ = guest(client, ip="10.0.0.9")
    assert err(bots(client, code, h3, action="add", bot_id=mk(client, h3))) == (403, "not_member")
    assert err(bots(client, code, h2, action="add")) == (403, "not_host")


def test_add_after_start_and_when_full(client, conn):
    code, h, (h2,) = room_with(client)
    bid = mk(client, h2)
    client.patch(f"{API}/rooms/{code}/settings", json={"bot_fill": True}, headers=h)
    rid = room_row(conn, code)["id"]
    for _ in range(GameConfig().max_players - 2):
        assert bots(client, code, h, action="add").status_code == 200
    assert err(bots(client, code, h2, action="add", bot_id=bid)) == (409, "room_full")
    conn.execute("UPDATE rooms SET status='playing' WHERE id=?", (rid,))
    conn.commit()
    assert err(bots(client, code, h2, action="add", bot_id=bid)) == (409, "not_lobby")


def test_edit_or_delete_after_adding_does_not_change_the_room(client):
    code, h, (h2,) = room_with(client, 1)
    bid = mk(client, h2)
    before = bots(client, code, h2, action="add", bot_id=bid).get_json()["players"]
    client.patch(f"{API}/bots/{bid}", json={"name": "Renamed"}, headers=h2)
    client.delete(f"{API}/bots/{bid}", headers=h2)
    after = client.get(f"{API}/rooms/{code}", headers=h).get_json()["players"]
    assert [p for p in after if p["is_bot"]] == bot_players({"players": before})
    assert client.post(f"{API}/rooms/{code}/start", headers=h).status_code == 200


def test_remove_rules(client):
    code, h, (h2, h3) = room_with(client, 2)
    a, b = mk(client, h2, "A"), mk(client, h3, "B")
    seat_a = next(p["seat"] for p in bot_players(bots(client, code, h2, action="add", bot_id=a).get_json()))
    snap = bots(client, code, h3, action="add", bot_id=b).get_json()
    seat_b = next(p["seat"] for p in bot_players(snap) if p["name"] == "B")
    bots(client, code, h, action="add")
    snap = client.get(f"{API}/rooms/{code}", headers=h).get_json()
    seat_builtin = next(p["seat"] for p in bot_players(snap) if p["bot_id"] is None)
    human = next(p["seat"] for p in snap["players"] if not p["is_bot"])
    assert err(bots(client, code, h3, action="remove", seat=seat_a)) == (403, "not_allowed")
    assert err(bots(client, code, h2, action="remove", seat=seat_builtin)) == (403, "not_allowed")
    assert err(bots(client, code, h, action="remove", seat=human)) == (404, "not_found")
    assert err(bots(client, code, h, action="remove", seat=99)) == (404, "not_found")
    assert err(bots(client, code, h, action="remove", seat=True)) == (400, "bad_request")
    assert err(bots(client, code, h, action="remove", seat="1")) == (400, "bad_request")
    assert bots(client, code, h, action="remove", seat=seat_a).status_code == 200
    assert bots(client, code, h3, action="remove", seat=seat_b).status_code == 200
    assert len(bot_players(client.get(f"{API}/rooms/{code}", headers=h).get_json())) == 1
    assert bots(client, code, h, action="remove").status_code == 200
    assert bot_players(client.get(f"{API}/rooms/{code}", headers=h).get_json()) == []


def test_owner_leaving_lobby_takes_the_bot_with_them(client, conn):
    code, h, (h2,) = room_with(client)
    bots(client, code, h2, action="add", bot_id=mk(client, h2))
    rid = room_row(conn, code)["id"]
    assert client.post(f"{API}/rooms/{code}/leave", headers=h2).status_code == 200
    left = conn.execute("SELECT 1 FROM events WHERE room_id=? AND type='player_left'", (rid,)).fetchall()
    assert len(left) == 2
    assert conn.execute("SELECT COUNT(*) FROM players WHERE room_id=?", (rid,)).fetchone()[0] == 1

    code, h, (h2,) = room_with(client)
    bots(client, code, h2, action="add", bot_id=mk(client, h2))
    rid = room_row(conn, code)["id"]
    conn.execute("UPDATE rooms SET status='finished' WHERE id=?", (rid,))
    conn.commit()
    client.post(f"{API}/rooms/{code}/leave", headers=h2)
    assert conn.execute("SELECT COUNT(*) FROM players WHERE room_id=?", (rid,)).fetchone()[0] == 1


def test_leaving_mid_game_keeps_custom_bot(client, conn):
    code, h, (h2,) = room_with(client)
    bid = mk(client, h2)
    bots(client, code, h2, action="add", bot_id=bid)
    rid = room_row(conn, code)["id"]
    conn.execute("UPDATE rooms SET status='playing' WHERE id=?", (rid,))
    conn.commit()
    client.post(f"{API}/rooms/{code}/leave", headers=h2)
    snap = client.get(f"{API}/rooms/{code}", headers=h).get_json()
    assert len(snap["players"]) == 3
    custom = [p for p in snap["players"] if p["bot_id"] == bid]
    assert len(custom) == 1
    others = [p for p in bot_players(snap) if p["bot_id"] is None]
    assert len(others) == 1 and others[0]["avatar"] is None


def test_rematch_keeps_custom_bots(client, conn):
    code, h, (h2,) = room_with(client)
    bid = mk(client, h2)
    bots(client, code, h2, action="add", bot_id=bid)
    rid = room_row(conn, code)["id"]
    conn.execute("UPDATE rooms SET status='finished' WHERE id=?", (rid,))
    conn.commit()
    r = client.post(f"{API}/rooms/{code}/rematch", headers=h)
    assert r.status_code == 200
    assert [p["bot_id"] for p in bot_players(r.get_json())] == [bid]


def test_start_fill_counts_custom_bots(client, conn):
    h, _, snap = create(client)
    code = snap["code"]
    bots(client, code, h, action="add", bot_id=mk(client, h))
    assert client.post(f"{API}/rooms/{code}/start", headers=h).status_code == 200
    rid = room_row(conn, code)["id"]
    rows = conn.execute("SELECT bot_id, bot_persona FROM players WHERE room_id=?", (rid,)).fetchall()
    assert len(rows) == 4
    assert sum(1 for r in rows if r["bot_persona"] == "custom") == 1


def test_old_players_table_is_migrated(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.close_conn()
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE players(room_id TEXT, player_id TEXT, seat INTEGER, name TEXT, lang TEXT,"
              " is_bot INTEGER, bot_persona TEXT, role TEXT, alive INTEGER, connected INTEGER,"
              " joined_at INTEGER, PRIMARY KEY(room_id, seat))")
    c.execute("INSERT INTO players VALUES('r','p',0,'Old','en',0,NULL,NULL,1,1,0)")
    c.commit()
    c.close()
    db.init_db()
    db.init_db()
    conn = db.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(players)")}
    assert {"avatar_emoji", "avatar_color", "bot_id", "bot_owner_id", "outfit_json"} <= cols
    assert conn.execute("SELECT name FROM players").fetchone()["name"] == "Old"
    db.close_conn()
