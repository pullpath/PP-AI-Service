from __future__ import annotations

import json

from ai_svc.spy_hunt import clans
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.tests.test_clans import member

DAY = 24 * 3600 * 1000
W0 = 1_794_182_400_000  # Monday 2026-11-09 00:00 UTC
WEEK = 7 * DAY


def at(week_index: int, day: int = 2) -> int:
    return W0 + week_index * WEEK + day * DAY


def mk_clan(name, size):
    lead = member()
    c = clans.create(lead, name, 0)
    ids = [lead]
    for _ in range(size - 1):
        p = member()
        clans.join(p, c["code"])
        ids.append(p)
    return c, ids


def give(clan_id, player_id, pts, ts):
    conn = get_conn()
    conn.execute("INSERT INTO clan_points(key, clan_id, player_id, week, created_day, points,"
                 " created_at) VALUES (?,?,?,?,?,?,?)",
                 (f"t:{clan_id}:{player_id}:{ts}:{pts}", clan_id, player_id, clans.week_of(ts),
                  clans._utc_day(ts), pts, ts))
    conn.commit()


def row(week_index, clan_id):
    return get_conn().execute("SELECT * FROM clan_weeks WHERE week=? AND clan_id=?",
                              (clans.week_of(at(week_index)), clan_id)).fetchone()


def test_pairing_by_size_needs_3_members_and_last_week_points(temp_db):
    a, ai = mk_clan("Aaa", 3)
    b, bi = mk_clan("Bbb", 4)
    small, si = mk_clan("Small", 2)
    idle, ii = mk_clan("Idle", 5)
    for c, ids in ((a, ai), (b, bi), (small, si)):
        give(c["id"], ids[0], 10, at(0))
    clans.roll_weeks(at(1))
    ra, rb = row(1, a["id"]), row(1, b["id"])
    assert ra["rival_id"] == b["id"] and rb["rival_id"] == a["id"]
    assert ra["ghost"] == 0
    assert row(1, small["id"]) is None
    assert row(1, idle["id"]) is None


def test_pairs_neighbours_by_member_count(temp_db):
    made = [mk_clan(n, s) for n, s in (("Three", 3), ("Ten", 10), ("Four", 4), ("Nine", 9))]
    for c, ids in made:
        give(c["id"], ids[0], 10, at(0))
    clans.roll_weeks(at(1))
    by = {c["name"]: c["id"] for c, _ in made}
    assert row(1, by["Three"])["rival_id"] == by["Four"]
    assert row(1, by["Ten"])["rival_id"] == by["Nine"]


def test_odd_clan_gets_ghost_with_floor_50(temp_db):
    made = [mk_clan(n, 3) for n in ("Aaa", "Bbb", "Ccc")]
    for c, ids in made:
        give(c["id"], ids[0], 10, at(0))
    clans.roll_weeks(at(1))
    ghosts = [c for c, _ in made if row(1, c["id"])["ghost"]]
    assert len(ghosts) == 1
    g = ghosts[0]
    assert row(1, g["id"])["rival_id"] is None
    others = [c for c, _ in made if c["id"] != g["id"]]
    give(others[0]["id"], made[0][1][0], 20, at(1))  # whoever; scores 20 and 0 -> avg 10 -> floor 50
    give(g["id"], [ids for c, ids in made if c["id"] == g["id"]][0][0], 60, at(1))
    clans.roll_weeks(at(2))
    r = row(1, g["id"])
    assert r["rival_score"] == 50 and r["own"] == 60 and r["result"] == "won"


def test_ghost_uses_average_of_other_clans_when_above_50(temp_db):
    made = [mk_clan(n, 3) for n in ("Aaa", "Bbb", "Ccc")]
    for c, ids in made:
        give(c["id"], ids[0], 10, at(0))
    clans.roll_weeks(at(1))
    g = next(c for c, _ in made if row(1, c["id"])["ghost"])
    for c, ids in made:
        if c["id"] != g["id"]:
            give(c["id"], ids[0], 100, at(1))
            give(c["id"], ids[1], 60, at(1, 3))
    clans.roll_weeks(at(2))
    assert row(1, g["id"])["rival_score"] == 160


def _pair_two():
    a, ai = mk_clan("Aaa", 3)
    b, bi = mk_clan("Bbb", 3)
    for c, ids in ((a, ai), (b, bi)):
        give(c["id"], ids[0], 10, at(0))
    return (a, ai), (b, bi)


def test_higher_score_wins_tie_is_draw(temp_db):
    (a, ai), (b, bi) = _pair_two()
    clans.roll_weeks(at(1))
    give(a["id"], ai[0], 40, at(1))
    give(b["id"], bi[0], 30, at(1))
    clans.roll_weeks(at(2))
    assert (row(1, a["id"])["result"], row(1, b["id"])["result"]) == ("won", "lost")
    assert row(1, a["id"])["own"] == 40 and row(1, a["id"])["rival_score"] == 30
    give(a["id"], ai[0], 20, at(2))
    give(b["id"], bi[0], 20, at(2))
    clans.roll_weeks(at(3))
    assert (row(2, a["id"])["result"], row(2, b["id"])["result"]) == ("draw", "draw")


def test_draw_keeps_streak_loss_resets(temp_db):
    (a, ai), (b, bi) = _pair_two()
    plan = [(30, 10), (30, 30), (30, 10), (10, 30), (30, 10)]  # won, draw, won, lost, won
    for i, (sa, sb) in enumerate(plan, start=1):
        clans.roll_weeks(at(i))
        give(a["id"], ai[0], sa, at(i))
        give(b["id"], bi[0], sb, at(i))
        clans.roll_weeks(at(i + 1))
        s = clans.season(ai[0], now_ms=at(i + 1))["streak"]
        assert s == [1, 1, 2, 0, 1][i - 1]


def test_history_capped_at_8_newest_first(temp_db):
    (a, ai), (b, bi) = _pair_two()
    for i in range(1, 11):
        clans.roll_weeks(at(i))
        give(a["id"], ai[0], 10 + i, at(i))
        give(b["id"], bi[0], 5, at(i))
    s = clans.season(ai[0], now_ms=at(11))
    assert len(s["history"]) == 8
    assert s["history"][0]["week"] == clans.week_of(at(10))
    assert s["history"][0] == {"week": clans.week_of(at(10)), "result": "won", "own": 20,
                               "rival_score": 5, "rival_name": "Bbb", "ghost": False}


def test_roll_is_idempotent(temp_db):
    (a, ai), (b, bi) = _pair_two()
    clans.roll_weeks(at(1))
    clans.roll_weeks(at(1, 4))
    give(a["id"], ai[0], 10, at(1))
    clans.roll_weeks(at(2))
    clans.roll_weeks(at(2, 1))
    n = get_conn().execute("SELECT COUNT(*) FROM clan_weeks").fetchone()[0]
    # week 1: a+b ; week 2: only a had points in week 1, so a alone faces a practice rival
    assert n == 3
    assert row(2, a["id"])["ghost"] == 1 and row(2, b["id"]) is None
    assert row(1, a["id"])["result"] == "won"


def test_gap_of_three_weeks_closes_each_missed_week_once(temp_db):
    (a, ai), (b, bi) = _pair_two()
    clans.roll_weeks(at(1))
    give(a["id"], ai[0], 10, at(1))
    give(b["id"], bi[0], 20, at(1))
    clans.roll_weeks(at(4))  # weeks 2 and 3 had no traffic
    clans.roll_weeks(at(4, 3))
    assert row(1, a["id"])["result"] == "lost"
    assert get_conn().execute("SELECT COUNT(*) FROM clan_weeks WHERE result IS NULL").fetchone()[0] == 0
    assert get_conn().execute("SELECT COUNT(*) FROM clan_weeks").fetchone()[0] == 2


def test_small_clan_has_no_rival_and_still_scores(temp_db):
    c, ids = mk_clan("Duo", 2)
    give(c["id"], ids[0], 10, at(0))
    clans.roll_weeks(at(1))
    give(c["id"], ids[1], 30, at(1))
    s = clans.season(ids[0], now_ms=at(1, 3))
    assert s["this_week"]["own"] == 30
    assert s["this_week"]["rival"] is None and s["this_week"]["ghost"] is False
    assert s["this_week"]["ends_at"] == W0 + 2 * WEEK


def test_this_week_shows_rival_score_live(temp_db):
    (a, ai), (b, bi) = _pair_two()
    clans.roll_weeks(at(1))
    give(b["id"], bi[0], 25, at(1))
    s = clans.season(ai[0], now_ms=at(1, 3))
    assert s["this_week"]["rival"] == {"name": "Bbb", "badge": clans.BADGES[0], "score": 25}


def test_members_sorted_by_this_week_points(temp_db, conn):
    c, ids = mk_clan("Trio", 3)
    conn.execute("INSERT INTO players(room_id, player_id, seat, name, lang, is_bot, alive,"
                 " connected, joined_at) VALUES ('r', ?, 0, 'Mochi', 'en', 0, 1, 1, 5)", (ids[1],))
    conn.commit()
    give(c["id"], ids[1], 30, at(1))
    give(c["id"], ids[2], 10, at(1))
    m = clans.season(ids[0], now_ms=at(1, 3))["members"]
    assert m[0] == {"name": "Mochi", "points": 30, "is_leader": False}
    assert [x["points"] for x in m] == [30, 10, 0]
    assert m[2]["name"] == "Player" and m[2]["is_leader"] is True


def test_member_joined_mid_week_counts_from_joining(temp_db):
    from ai_svc.spy_hunt.tests.test_clans_points import finish, make_room
    c, ids = mk_clan("Trio", 3)
    late = member()
    finish(make_room([(late, False, "civilian"), (ids[0], False, "spy")]), "civilians")
    clans.join(late, c["code"])
    s = clans.season(ids[0])
    assert next(x for x in s["members"] if x["points"] == 10)  # ids[0] lost: 10
    assert sum(x["points"] for x in s["members"]) == 10


def test_season_exposes_no_email_or_player_id(temp_db):
    (a, ai), (b, bi) = _pair_two()
    clans.roll_weeks(at(1))
    s = json.dumps(clans.season(ai[0], now_ms=at(1, 3)))
    assert "@example.com" not in s
    for p in ai + bi:
        assert p not in s


def test_season_for_non_member_is_none(temp_db):
    assert clans.season(member()) is None


def test_rejoining_member_gets_no_points_back_in_member_list(temp_db, conn):
    c, ids = mk_clan("Trio", 3)
    b = ids[1]
    give(c["id"], b, 60, at(1))
    clans.leave(b)
    clans.join(b, c["code"])
    conn.execute("UPDATE clan_members SET joined_at=? WHERE player_id=?", (at(1, 3), b))
    conn.commit()
    s = clans.season(ids[0], now_ms=at(1, 4))
    assert [m["points"] for m in s["members"]] == [0, 0, 0]
    assert s["this_week"]["own"] == 60  # the clan keeps what b earned


def test_display_name_lookup_uses_an_index(temp_db, conn):
    plan = " ".join(r[3] for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT name FROM players WHERE player_id=? AND is_bot=0"
        " ORDER BY joined_at DESC, rowid DESC LIMIT 1", ("x",)))
    assert "SCAN players" not in plan


def test_viewing_a_season_does_not_take_the_write_lock(temp_db, conn):
    import sqlite3
    c, ids = mk_clan("Trio", 3)
    clans.season(ids[0])  # rolls once, meta now current
    other = sqlite3.connect(temp_db, timeout=0.1)
    other.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("PRAGMA busy_timeout=100")
        assert clans.season(ids[0]) is not None
    finally:
        other.rollback()
        other.close()
