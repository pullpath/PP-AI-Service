from __future__ import annotations

from ai_svc.spy_hunt import db
from ai_svc.spy_hunt.scripts import block_bot

from .test_custom_bots import mk
from .test_rooms import guest


def _blocked(bid):
    return db.get_conn().execute("SELECT blocked FROM custom_bots WHERE id=?", (bid,)).fetchone()[0]


def test_block_bot_script(client, capsys):
    h, _ = guest(client)
    bid = mk(client, h).get_json()["id"]
    assert block_bot.main([bid]) == 0
    assert _blocked(bid) == 1
    assert block_bot.main([bid, "--unblock"]) == 0
    assert _blocked(bid) == 0
    assert block_bot.main(["nope"]) == 1
