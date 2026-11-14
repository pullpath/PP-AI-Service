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


from ai_svc.spy_hunt.tests.test_accounts import _auth_header, _make_guest


def test_games_for_lists_most_recent_first(conn, monkeypatch):
    import itertools
    clock = itertools.count(1000, 10)
    monkeypatch.setattr(history.time, "time", lambda: next(clock) / 1000)
    rid1 = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid1, "civilians")
    rid2 = make_room([("a", False, "spy"), ("b", False, "civilian")])
    finish(rid2, "spies")
    games = history.games_for("a")
    assert [g["room_id"] for g in games] == [rid2, rid1]
    assert games[0]["your_role"] == "spy" and games[0]["won"] is True


def test_games_for_only_includes_the_requested_player(conn):
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    assert history.games_for("nobody") == []


def _game_no(conn, rid):
    return conn.execute("SELECT game_no FROM room_results WHERE room_id=?", (rid,)).fetchone()[0]


def test_game_detail_marks_the_viewer_and_hides_other_player_ids(conn):
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    detail = history.game_detail("a", rid, _game_no(conn, rid))
    you = next(r for r in detail["roles"] if r["is_you"])
    other = next(r for r in detail["roles"] if not r["is_you"])
    assert you["role"] == "civilian"
    assert "player_id" not in you and "player_id" not in other


def test_game_detail_returns_none_for_a_non_participant(conn):
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    assert history.game_detail("stranger", rid, _game_no(conn, rid)) is None


def test_my_games_route_requires_auth(client):
    assert client.get("/api/spy-hunt/me/games").status_code == 401


def test_my_game_detail_route_404s_for_a_foreign_game(client):
    guest = _make_guest(client)
    r = client.get("/api/spy-hunt/me/games/no-such-room/1", headers=_auth_header(guest))
    assert r.status_code == 404


def test_game_detail_words_is_an_object_when_the_room_had_no_pair(conn):
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    detail = history.game_detail("a", rid, _game_no(conn, rid))
    assert detail["words"] == {}


def test_a_failed_history_write_leaves_no_partial_rows(conn, monkeypatch):
    real = history.json.dumps
    calls = {"n": 0}

    def flaky(obj, *a, **k):
        calls["n"] += 1
        if calls["n"] == 3:  # roles, words ok; first player's credit_parts fails
            raise RuntimeError("boom")
        return real(obj, *a, **k)
    monkeypatch.setattr(history.json, "dumps", flaky)
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    finish(rid, "civilians")
    assert conn.execute("SELECT status FROM rooms WHERE id=?", (rid,)).fetchone()[0] == "finished"
    assert conn.execute("SELECT COUNT(*) FROM room_results WHERE room_id=?", (rid,)).fetchone()[0] == 0


def test_game_detail_route_404s_for_an_oversized_game_no(client):
    guest = _make_guest(client)
    r = client.get("/api/spy-hunt/me/games/x/99999999999999999999", headers=_auth_header(guest))
    assert r.status_code == 404


def test_finish_survives_history_write_that_aborts_the_transaction(conn, monkeypatch):
    def abort(c, *_a, **_k):
        c.execute("ROLLBACK")  # sqlite can auto-rollback on SQLITE_FULL; the savepoint is then gone
        raise RuntimeError("boom")
    monkeypatch.setattr(history, "record_game", abort)
    rid = make_room([("a", False, "civilian"), ("b", False, "spy")])
    try:
        finish(rid, "civilians")
    except Exception as e:  # noqa: BLE001
        assert "savepoint" not in str(e).lower(), e
