from __future__ import annotations

import random

from ai_svc.spy_hunt import engine as e


def seats(roles, dead=()):
    return [{"seat": i, "role": r, "alive": i not in dead} for i, r in enumerate(roles)]


C, S = "civilian", "spy"


def test_one_spy_three_alive_spies_win():
    # 1 spy vs 1 civilian (spies >= civilians) -> spies win
    assert e.check_win(seats([S, C, C, C], dead={2, 3}), 1, 5) == "spies"
    # 1 spy vs 2 civilians (3 alive) -> game continues under the binding rule
    assert e.check_win(seats([S, C, C, C], dead={3}), 1, 5) is None


def test_spy_caught_civilians_win():
    assert e.check_win(seats([S, C, C, C], dead={0, 1}), 2, 5) == "civilians"


def test_two_spies_eight_players_continues():
    roles = [S, S, C, C, C, C, C, C]
    assert e.check_win(seats(roles, dead={0}), 1, 5) is None


def test_final_round_catch_goes_to_civilians():
    assert e.check_win(seats([S, C, C, C], dead={0}), 5, 5) == "civilians"


def test_max_rounds_with_spy_in_spies_win():
    assert e.check_win(seats([S, C, C, C, C]), 5, 5) == "spies"


def test_no_win_midgame():
    assert e.check_win(seats([S, C, C, C, C]), 1, 5) is None


def test_tie_stage0_tiebreak():
    r = e.resolve_vote({0: 1, 1: 0, 2: 1, 3: 0}, 0, [0, 1, 2, 3], None)
    assert r.outcome == "tiebreak" and sorted(r.tied) == [0, 1] and r.eliminated is None


def test_tie_stage1_nobody():
    r = e.resolve_vote({2: 0, 3: 1}, 1, [0, 1, 2, 3], [0, 1])
    assert r.outcome == "nobody" and r.eliminated is None


def test_all_tied_nobody():
    r = e.resolve_vote({0: 1, 1: 2, 2: 0}, 0, [0, 1, 2], None)
    assert r.outcome == "nobody" and r.tied == []


def test_zero_votes_nobody():
    r = e.resolve_vote({0: None, 1: None, 2: None}, 0, [0, 1, 2], None)
    assert r.outcome == "nobody"
    assert e.resolve_vote({}, 0, [0, 1], None).outcome == "nobody"


def test_abstains_ignored():
    r = e.resolve_vote({0: 2, 1: None, 3: 2, 2: 0}, 0, [0, 1, 2, 3], None)
    assert r.outcome == "eliminated" and r.eliminated == 2


def test_plurality_elimination():
    r = e.resolve_vote({0: 1, 1: 2, 2: 1, 3: 1}, 0, [0, 1, 2, 3], None)
    assert (r.outcome, r.eliminated) == ("eliminated", 1)


def test_revote_eligibility():
    assert e.eligible_voters([0, 1, 2, 3], 1, [0, 1]) == [2, 3]
    assert e.eligible_targets([0, 1, 2, 3], 1, [0, 1]) == [0, 1]


def test_stage0_eligibility_all_alive():
    assert e.eligible_voters([0, 1, 2], 0, None) == [0, 1, 2]
    assert e.eligible_targets([0, 1, 2], 0, None) == [0, 1, 2]


def test_contains_own_word():
    w = {"en": "coffee", "zh-Hans": "咖啡"}
    assert e.contains_own_word("I like 咖啡?", w)
    assert e.contains_own_word("I drink Coffee", w)
    assert not e.contains_own_word("I drink tea", w)


def test_other_pair_word_not_checked():
    assert not e.contains_own_word("I like tea", {"en": "coffee"})


def test_empty_word_safe():
    assert not e.contains_own_word("anything", {"en": "", "zh-Hans": "   "})
    assert not e.contains_own_word("anything", {})


def test_assign_roles_exact_and_unbiased():
    rng = random.Random(42)
    n, k, draws = 6, 2, 2000
    counts = [0] * n
    for _ in range(draws):
        roles = e.assign_roles(n, k, rng)
        assert len(roles) == n and roles.count("spy") == k
        assert set(roles) <= {"spy", "civilian"}
        for i, r in enumerate(roles):
            counts[i] += r == "spy"
    for c in counts:
        assert abs(c / draws - k / n) < 0.05


def test_next_speaker_basic_and_skips_dead_and_spoken():
    order = [3, 1, 0, 2]
    assert e.next_speaker(order, {0, 1, 2, 3}, set(), None) == 3
    assert e.next_speaker(order, {0, 1, 2}, set(), None) == 1
    assert e.next_speaker(order, {0, 1, 2}, {1}, None) == 0
    assert e.next_speaker(order, {0, 1, 2}, {1, 0, 2}, None) is None


def test_next_speaker_tiebreak_restricted():
    order = [3, 1, 0, 2]
    assert e.next_speaker(order, {0, 1, 2, 3}, set(), [0, 2]) == 0
    assert e.next_speaker(order, {0, 1, 2, 3}, {0}, [0, 2]) == 2
    assert e.next_speaker(order, {0, 1, 2, 3}, {0, 2}, [0, 2]) is None
