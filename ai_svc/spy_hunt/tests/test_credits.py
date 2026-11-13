from __future__ import annotations

from ai_svc.spy_hunt.db import get_conn


def test_credit_tables_exist(temp_db):
    cols = {r[1] for r in get_conn().execute("PRAGMA table_info(player_credits)")}
    assert cols == {"key", "player_id", "credits", "created_day", "created_at"}
    tcols = {r[1] for r in get_conn().execute("PRAGMA table_info(player_total_credits)")}
    assert tcols == {"player_id", "credits", "updated_at"}
