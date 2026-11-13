from __future__ import annotations

import json

from ai_svc.spy_hunt import credits
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.tests.test_clans import guest
from ai_svc.spy_hunt.tests.test_clans_points import finish, make_room


def test_game_over_event_carries_credits_and_totals_increase(temp_db):
    a, b = guest(), guest()
    before = credits.total(get_conn(), a)
    rid = make_room([(a, False, "spy"), (b, False, "civilian"), ("b1", True, "civilian")])
    finish(rid, "spies")
    row = get_conn().execute(
        "SELECT payload_json FROM events WHERE room_id=? AND type='game_over'", (rid,)).fetchone()
    payload = json.loads(row[0])
    assert payload["credits"]
    seats = {r[0]: r[1] for r in get_conn().execute(
        "SELECT player_id, seat FROM players WHERE room_id=?", (rid,))}
    assert set(payload["credits"]) == {str(seats[a]), str(seats[b])}
    assert a not in payload["credits"] and b not in payload["credits"]
    assert all(v > 0 for v in payload["credits"].values())
    assert set(payload["credit_parts"]) == set(payload["credits"])
    for seat, parts in payload["credit_parts"].items():
        assert parts[0]["kind"] == "played"
        assert sum(p["n"] for p in parts) == payload["credits"][seat]
    assert "winner" in payload and "roles" in payload and "words" in payload
    assert credits.total(get_conn(), a) > before
