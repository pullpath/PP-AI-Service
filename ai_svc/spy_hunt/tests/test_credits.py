from __future__ import annotations

from ai_svc.spy_hunt import credits
from ai_svc.spy_hunt.db import get_conn


def test_credit_tables_exist(temp_db):
    cols = {r[1] for r in get_conn().execute("PRAGMA table_info(player_credits)")}
    assert cols == {"key", "player_id", "credits", "created_day", "created_at"}
    tcols = {r[1] for r in get_conn().execute("PRAGMA table_info(player_total_credits)")}
    assert tcols == {"player_id", "credits", "updated_at"}


def test_add_awards_and_updates_total(temp_db):
    with get_conn() as c:
        assert credits._add(c, "k1", "g1", 20, 1000) == 20
    assert credits.total(get_conn(), "g1") == 20


def test_add_is_idempotent_by_key(temp_db):
    with get_conn() as c:
        credits._add(c, "k1", "g1", 20, 1000)
        assert credits._add(c, "k1", "g1", 20, 2000) == 0   # same key, no double
    assert credits.total(get_conn(), "g1") == 20


def test_daily_cap_clamps_and_total_matches_ledger(temp_db):
    with get_conn() as c:
        credits._add(c, "a", "g1", 490, 1000)
        assert credits._add(c, "b", "g1", 20, 1000) == 10    # only 10 of 20 fits under 500
    led = get_conn().execute("SELECT COALESCE(SUM(credits),0) FROM player_credits WHERE player_id='g1'").fetchone()[0]
    assert led == 500 and credits.total(get_conn(), "g1") == 500


def test_guest_earns_without_clan(temp_db):
    with get_conn() as c:
        assert credits._add(c, "k", "guest-no-clan", 10, 1000) == 10


def test_rank_for_thresholds(temp_db):
    assert credits.rank_for(0)["key"] == "rookie"
    assert credits.rank_for(249)["key"] == "rookie"
    assert credits.rank_for(750)["key"] == "hunter"
    assert credits.rank_for(12000)["key"] == "legend"


def test_summary_shape(temp_db):
    with get_conn() as c:
        credits._add(c, "k", "g1", 300, 1000)
    s = credits.summary("g1")
    assert s["credits"] == 300 and s["rank"]["key"] == "sleuth"
    assert s["next"]["key"] == "hunter" and s["next"]["remaining"] == 450


def test_award_game_returns_per_player_delta(temp_db):
    rows = [{"player_id": "a", "is_bot": 0, "role": "spy"},
            {"player_id": "b", "is_bot": 0, "role": "civilian"},
            {"player_id": "z", "is_bot": 1, "role": "civilian"}]
    with get_conn() as c:
        d = credits.award_game(c, "r1", 1, rows, "spies")
    assert d == {"a": 20, "b": 10}   # spy won (+10+10), civ played (+10), bot excluded


def test_award_game_needs_two_humans(temp_db):
    rows = [{"player_id": "a", "is_bot": 0, "role": "spy"}, {"player_id": "z", "is_bot": 1, "role": "civilian"}]
    with get_conn() as c:
        assert credits.award_game(c, "r1", 1, rows, "spies") == {}


def test_award_daily_solved_adds_streak_bonus(temp_db):
    with get_conn() as c:
        assert credits.award_daily(c, "g1", "2026-11-13", True, streak=4) == 10 + 10 + 20


def test_award_daily_missed_has_no_streak_bonus(temp_db):
    with get_conn() as c:
        assert credits.award_daily(c, "g1", "2026-11-13", False, streak=9) == 10


def test_award_daily_replay_is_zero(temp_db):
    with get_conn() as c:
        credits.award_daily(c, "g1", "2026-11-13", True, streak=4)
        assert credits.award_daily(c, "g1", "2026-11-13", True, streak=4) == 0


def test_award_game_parts_name_each_source(temp_db):
    rows = [{"player_id": "a", "is_bot": 0, "role": "spy"},
            {"player_id": "b", "is_bot": 0, "role": "civilian"}]
    with get_conn() as c:
        d = credits.award_game_parts(c, "r1", 1, rows, "spies")
    assert d == {"a": [{"kind": "played", "n": 10}, {"kind": "won", "n": 10}],
                 "b": [{"kind": "played", "n": 10}]}


def test_award_daily_parts_include_streak(temp_db):
    with get_conn() as c:
        parts = credits.award_daily_parts(c, "g1", "2026-11-13", True, streak=3)
    assert parts == [{"kind": "daily", "n": 10}, {"kind": "found", "n": 10}, {"kind": "streak", "n": 15}]


def test_parts_shrink_under_the_cap_and_never_overstate(temp_db):
    with get_conn() as c:
        credits._add(c, "x", "a", 485, credits._now_ms())
        rows = [{"player_id": "a", "is_bot": 0, "role": "spy"},
                {"player_id": "b", "is_bot": 0, "role": "civilian"}]
        d = credits.award_game_parts(c, "r1", 1, rows, "spies")
    assert d["a"] == [{"kind": "played", "n": 10}, {"kind": "won", "n": 5}]


def test_replayed_parts_are_empty(temp_db):
    with get_conn() as c:
        credits.award_daily_parts(c, "g1", "2026-11-13", True, streak=1)
        assert credits.award_daily_parts(c, "g1", "2026-11-13", True, streak=1) == []
