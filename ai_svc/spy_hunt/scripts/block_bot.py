"""Block or unblock a custom bot on the real database (db.DB_PATH).

    python -m ai_svc.spy_hunt.scripts.block_bot <id>             # remove from the board, no new remixes
    python -m ai_svc.spy_hunt.scripts.block_bot <id> --unblock
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bot_id")
    ap.add_argument("--unblock", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    # ids are secrets.token_urlsafe(6), so some start with "-": argparse would read that as a flag.
    # Anything that isn't our own flag is the id; "--" tells argparse so.
    flags = [a for a in argv if a == "--unblock"]
    rest = [a for a in argv if a != "--unblock"]
    args = ap.parse_args(flags + ["--"] + rest)

    from ai_svc.spy_hunt import db
    db.init_db()
    conn = db.get_conn()
    blocked = 0 if args.unblock else 1
    cur = conn.execute("UPDATE custom_bots SET blocked=? WHERE id=?", (blocked, args.bot_id))
    conn.commit()
    if cur.rowcount == 0:
        print(f"no bot {args.bot_id}")
        return 1
    print(f"bot {args.bot_id} {'unblocked' if args.unblock else 'blocked'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
