from __future__ import annotations

import random

from ai_svc.spy_hunt import puzzles
from ai_svc.spy_hunt.scripts import build_puzzles
from ai_svc.spy_hunt.tests.puzzle_fixtures import sample_puzzle
from ai_svc.spy_hunt.tests.test_puzzle_gen import register_world


def seed(n=2):
    return [puzzles.insert_ready(*sample_puzzle(), 2, f"p-{i}") for i in range(n)]


def test_review_lists_ready_puzzles_with_statements(temp_db, capsys):
    a, _ = seed()
    assert build_puzzles.main(["--review"]) == 0
    out = capsys.readouterr().out
    assert f"#{a}" in out and "piano / 钢琴" in out and "Milo" in out and "It has keys." in out
    assert "spy: seat 2 (Pip)" in out and "organ / 风琴" in out


def test_veto_removes_from_queue_and_reports(temp_db, capsys):
    a, b = seed()
    assert build_puzzles.main(["--veto", str(a)]) == 0
    assert "vetoed" in capsys.readouterr().out
    assert [r["id"] for r in puzzles.list_ready()] == [b]


def test_veto_unknown_id_exits_1(temp_db, capsys):
    assert build_puzzles.main(["--veto", "999"]) == 1
    assert "not" in capsys.readouterr().out


def test_count_fills_queue_with_fake_llm(temp_db, capsys):
    register_world()
    assert build_puzzles.main(["--count", "1"]) == 0
    assert puzzles.ready_count() == 1
    assert "added 1" in capsys.readouterr().out
