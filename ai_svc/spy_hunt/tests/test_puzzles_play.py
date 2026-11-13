from __future__ import annotations

import json
import threading

import pytest

from ai_svc.spy_hunt import credits, puzzles
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.store import StoreError
from ai_svc.spy_hunt.tests.puzzle_fixtures import sample_puzzle

DAY = "2026-11-10"


@pytest.fixture
def clock(monkeypatch):
    box = {"t": 1_000_000}
    monkeypatch.setattr(puzzles, "_now_ms", lambda: box["t"])
    return box


def add(n=1, spy_seat=2):
    for i in range(n):
        public, answer = sample_puzzle(spy_seat)
        puzzles.insert_ready(public, answer, 2, f"p-{i}")


def code_of(exc_info):
    return exc_info.value.code


@pytest.mark.parametrize("args,expected", [
    ((1, 0, True), 140), ((1, 60000, False), 120), ((1, 180000, False), 100),
    ((1, 120000, False), 110), ((2, 60000, True), 100), ((None, 1000, True), 0),
])
def test_score_table(args, expected):
    assert puzzles.score(*args) == expected


def test_get_today_creates_attempt_and_hides_answer(temp_db, clock):
    add()
    out = puzzles.get_today("g1", DAY)
    assert out["me"] == {"stage": "spy", "tries": 0, "tries_left": 2, "wrong": []}
    assert "spy_seat" not in json.dumps(out)
    clock["t"] += 50_000
    puzzles.get_today("g1", DAY)
    from ai_svc.spy_hunt.db import get_conn
    # opening the puzzle must not start the clock: it stays unset until the first guess
    row = get_conn().execute("SELECT started_at FROM puzzle_results WHERE player_id='g1'").fetchone()
    assert row["started_at"] is None


def test_clock_starts_on_first_guess_not_on_open(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    clock["t"] += 600_000  # peeked, then wandered off for ten minutes
    puzzles.guess_spy("g1", 0, DAY)  # first guess starts the clock
    clock["t"] += 30_000
    puzzles.guess_spy("g1", 2, DAY)
    puzzles.guess_word("g1", None, DAY)
    r = puzzles.result("g1", DAY)
    assert r["elapsed_ms"] == 30_000


def test_get_today_no_puzzle_is_503(temp_db, clock):
    with pytest.raises(StoreError) as e:
        puzzles.get_today("g1", DAY)
    assert e.value.status == 503 and e.value.code == "no_puzzle"


def test_correct_first_guess_moves_to_word_stage(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    out = puzzles.guess_spy("g1", 2, DAY)
    assert out == {"correct": True, "stage": "word", "tries": 1, "tries_left": 1}
    assert "organ" not in json.dumps(out)


def test_wrong_then_wrong_ends_unsolved(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    assert puzzles.guess_spy("g1", 0, DAY) == {"correct": False, "stage": "spy", "tries": 1, "tries_left": 1}
    last = puzzles.guess_spy("g1", 1, DAY)
    assert last["stage"] == "done" and last["correct"] is False
    r = puzzles.result("g1", DAY)
    assert r["solved"] is False and r["score"] == 0 and r["tries"] == 2
    assert r["answer"]["spy_seat"] == 2 and r["answer"]["spy_word"]["en"] == "organ"


def test_wrong_then_correct_scores_try_two(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    clock["t"] += 60_000
    puzzles.guess_spy("g1", 0, DAY)
    puzzles.guess_spy("g1", 2, DAY)
    assert puzzles.guess_word("g1", None, DAY) == {"correct": None, "stage": "done"}
    r = puzzles.result("g1", DAY)
    assert r["score"] == 80 and r["word_correct"] is None and r["solved"] is True


def test_word_guess_correct_adds_20(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 2, DAY)
    assert puzzles.guess_word("g1", 0, DAY)["correct"] is True
    assert puzzles.result("g1", DAY)["score"] == 140


def test_word_guess_wrong_adds_nothing(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 2, DAY)
    assert puzzles.guess_word("g1", 3, DAY)["correct"] is False
    r = puzzles.result("g1", DAY)
    assert r["score"] == 120 and r["word_correct"] is False


def test_elapsed_is_server_measured(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 2, DAY)  # first guess starts the server clock
    clock["t"] += 90_000
    puzzles.guess_word("g1", None, DAY)
    r = puzzles.result("g1", DAY)
    assert r["elapsed_ms"] == 90_000 and r["score"] == 100 + 15


def test_cannot_guess_after_done(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 2, DAY)
    puzzles.guess_word("g1", None, DAY)
    with pytest.raises(StoreError) as e:
        puzzles.guess_spy("g1", 2, DAY)
    assert e.value.status == 409 and e.value.code == "wrong_stage"


def test_cannot_guess_word_in_spy_stage(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    with pytest.raises(StoreError) as e:
        puzzles.guess_word("g1", 0, DAY)
    assert e.value.status == 409 and e.value.code == "wrong_stage"


def test_guess_without_attempt_is_404(temp_db, clock):
    add()
    with pytest.raises(StoreError) as e:
        puzzles.guess_spy("nobody", 2, DAY)
    assert e.value.status == 404 and e.value.code == "no_attempt"


@pytest.mark.parametrize("bad", [True, "2", 5, -1, None, 1.0])
def test_bad_seat_rejected(temp_db, clock, bad):
    add()
    puzzles.get_today("g1", DAY)
    with pytest.raises(StoreError) as e:
        puzzles.guess_spy("g1", bad, DAY)
    assert e.value.status == 400 and e.value.code == "bad_seat"


@pytest.mark.parametrize("bad", [True, "1", 4, -1, 1.0])
def test_bad_option_rejected(temp_db, clock, bad):
    add()
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 2, DAY)
    with pytest.raises(StoreError) as e:
        puzzles.guess_word("g1", bad, DAY)
    assert e.value.status == 400 and e.value.code == "bad_option"


def test_result_before_done_is_409(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    with pytest.raises(StoreError) as e:
        puzzles.result("g1", DAY)
    assert e.value.status == 409 and e.value.code == "not_finished"


def test_two_parallel_guesses_use_at_most_two_tries(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    outcomes = []

    def go(seat):
        try:
            outcomes.append(puzzles.guess_spy("g1", seat, DAY))
        except StoreError as e:
            outcomes.append(e.code)

    threads = [threading.Thread(target=go, args=(s,)) for s in (0, 1, 3, 4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    from ai_svc.spy_hunt.db import get_conn
    row = get_conn().execute("SELECT tries, stage FROM puzzle_results WHERE player_id='g1'").fetchone()
    assert row["tries"] == 2 and row["stage"] == "done"
    assert outcomes.count("wrong_stage") == 2


def test_stats_count_finished_attempts_only(temp_db, clock):
    add()
    for pid, seat in (("a", 2), ("b", 0)):
        puzzles.get_today(pid, DAY)
        if seat == 2:
            puzzles.guess_spy(pid, 2, DAY)
            puzzles.guess_word(pid, None, DAY)
        else:
            puzzles.guess_spy(pid, 0, DAY)
            puzzles.guess_spy(pid, 1, DAY)
    puzzles.get_today("c", DAY)
    r = puzzles.result("a", DAY)
    assert r["stats"] == {"players": 2, "solved_pct": 50}


def test_yesterdays_attempt_does_not_affect_today(temp_db, clock):
    add(2)
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 2, DAY)
    puzzles.guess_word("g1", None, DAY)
    out = puzzles.get_today("g1", "2026-11-11")
    assert out["me"] == {"stage": "spy", "tries": 0, "tries_left": 2, "wrong": []}
    assert out["puzzle"]["number"] == 2


def test_wrong_seats_survive_a_reload(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 0, DAY)
    me = puzzles.get_today("g1", DAY)["me"]
    assert me == {"stage": "spy", "tries": 1, "tries_left": 1, "wrong": [0]}


def test_repeating_a_wrong_seat_is_rejected_and_costs_no_try(temp_db, clock):
    add()
    puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 0, DAY)
    with pytest.raises(StoreError) as e:
        puzzles.guess_spy("g1", 0, DAY)
    assert e.value.status == 409 and e.value.code == "already_tried"
    assert puzzles.get_today("g1", DAY)["me"]["tries"] == 1


def test_check_day_accepts_today_and_yesterday_only(temp_db, clock):
    assert puzzles.check_day(None) == puzzles.utc_day()
    assert puzzles.check_day("1970-01-01") == "1970-01-01"
    assert puzzles.check_day("1969-12-31") == "1969-12-31"
    for bad in ("1970-01-02", "1969-12-30", "garbage", 5, "1970-1-1"):
        with pytest.raises(StoreError) as e:
            puzzles.check_day(bad)
        assert e.value.status == 400 and e.value.code == "bad_day"


def test_daily_solved_awards_credits_and_reports_them(temp_db, clock):
    add(); puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 2, DAY)            # found
    puzzles.guess_word("g1", 0, DAY)           # word right
    r = puzzles.result("g1", DAY)
    assert r["credits_earned"] >= 20           # base+solved (+streak bonus)
    assert r["credits_earned"] == credits.total(get_conn(), "g1")
    assert [p["kind"] for p in r["credit_parts"]][:2] == ["daily", "found"]
    assert sum(p["n"] for p in r["credit_parts"]) == r["credits_earned"]


def test_daily_missed_awards_base_only(temp_db, clock):
    add(); puzzles.get_today("g1", DAY)
    puzzles.guess_spy("g1", 0, DAY); puzzles.guess_spy("g1", 1, DAY)   # two wrong -> done
    r = puzzles.result("g1", DAY)
    assert r["credits_earned"] == 10
    assert r["credit_parts"] == [{"kind": "daily", "n": 10}]
