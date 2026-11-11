from __future__ import annotations

import itertools

import pytest

from ai_svc.spy_hunt import clans, game, puzzles, store
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.tests.puzzle_fixtures import sample_puzzle
from ai_svc.spy_hunt.tests.test_clans import guest, member

_room_n = itertools.count()


def points(clan_id=None, player_id=None):
    q, a = "SELECT COALESCE(SUM(points), 0) FROM clan_points WHERE 1=1", []
    if clan_id:
        q += " AND clan_id=?"
        a.append(clan_id)
    if player_id:
        q += " AND player_id=?"
        a.append(player_id)
    return get_conn().execute(q, a).fetchone()[0]


def make_room(seats):
    """seats: list of (player_id, is_bot, role). Returns room_id, playing."""
    conn = get_conn()
    rid = f"room{next(_room_n)}"
    conn.execute("INSERT INTO rooms(id, code, host_player_id, main_lang, config_json, status,"
                 " round, game_no, version) VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, rid[-4:].upper().rjust(4, "X"), seats[0][0], "en", "{}", "playing", 1, 1, 0))
    for i, (pid, bot, role) in enumerate(seats):
        conn.execute("INSERT INTO players(room_id, player_id, seat, name, lang, is_bot, role, alive,"
                     " connected, joined_at) VALUES (?,?,?,?,?,?,?,1,1,0)",
                     (rid, pid, i, f"P{i}", "en", int(bot), role))
    conn.commit()
    return rid


def finish(rid, winner):
    with store.tx(rid) as c:
        game._finish(c, rid, [], winner, [])


def test_week_of_is_utc_monday():
    # 2026-11-11 is a Wednesday
    assert clans.week_of(1_794_398_400_000) == "2026-11-09"  # 2026-11-11 12:00 UTC
    assert clans.week_of(1_794_182_400_000) == "2026-11-09"  # Monday 00:00 UTC
    assert clans.week_of(1_794_182_399_999) == "2026-11-02"  # Sunday 23:59:59.999


def test_game_award_20_for_winner_10_for_loser(temp_db):
    spy, civ = member(), member()
    c = clans.create(spy, "Foxes", 0)
    clans.join(civ, c["code"])
    rid = make_room([(spy, False, "spy"), (civ, False, "civilian"), ("b1", True, "civilian")])
    finish(rid, "spies")
    assert points(player_id=spy) == 20
    assert points(player_id=civ) == 10
    assert points(clan_id=c["id"]) == 30


def test_no_award_for_single_human_room_or_no_winner(temp_db):
    a, b = member(), member()
    c = clans.create(a, "Foxes", 0)
    clans.join(b, c["code"])
    finish(make_room([(a, False, "spy"), ("b1", True, "civilian"), ("b2", True, "civilian")]), "spies")
    assert points(clan_id=c["id"]) == 0
    finish(make_room([(a, False, "spy"), (b, False, "civilian")]), None)
    assert points(clan_id=c["id"]) == 0


def test_bot_seats_never_earn(temp_db, conn):
    a, b = member(), member()
    c = clans.create(a, "Foxes", 0)
    # b is in the clan but sits in this game as a bot (took over after leaving)
    clans.join(b, c["code"])
    finish(make_room([(a, False, "civilian"), (b, True, "civilian"), (guest(), False, "spy")]), "civilians")
    assert points(player_id=b) == 0
    assert points(player_id=a) == 20


def test_award_idempotent_on_retried_finish(temp_db):
    a, b = member(), member()
    clans.create(a, "Foxes", 0)
    rid = make_room([(a, False, "civilian"), (b, False, "spy")])
    finish(rid, "civilians")
    rows = get_conn().execute("SELECT * FROM players WHERE room_id=?", (rid,)).fetchall()
    with store.tx(rid) as c:
        clans.award_game(c, rid, 1, rows, "civilians")
    assert points(player_id=a) == 20
    assert get_conn().execute("SELECT COUNT(*) FROM clan_points").fetchone()[0] == 1


def test_award_error_does_not_break_finish(temp_db, monkeypatch):
    a, b = member(), member()
    clans.create(a, "Foxes", 0)

    def boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(clans, "membership", boom)
    rid = make_room([(a, False, "civilian"), (b, False, "spy")])
    finish(rid, "civilians")
    assert get_conn().execute("SELECT status FROM rooms WHERE id=?", (rid,)).fetchone()[0] == "finished"


def test_non_member_and_guest_unaffected(temp_db):
    a, g = member(), guest()
    finish(make_room([(a, False, "civilian"), (g, False, "spy")]), "spies")
    assert get_conn().execute("SELECT COUNT(*) FROM clan_points").fetchone()[0] == 0


def test_points_go_to_clan_at_time_of_game_after_switching_clans(temp_db):
    a, other = member(), member()
    first = clans.create(a, "Foxes", 0)
    finish(make_room([(a, False, "civilian"), (other, False, "spy")]), "civilians")
    clans.leave(a)
    second = clans.create(a, "Wolves", 0)
    finish(make_room([(a, False, "civilian"), (other, False, "spy")]), "spies")
    # Foxes was deleted when its only member left, but the row it earned stays keyed to it
    assert points(clan_id=first["id"]) == 20
    assert points(clan_id=second["id"]) == 10


def test_leaver_points_stay_with_clan(temp_db):
    a, b = member(), member()
    c = clans.create(a, "Foxes", 0)
    clans.join(b, c["code"])
    finish(make_room([(a, False, "civilian"), (b, False, "spy")]), "civilians")
    clans.leave(b)
    assert points(clan_id=c["id"]) == 30


def test_daily_cap_100_per_player_per_day(temp_db):
    a, b = member(), member()
    clans.create(a, "Foxes", 0)
    for _ in range(6):
        finish(make_room([(a, False, "civilian"), (b, False, "spy")]), "civilians")
    assert points(player_id=a) == 100


@pytest.fixture
def puzzle_day(monkeypatch):
    day = puzzles.utc_day()
    public, answer = sample_puzzle(2)
    puzzles.insert_ready(public, answer, 2, "p-0")
    return day


def test_daily_award_10_finished_20_solved(temp_db, puzzle_day):
    solver, loser = member(), member()
    c = clans.create(solver, "Foxes", 0)
    clans.join(loser, c["code"])
    puzzles.get_today(solver, puzzle_day)
    puzzles.guess_spy(solver, 2, puzzle_day)
    assert points(player_id=solver) == 0  # not finished until the word stage is done
    puzzles.guess_word(solver, None, puzzle_day)
    assert points(player_id=solver) == 20
    puzzles.get_today(loser, puzzle_day)
    puzzles.guess_spy(loser, 0, puzzle_day)
    puzzles.guess_spy(loser, 1, puzzle_day)
    assert points(player_id=loser) == 10
