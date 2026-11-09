"""Offline word-pool builder (impl spec §9). Run once with a real key:

    python -m ai_svc.spy_hunt.scripts.build_pool --target 120
    python -m ai_svc.spy_hunt.scripts.build_pool --extend --target 120   # keep the shipped pairs

Runs generate-and-validate over a theme list in a throwaway database until at
least --target pairs pass, then writes seed/pairs_candidate.json. The shipped
seed/pairs_seed.json is NOT touched: the owner reviews the candidate file and
copies it over pairs_seed.json to load it."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from typing import List, Optional

THEMES = (
    "food", "drinks", "fruit", "vegetables", "animals", "pets", "birds", "sea creatures",
    "clothing", "shoes", "kitchen tools", "furniture", "household items", "stationery",
    "school", "sports", "outdoor games", "music instruments", "transport", "vehicles",
    "weather", "nature", "plants", "places in a city", "buildings", "jobs", "tools",
    "electronics", "toys", "festivals", "hobbies", "body care", "snacks", "desserts",
)
CALLS_PER_PAIR = 2
MAX_CALL_BUDGET = 450


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=120)
    ap.add_argument("--extend", action="store_true",
                    help="start from the shipped seed; --target is the total pool size and only "
                         "the new pairs are written")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "seed", "pairs_candidate.json"))
    args = ap.parse_args(argv)

    from ai_svc.spy_hunt import db, store, words
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "build_pool.db")
    db.close_conn()
    db.init_db()
    conn = db.get_conn()
    if not args.extend:
        conn.execute("DELETE FROM pairs")
        conn.commit()
    baseline = {r["id"] for r in conn.execute("SELECT id FROM pairs")}
    room = store.create_room("builder", "builder", "en")
    rid = room["id"]

    calls, i = 0, 0
    while calls < MAX_CALL_BUDGET:
        have = conn.execute("SELECT COUNT(*) c FROM pairs").fetchone()["c"]
        if have >= args.target:
            break
        conn.execute("UPDATE rooms SET ai_calls=0 WHERE id=?", (rid,))
        conn.commit()
        theme = THEMES[i % len(THEMES)]
        i += 1
        pair = words.generate_pair(rid, theme)
        calls += CALLS_PER_PAIR
        print(f"[{have}/{args.target}] {theme}: {pair.words['en'] if pair else 'rejected'}")

    rows = [r for r in conn.execute("SELECT * FROM pairs ORDER BY id") if r["id"] not in baseline]
    out = [{"id": r["id"], "difficulty": r["difficulty"], "theme": r["theme"],
            "words": json.loads(r["words_json"])} for r in rows]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {len(out)} pairs to {args.out} (review before use)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
