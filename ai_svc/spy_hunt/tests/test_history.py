from __future__ import annotations

from ai_svc.spy_hunt import game, history, store
from ai_svc.spy_hunt.tests.test_clans_points import finish, make_room


def test_record_game_writes_one_row_per_human(conn):
    rid = make_room([("a", False, "civilian"), ("b", False, "spy"), ("bot1", True, "civilian")])
    finish(rid, "civilians")
    rows = conn.execute("SELECT player_id FROM room_result_players WHERE room_id=?", (rid,)).fetchall()
    assert {r["player_id"] for r in rows} == {"a", "b"}


def test_record_game_writes_the_room_result_row(conn):
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    row = conn.execute("SELECT winner FROM room_results WHERE room_id=?", (rid,)).fetchone()
    assert row["winner"] == "civilians"


def test_record_game_is_idempotent_on_retried_finish(conn):
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    rows = conn.execute("SELECT * FROM players WHERE room_id=?", (rid,)).fetchall()
    with store.tx(rid) as c:
        history.record_game(c, dict(conn.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()),
                            rows, "civilians", {}, {})
    assert conn.execute("SELECT COUNT(*) FROM room_results WHERE room_id=?", (rid,)).fetchone()[0] == 1


def test_record_game_still_writes_below_min_humans(conn):
    rid = make_room([("a", False, "civilian"), ("bot1", True, "spy")])
    finish(rid, "civilians")
    row = conn.execute("SELECT player_id FROM room_result_players WHERE room_id=?", (rid,)).fetchone()
    assert row["player_id"] == "a"


def test_finish_still_succeeds_when_record_game_raises(conn, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(history, "record_game", boom)
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    assert conn.execute("SELECT status FROM rooms WHERE id=?", (rid,)).fetchone()[0] == "finished"
