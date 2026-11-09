from __future__ import annotations

import json

from ai_svc.spy_hunt import db, fake_llm
from ai_svc.spy_hunt.scripts import build_pool


def register_fresh_pairs():
    n = {"i": 0}

    def gen(prompt):
        n["i"] += 1
        i = n["i"]
        return {"en": {"a": f"alpha{i}", "b": f"beta{i}"}, "zh_hans": {"a": f"甲{i}", "b": f"乙{i}"},
                "difficulty": 2, "theme": "t"}

    fake_llm.register("pair_generate", gen)
    fake_llm.register("pair_validate", lambda p: {"en": {"ok": True}, "zh_hans": {"ok": True}})


def seed_ids():
    return {p["id"] for p in json.load(open(db.SEED_PATH, encoding="utf-8"))}


def test_extend_starts_from_the_seed_and_writes_only_new_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", db.DB_PATH)  # build_pool swaps it; restore afterwards
    register_fresh_pairs()
    out = tmp_path / "c.json"
    size = len(seed_ids())
    assert build_pool.main(["--extend", "--target", str(size + 2), "--out", str(out)]) == 0
    new = json.load(open(out, encoding="utf-8"))
    assert len(new) == 2
    assert not ({p["id"] for p in new} & seed_ids())


def test_without_extend_the_pool_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", db.DB_PATH)
    register_fresh_pairs()
    out = tmp_path / "c.json"
    assert build_pool.main(["--target", "2", "--out", str(out)]) == 0
    assert len(json.load(open(out, encoding="utf-8"))) == 2
