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
