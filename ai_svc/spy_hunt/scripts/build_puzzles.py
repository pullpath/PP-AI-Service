"""Daily puzzle queue tool. Uses the real database (db.DB_PATH) and, for --count,
the real model, so it spends model calls (about 13 per puzzle).

    python -m ai_svc.spy_hunt.scripts.build_puzzles --count 14   # fill the queue
    python -m ai_svc.spy_hunt.scripts.build_puzzles --review     # read ready puzzles
    python -m ai_svc.spy_hunt.scripts.build_puzzles --veto 7     # drop one from the queue
"""
from __future__ import annotations

import argparse
import json
from typing import List, Optional


def _review() -> None:
    from ai_svc.spy_hunt import db, puzzles
    rows = db.get_conn().execute(
        "SELECT * FROM puzzles WHERE status='ready' ORDER BY id").fetchall()
    if not rows:
        print("no ready puzzles")
    for r in rows:
        pub, ans = json.loads(r["public_json"]), json.loads(r["answer_json"])
        names = {p["seat"]: p["name"] for p in pub["players"]}
        cw, sw = pub["civilian_word"], ans["spy_word"]
        print(f"#{r['id']} difficulty {r['difficulty']} origin {pub['origin_lang']}"
              f" civilian: {cw['en']} / {cw['zh-Hans']}")
        print(f"    spy: seat {ans['spy_seat']} ({names[ans['spy_seat']]}),"
              f" word {sw['en']} / {sw['zh-Hans']}")
        for m in pub["statements"]:
            print(f"    r{m['round']} {names[m['seat']]}: {m['text']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, help="fill the ready queue up to N puzzles")
    ap.add_argument("--review", action="store_true", help="print ready puzzles with the answer")
    ap.add_argument("--veto", type=int, metavar="ID", help="remove a ready puzzle from the queue")
    args = ap.parse_args(argv)

    from ai_svc.spy_hunt import db, puzzle_gen, puzzles
    db.init_db()
    if args.review:
        _review()
        return 0
    if args.veto is not None:
        if puzzles.veto(args.veto):
            print(f"puzzle {args.veto} vetoed")
            return 0
        print(f"puzzle {args.veto} is not a ready puzzle")
        return 1
    before = puzzles.ready_count()
    puzzle_gen.fill_queue(args.count if args.count is not None else puzzle_gen.QUEUE_TARGET)
    print(f"added {puzzles.ready_count() - before}, {puzzles.ready_count()} ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
