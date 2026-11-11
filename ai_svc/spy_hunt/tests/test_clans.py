from __future__ import annotations

import itertools

import pytest

from ai_svc.spy_hunt import accounts, auth, clans
from ai_svc.spy_hunt.store import StoreError

_n = itertools.count()


def member(conn=None) -> str:
    pid, _ = auth.create_guest()
    accounts.register(pid, f"u{next(_n)}@example.com", "longenough")
    return pid


def guest() -> str:
    pid, _ = auth.create_guest()
    return pid


def _err(fn, *a):
    with pytest.raises(StoreError) as e:
        fn(*a)
    return e.value


def test_guest_cannot_create(temp_db):
    e = _err(clans.create, guest(), "Foxes", 0)
    assert (e.status, e.code) == (403, "register_required")


def test_guest_cannot_join(temp_db):
    c = clans.create(member(), "Foxes", 0)
    e = _err(clans.join, guest(), c["code"])
    assert (e.status, e.code) == (403, "register_required")


def test_create_and_name_unique_case_insensitive(temp_db):
    c = clans.create(member(), "Foxes", 0)
    assert c["name"] == "Foxes"
    assert c["badge"] == clans.BADGES[0]
    assert len(c["code"]) == 6
    e = _err(clans.create, member(), " foxes ", 1)
    assert (e.status, e.code) == (409, "name_taken")


@pytest.mark.parametrize("name", ["ab", "x" * 21, "", None, 5])
def test_name_length_bounds(temp_db, name):
    e = _err(clans.create, member(), name, 0)
    assert (e.status, e.code) == (400, "bad_name")


def test_bad_badge(temp_db):
    e = _err(clans.create, member(), "Foxes", len(clans.BADGES))
    assert (e.status, e.code) == (400, "bad_badge")


def test_already_in_clan_409(temp_db):
    p = member()
    clans.create(p, "Foxes", 0)
    assert _err(clans.create, p, "Wolves", 0).code == "already_in_clan"
    other = clans.create(member(), "Wolves", 0)
    assert _err(clans.join, p, other["code"]).code == "already_in_clan"


def test_join_unknown_code_404(temp_db):
    e = _err(clans.join, member(), "ZZZZZZ")
    assert (e.status, e.code) == (404, "no_clan")


def test_join_by_code_and_full_at_30(temp_db):
    c = clans.create(member(), "Foxes", 0)
    for _ in range(clans.MAX_MEMBERS - 1):
        clans.join(member(), c["code"].lower())
    e = _err(clans.join, member(), c["code"])
    assert (e.status, e.code) == (409, "clan_full")


def test_membership(temp_db):
    p = member()
    assert clans.membership(p) is None
    c = clans.create(p, "Foxes", 2)
    m = clans.membership(p)
    assert m["clan_id"] == c["id"] and m["name"] == "Foxes" and m["badge"] == clans.BADGES[2]
    assert isinstance(m["joined_at"], int)


def test_leave_when_not_in_clan(temp_db):
    e = _err(clans.leave, member())
    assert (e.status, e.code) == (409, "not_in_clan")


def test_leader_leaves_earliest_joined_takes_over(temp_db, conn):
    lead, a, b = member(), member(), member()
    c = clans.create(lead, "Foxes", 0)
    clans.join(b, c["code"])
    clans.join(a, c["code"])
    conn.execute("UPDATE clan_members SET joined_at=1 WHERE player_id=?", (a,))
    conn.execute("UPDATE clan_members SET joined_at=2 WHERE player_id=?", (b,))
    conn.commit()
    clans.leave(lead)
    row = conn.execute("SELECT leader_id FROM clans WHERE id=?", (c["id"],)).fetchone()
    assert row["leader_id"] == a
    assert clans.membership(lead) is None


def test_last_member_leaving_deletes_clan(temp_db, conn):
    p = member()
    c = clans.create(p, "Foxes", 0)
    clans.leave(p)
    assert conn.execute("SELECT COUNT(*) FROM clans WHERE id=?", (c["id"],)).fetchone()[0] == 0
    # the name is free again
    clans.create(member(), "Foxes", 0)


def test_list_open_excludes_full_and_caps_20_newest_first(temp_db, conn):
    made = []
    for i in range(22):
        made.append(clans.create(member(), f"Clan {i:02d}", 0))
        conn.execute("UPDATE clans SET created_at=? WHERE id=?", (i, made[-1]["id"]))
    conn.commit()
    full = made[21]
    for _ in range(clans.MAX_MEMBERS - 1):
        clans.join(member(), full["code"])
    listed = clans.list_open()
    assert len(listed) == 20
    assert listed[0]["name"] == "Clan 20"
    assert all(x["name"] != "Clan 21" for x in listed)
    assert {"id", "name", "badge", "members", "code"} <= set(listed[0])
