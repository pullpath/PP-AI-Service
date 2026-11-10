"""Nightly arena run. Uses the real database (db.DB_PATH) and the real model.

    python -m ai_svc.spy_hunt.scripts.arena_night --matches 20
    python -m ai_svc.spy_hunt.scripts.arena_night --dry-run
"""
from __future__ import annotations

import argparse
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, help="most matches to play tonight")
    ap.add_argument("--dry-run", action="store_true", help="print the groups, play nothing")
    args = ap.parse_args(argv)

    from ai_svc.spy_hunt import arena, db
    db.init_db()
    res = arena.run_night(args.matches if args.matches is not None else arena.ARENA_MATCHES_PER_DAY,
                          dry_run=args.dry_run)
    print(f"played {res['played']}, discarded {res['discarded']}, skipped {res['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
