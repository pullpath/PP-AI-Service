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
    assert set(payload["credits"]) == {a, b}
    assert "winner" in payload and "roles" in payload and "words" in payload
    assert credits.total(get_conn(), a) > before
