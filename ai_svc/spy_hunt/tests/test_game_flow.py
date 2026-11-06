from __future__ import annotations

import json

import pytest

from ai_svc.spy_hunt import game, store, visibility
from ai_svc.spy_hunt.config import BOT_NAMES, BOT_PERSONA_KEYS, GameConfig
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.store import StoreError

API = "/api/spy-hunt"
WORDS = {"en": {"a": "lighthouse", "b": "windmill"}, "zh-Hans": {"a": "灯塔", "b": "风车"}}
ALL_SECRETS = {"lighthouse", "windmill", "灯塔", "风车"}


@pytest.fixture(autouse=True)
def _game_env(temp_db):
    game.set_pair_source(lambda room_id: game.Pair("t-pair", WORDS))
    calls = []
    game.set_on_phase_change(lambda *a: calls.append(a))
    yield calls
    game.set_pair_source(None)
    game.set_on_phase_change(None)


# ---- helpers ----

def lobby(n=3, langs=None):
    """A lobby with n humans pid0..pid{n-1}; returns room id."""
    langs = langs or ["en", "zh-Hans"]
    room = store.create_room("pid0", "P0", langs[0])
    for i in range(1, n):
        store.add_player(room["id"], f"pid{i}", f"P{i}", langs[i % len(langs)])
    return room["id"]


def room(rid):
    return store.get_room(rid)


def seats(rid):
    """{seat: row dict} straight from the DB (test-only, may read role)."""
    return {r["seat"]: dict(r) for r in get_conn().execute(
        "SELECT * FROM players WHERE room_id=? ORDER BY seat", (rid,))}


def pid(rid, seat):
    return seats(rid)[seat]["player_id"]


def spy_seats(rid):
    return [s for s, r in seats(rid).items() if r["role"] == "spy"]


def civ_seats(rid):
    return [s for s, r in seats(rid).items() if r["role"] == "civilian"]


def alive(rid):
    return [s for s, r in seats(rid).items() if r["alive"]]


def speaker(rid):
    return visibility.build_snapshot(rid, pid(rid, 0))["current_speaker"]


def say_all(rid, text="it is tall and near the sea"):
    """Every remaining speaker of the current describe phase speaks."""
    phase = room(rid)["phase"]
    spoken = []
    while room(rid)["phase"] == phase:
        s = speaker(rid)
        assert s is not None
        game.submit_statement(rid, pid(rid, s), f"{text} {s}")
        spoken.append(s)
    return spoken


def vote(rid, mapping):
    for voter, target in mapping.items():
        game.submit_vote(rid, pid(rid, voter), target)


def start(rid, by="pid0"):
    game.start_game(rid, by)
    return room(rid)


def events(rid, after=0):
    return [dict(r) | {"payload": json.loads(r["payload_json"])} for r in get_conn().execute(
        "SELECT * FROM events WHERE room_id=? AND seq>? ORDER BY seq", (rid, after))]


def last_seq(rid):
    return get_conn().execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE room_id=?",
                              (rid,)).fetchone()[0]


def word_of(rid, seat, lang=None):
    r = room(rid)
    row = seats(rid)[seat]
    civ, spy = ("a", "b") if r["civ_is_a"] else ("b", "a")
    return WORDS[lang or row["lang"]][spy if row["role"] == "spy" else civ]


def other_civ(rid, *exclude):
    return next(s for s in civ_seats(rid) if s not in exclude and s in alive(rid))


# ---- start ----

def test_start_with_three_humans_adds_one_bot(_game_env):
    rid = lobby(3)
    r = start(rid)
    st = seats(rid)
    assert sorted(st) == [0, 1, 2, 3]
    bots = [x for x in st.values() if x["is_bot"]]
    assert len(bots) == 1
    assert bots[0]["bot_persona"] in BOT_PERSONA_KEYS
    assert bots[0]["name"] in BOT_NAMES
    assert len(spy_seats(rid)) == 1 and len(civ_seats(rid)) == 3
    assert all(x["alive"] == 1 for x in st.values())
    assert r["status"] == "playing" and r["phase"] == "describe" and r["round"] == 1
    assert r["pair_id"] == "t-pair" and r["civ_is_a"] in (0, 1)
    cfg = json.loads(r["config_json"])
    assert cfg["spy_count"] == 1 and cfg["max_rounds"] == GameConfig().max_rounds(4, 1) == 4
    assert cfg["players"] == 4
    assert r["phase_seq"] >= 1 and r["phase_deadline"] > store.now_ms()
    # the timer hook got the new phase_seq and deadline
    assert _game_env[-1] == (rid, r["phase_seq"], r["phase_deadline"])
    # pair is readable by the firewall (snapshot my_word)
    for s in st:
        snap = visibility.build_snapshot(rid, pid(rid, s))
        assert snap["me"]["my_word"] == word_of(rid, s)


def test_start_game_started_is_personal_and_has_no_role():
    rid = lobby(4)
    before = last_seq(rid)
    start(rid)
    evs = events(rid, before)
    gs = [e for e in evs if e["type"] == "game_started"]
    assert sorted(e["audience"] for e in gs) == [f"seat:{s}" for s in range(4)]
    for e in gs:
        s = int(e["audience"].split(":")[1])
        assert e["payload"]["my_word"] == word_of(rid, s)
        assert e["payload"]["seat"] == s
        text = json.dumps(e["payload"], ensure_ascii=False)
        assert "role" not in text and '"spy"' not in text and '"civilian"' not in text
        assert not (ALL_SECRETS - {word_of(rid, s)}) & {w for w in ALL_SECRETS if w in text}
    turns = [e for e in evs if e["type"] == "turn"]
    assert turns and turns[-1]["audience"] == "all"
    assert turns[-1]["payload"]["seat"] == 0 and turns[-1]["payload"]["phase"] == "describe"


def test_start_eight_seats_two_spies():
    rid = lobby(5)
    for _ in range(3):
        game.add_bot(rid, "pid0")
    r = start(rid)
    assert len(seats(rid)) == 8
    assert len(spy_seats(rid)) == 2
    cfg = json.loads(r["config_json"])
    assert cfg["spy_count"] == 2 and cfg["max_rounds"] == 6


def test_start_compacts_and_shuffles_seats():
    rid = lobby(5)
    game.leave(rid, "pid2")  # frees seat 2 in the lobby; not compacted yet
    assert sorted(seats(rid)) == [0, 1, 3, 4]
    start(rid)
    st = seats(rid)
    assert sorted(st) == [0, 1, 2, 3]
    assert {x["player_id"] for x in st.values()} == {"pid0", "pid1", "pid3", "pid4"}


def test_start_non_host_and_wrong_status():
    rid = lobby(3)
    with pytest.raises(StoreError) as e:
        game.start_game(rid, "pid1")
    assert e.value.status == 403
    start(rid)
    with pytest.raises(StoreError) as e:
        game.start_game(rid, "pid0")
    assert e.value.status == 409


def test_start_without_bot_fill_needs_min_players():
    rid = lobby(3)
    store.update_settings(rid, "pid0", bot_fill=False)
    with pytest.raises(StoreError) as e:
        game.start_game(rid, "pid0")
    assert e.value.status == 409
    game.add_bot(rid, "pid0")  # host may still add a bot by hand
    start(rid)
    assert len(seats(rid)) == 4


def test_bot_names_unique_and_add_remove():
    rid = lobby(1)
    for _ in range(9):
        game.add_bot(rid, "pid0")
    names = [x["name"] for x in seats(rid).values()]
    assert len(set(names)) == 10
    with pytest.raises(StoreError) as e:
        game.add_bot(rid, "pid0")
    assert e.value.status == 409 and e.value.code == "room_full"
    with pytest.raises(StoreError) as e:
        game.add_bot(rid, "pidX")
    assert e.value.status == 403
    game.remove_bot(rid, "pid0")
    assert len(seats(rid)) == 9
    assert not seats(rid)[0]["is_bot"]


# ---- statements ----

def test_statement_out_of_turn_409():
    rid = lobby(4)
    start(rid)
    assert speaker(rid) == 0
    with pytest.raises(StoreError) as e:
        game.submit_statement(rid, pid(rid, 1), "hello")
    assert e.value.status == 409


def test_own_word_statement_400_turn_not_consumed():
    rid = lobby(4)
    start(rid)
    s = speaker(rid)
    p = pid(rid, s)
    seq = room(rid)["phase_seq"]
    for lang in ("en", "zh-Hans"):  # own word in ANY language is refused
        with pytest.raises(StoreError) as e:
            game.submit_statement(rid, p, f"I think of {word_of(rid, s, lang).upper()}!")
        assert e.value.status == 400 and e.value.code == "own_word"
        # never reveals the other pair word
        for w in ALL_SECRETS:
            assert w not in e.value.message
    with pytest.raises(StoreError) as e:
        game.submit_statement(rid, p, "x" * (GameConfig().statement_max_chars + 1))
    assert e.value.status == 400
    for bad in ("", "   ", "​​"):
        with pytest.raises(StoreError) as e:
            game.submit_statement(rid, p, bad)
        assert e.value.status == 400
    assert speaker(rid) == s and room(rid)["phase_seq"] == seq
    n = get_conn().execute("SELECT COUNT(*) FROM messages WHERE room_id=?", (rid,)).fetchone()[0]
    assert n == 0
    game.submit_statement(rid, p, "x" * GameConfig().statement_max_chars)
    assert speaker(rid) != s and room(rid)["phase_seq"] == seq + 1


def test_zero_width_cannot_smuggle_own_word():
    rid = lobby(4)
    start(rid)
    s = speaker(rid)
    w = word_of(rid, s, "en")
    with pytest.raises(StoreError) as e:
        game.submit_statement(rid, pid(rid, s), w[:2] + "​" + w[2:])
    assert e.value.code == "own_word"


def test_statement_event_and_speaker_advance(_game_env):
    rid = lobby(4)
    start(rid)
    before = last_seq(rid)
    game.submit_statement(rid, pid(rid, 0), "tall and white")
    evs = events(rid, before)
    assert [e["type"] for e in evs] == ["statement", "turn"]
    msg = evs[0]["payload"]["message"]
    assert msg["seat"] == 0 and msg["text"] == "tall and white" and msg["kind"] == "statement"
    assert msg["stage"] == 0 and msg["round"] == 1
    assert evs[1]["payload"]["seat"] == 1
    r = room(rid)
    assert _game_env[-1] == (rid, r["phase_seq"], r["phase_deadline"])


def test_describe_timeout_records_skipped_and_is_idempotent():
    rid = lobby(4)
    start(rid)
    seq = room(rid)["phase_seq"]
    assert game.advance_phase(rid, seq - 1) is False  # stale
    assert game.advance_phase(rid, seq) is True
    assert game.advance_phase(rid, seq) is False  # same entry fired twice acts once
    m = get_conn().execute("SELECT * FROM messages WHERE room_id=?", (rid,)).fetchall()
    assert len(m) == 1 and m[0]["kind"] == "skipped" and m[0]["text"] is None and m[0]["seat"] == 0
    assert speaker(rid) == 1


def test_join_and_lang_change_do_not_bump_phase_seq():
    rid = lobby(4)
    start(rid)
    seq = room(rid)["phase_seq"]
    store.update_me(rid, "pid1", lang="zh-Hans")
    store.add_player(rid, "pid1", "x", "en")  # idempotent rejoin
    assert room(rid)["phase_seq"] == seq


def test_describe_ends_into_vote():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    r = room(rid)
    assert r["phase"] == "vote"
    assert r["phase_deadline"] > store.now_ms()


# ---- votes ----

def test_vote_validation():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    with pytest.raises(StoreError) as e:
        game.submit_vote(rid, pid(rid, 0), 0)
    assert e.value.status == 400  # self
    for bad in (9, -1, True, "1", 1.5):
        with pytest.raises(StoreError) as e:
            game.submit_vote(rid, pid(rid, 0), bad)
        assert e.value.status == 400
    with pytest.raises(StoreError) as e:
        game.submit_vote(rid, "stranger", 1)
    assert e.value.status == 403
    game.submit_vote(rid, pid(rid, 0), 1)
    with pytest.raises(StoreError) as e:
        game.submit_vote(rid, pid(rid, 0), 2)  # never silently overwrite
    assert e.value.status == 409
    row = get_conn().execute("SELECT target_seat FROM votes WHERE room_id=? AND voter_seat=0",
                             (rid,)).fetchone()
    assert row["target_seat"] == 1


def test_vote_in_describe_is_409():
    rid = lobby(4)
    start(rid)
    with pytest.raises(StoreError) as e:
        game.submit_vote(rid, pid(rid, 1), 2)
    assert e.value.status == 409


def test_vote_locked_event_hides_target():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    before = last_seq(rid)
    game.submit_vote(rid, pid(rid, 0), 1)
    evs = events(rid, before)
    assert [e["type"] for e in evs] == ["vote_locked"]
    assert evs[0]["payload"] == {"seat": 0, "round": 1, "stage": 0}


def test_abstain_only_round_advances():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    vote(rid, {s: None for s in range(4)})
    r = room(rid)
    assert r["phase"] == "reveal" and r["round"] == 1
    rev = [e for e in events(rid) if e["type"] == "reveal"][-1]["payload"]
    assert rev["eliminated"] is None and "role" not in rev
    assert alive(rid) == [0, 1, 2, 3]
    game.advance_phase(rid, r["phase_seq"])
    r = room(rid)
    assert r["phase"] == "describe" and r["round"] == 2 and speaker(rid) == 0


def test_vote_timeout_resolves_with_votes_in():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    victim = civ_seats(rid)[0]
    voters = [s for s in range(4) if s != victim][:2]
    vote(rid, {v: victim for v in voters})
    game.advance_phase(rid, room(rid)["phase_seq"])
    assert victim not in alive(rid)
    rev = [e for e in events(rid) if e["type"] == "reveal"][-1]
    assert rev["audience"] == "all"
    assert rev["payload"]["eliminated"] == victim and rev["payload"]["role"] == "civilian"


def test_all_tied_round_nobody_out():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    vote(rid, {0: 1, 1: 2, 2: 3, 3: 0})
    r = room(rid)
    assert r["phase"] == "reveal"
    assert alive(rid) == [0, 1, 2, 3]
    rev = [e for e in events(rid) if e["type"] == "reveal"][-1]["payload"]
    assert rev["eliminated"] is None and rev["outcome"] == "nobody"
    assert sorted((v["voter"], v["target"]) for v in rev["votes"]) == [(0, 1), (1, 2), (2, 3), (3, 0)]


def test_tiebreak_then_revote_with_tied_excluded():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    vote(rid, {0: 1, 1: 0, 2: 1, 3: 0})
    r = room(rid)
    assert r["phase"] == "tiebreak_describe"
    rev = [e for e in events(rid) if e["type"] == "reveal"][-1]["payload"]
    assert rev["outcome"] == "tiebreak" and rev["tied"] == [0, 1]
    # only the tied players speak, at stage 1
    with pytest.raises(StoreError) as e:
        game.submit_statement(rid, pid(rid, 2), "me too")
    assert e.value.status == 409
    assert say_all(rid) == [0, 1]
    st = [m["stage"] for m in get_conn().execute(
        "SELECT stage FROM messages WHERE room_id=? AND seat IN (0,1) ORDER BY id", (rid,))]
    assert st == [0, 0, 1, 1]
    assert room(rid)["phase"] == "revote"
    # tied players do not vote; others vote only for tied players
    with pytest.raises(StoreError) as e:
        game.submit_vote(rid, pid(rid, 0), 1)
    assert e.value.status == 403
    with pytest.raises(StoreError) as e:
        game.submit_vote(rid, pid(rid, 2), 3)
    assert e.value.status == 400
    vote(rid, {2: 0, 3: 0})
    assert 0 not in alive(rid)
    stage1 = get_conn().execute("SELECT COUNT(*) FROM votes WHERE room_id=? AND stage=1",
                                (rid,)).fetchone()[0]
    assert stage1 == 2


def test_revote_still_tied_nobody_out():
    rid = lobby(4)
    start(rid)
    say_all(rid)
    vote(rid, {0: 1, 1: 0, 2: 1, 3: 0})
    say_all(rid)
    vote(rid, {2: 0, 3: 1})
    r = room(rid)
    assert alive(rid) == [0, 1, 2, 3]
    assert r["phase"] == "reveal" or r["status"] == "finished"


# ---- full scripted games ----

def test_full_game_civilian_win():
    rid = lobby(3)
    start(rid)
    spy = spy_seats(rid)[0]
    say_all(rid)
    a_civ = civ_seats(rid)[0]
    vote(rid, {s: (spy if s != spy else a_civ) for s in range(4)})
    r = room(rid)
    assert r["status"] == "finished" and r["winner"] == "civilians" and r["phase"] is None
    over = [e for e in events(rid) if e["type"] == "game_over"]
    assert len(over) == 1 and over[0]["audience"] == "all"
    p = over[0]["payload"]
    assert p["winner"] == "civilians"
    assert {x["seat"]: x["role"] for x in p["roles"]}[spy] == "spy"
    assert set(p["words"]) == {"civilian", "spy"}
    assert set(p["words"]["civilian"]) == {"en", "zh-Hans"}
    snap = visibility.build_snapshot(rid, "pid0")
    assert snap["winner"] == "civilians" and all("role" in x for x in snap["players"])


def test_full_game_spy_win():
    rid = lobby(4)
    start(rid)
    spy = spy_seats(rid)[0]
    for rnd in (1, 2):
        assert room(rid)["round"] == rnd
        say_all(rid)
        victim = other_civ(rid)
        al = alive(rid)
        others = [s for s in al if s != victim]
        votes = {s: victim for s in others}
        votes[victim] = next(s for s in others)
        vote(rid, votes)
        if rnd == 1:
            r = room(rid)
            assert r["phase"] == "reveal" and r["status"] == "playing"
            game.advance_phase(rid, r["phase_seq"])
    r = room(rid)
    assert r["status"] == "finished" and r["winner"] == "spies"
    assert alive(rid) == sorted([spy, other_civ(rid)])


def test_round_cap_spy_win():
    rid = lobby(4)
    start(rid)
    for rnd in range(1, 5):
        assert room(rid)["round"] == rnd
        say_all(rid)
        vote(rid, {s: None for s in range(4)})
        r = room(rid)
        if rnd < 4:
            game.advance_phase(rid, r["phase_seq"])
    r = room(rid)
    assert r["status"] == "finished" and r["winner"] == "spies"


def test_leak_full_scripted_game():
    """Every event, filtered per seat via visible_to, never shows a role or
    another seat's word before game_over (the eliminated seat's role on
    `reveal` is public by design)."""
    rid = lobby(4, langs=["en", "zh-Hans"])
    start(rid)
    spy = spy_seats(rid)[0]
    # round 1: tie -> tiebreak -> revote eliminates a civilian
    say_all(rid)
    c1, c2 = [s for s in civ_seats(rid)][:2]
    rest = [s for s in range(4) if s not in (c1, c2)]
    vote(rid, {c1: c2, c2: c1, rest[0]: c1, rest[1]: c2})
    say_all(rid)
    vote(rid, {rest[0]: c1, rest[1]: c1})
    game.advance_phase(rid, room(rid)["phase_seq"])
    # round 2: a timeout, then the spy is caught
    game.advance_phase(rid, room(rid)["phase_seq"])
    say_all(rid)
    al = alive(rid)
    vote(rid, {s: (spy if s != spy else next(x for x in al if x != spy)) for s in al})
    assert room(rid)["winner"] == "civilians"

    evs = events(rid)
    types = {e["type"] for e in evs}
    assert {"game_started", "turn", "statement", "vote_locked", "reveal", "game_over"} <= types
    over_at = next(i for i, e in enumerate(evs) if e["type"] == "game_over")
    for s in range(4):
        mine = word_of(rid, s)
        for e in evs[:over_at]:
            if not visibility.visible_to(e, s):
                continue
            p = e["payload"]
            text = json.dumps(p, ensure_ascii=False)
            for w in ALL_SECRETS - {mine}:
                assert w not in text, (s, e["type"], w)
            if mine in text:
                assert e["type"] == "game_started" and e["audience"] == f"seat:{s}"
                assert p["my_word"] == mine
            assert "roles" not in text and '"words"' not in text
            if e["type"] == "reveal" and p.get("eliminated") is not None:
                assert p["role"] == seats(rid)[p["eliminated"]]["role"]
                text = json.dumps({k: v for k, v in p.items() if k != "role"})
            assert '"role"' not in text and '"spy"' not in text and '"civilian"' not in text, (s, e)


# ---- leave / host transfer ----

def test_leave_lobby_removes_player_and_transfers_host():
    rid = lobby(3)
    before = last_seq(rid)
    game.leave(rid, "pid0")
    assert sorted(seats(rid)) == [1, 2]
    r = room(rid)
    assert r["host_player_id"] == "pid1"  # longest-present human
    types = [e["type"] for e in events(rid, before)]
    assert "player_left" in types and "player_updated" in types
    with pytest.raises(StoreError):
        game.leave(rid, "pid0")


def test_leaving_player_becomes_bot_mid_game():
    rid = lobby(4)
    start(rid)
    seat = next(s for s, x in seats(rid).items() if x["player_id"] == "pid2")
    before_row = seats(rid)[seat]
    seq = room(rid)["phase_seq"]
    game.leave(rid, "pid2")
    row = seats(rid)[seat]
    assert row["is_bot"] == 1 and row["bot_persona"] in BOT_PERSONA_KEYS
    assert row["name"] == before_row["name"] and row["role"] == before_row["role"]
    assert row["alive"] == 1 and row["player_id"] != "pid2"
    assert store.seat_of(rid, "pid2") is None
    assert room(rid)["status"] == "playing" and room(rid)["phase_seq"] == seq
    ev = [e for e in events(rid) if e["type"] == "player_left"][-1]
    assert ev["audience"] == "all" and ev["payload"]["player"]["is_bot"] is True
    assert "role" not in json.dumps(ev["payload"])


def test_host_leaves_mid_game_transfers_to_longest_present_human():
    rid = lobby(4)
    start(rid)
    game.leave(rid, "pid0")
    assert room(rid)["host_player_id"] == "pid1"
    game.leave(rid, "pid1")
    assert room(rid)["host_player_id"] == "pid2"


def test_last_human_leaves_mid_game_room_finished_no_winner(_game_env):
    rid = lobby(2)
    start(rid)
    game.leave(rid, "pid0")
    game.leave(rid, "pid1")
    r = room(rid)
    assert r["status"] == "finished" and r["winner"] is None and r["phase"] is None
    assert _game_env[-1] == (rid, r["phase_seq"], None)
    seq = r["phase_seq"]
    assert game.advance_phase(rid, seq) is False


# ---- rematch ----

def test_rematch_keeps_players_and_does_not_collide():
    rid = lobby(3)
    start(rid)
    spy = spy_seats(rid)[0]
    say_all(rid)
    vote(rid, {s: (spy if s != spy else civ_seats(rid)[0]) for s in range(4)})
    assert room(rid)["status"] == "finished"
    with pytest.raises(StoreError) as e:
        game.rematch(rid, "pid1")
    assert e.value.status == 403
    game.rematch(rid, "pid0")
    r = room(rid)
    assert r["game_no"] == 2 and r["round"] == 0 and r["status"] == "lobby"
    assert r["pair_id"] is None and r["winner"] is None and r["phase"] is None
    st = seats(rid)
    assert len(st) == 4 and all(x["role"] is None and x["alive"] == 1 for x in st.values())
    snap = visibility.build_snapshot(rid, "pid0")
    assert snap["messages"] == [] and snap["me"]["my_word"] is None
    with pytest.raises(StoreError) as e:
        game.rematch(rid, "pid0")
    assert e.value.status == 409
    # game 2 round 1 rows do not collide with game 1 round 1 rows
    start(rid)
    say_all(rid)
    vote(rid, {s: None for s in range(4)})
    n = {r[0]: r[1] for r in get_conn().execute(
        "SELECT game_no, COUNT(*) FROM votes WHERE room_id=? AND round=1 GROUP BY game_no", (rid,))}
    assert n == {1: 4, 2: 4}
    m = {r[0]: r[1] for r in get_conn().execute(
        "SELECT game_no, COUNT(*) FROM messages WHERE room_id=? AND round=1 GROUP BY game_no", (rid,))}
    assert m == {1: 4, 2: 4}


def test_rematch_only_after_finish():
    rid = lobby(4)
    with pytest.raises(StoreError) as e:
        game.rematch(rid, "pid0")
    assert e.value.status == 409


# ---- routes ----

def guest(client):
    b = client.post(f"{API}/guests").get_json()
    return {"Authorization": f"Bearer {b['player_id']}.{b['token']}"}


def http_room(client, n=3):
    hs = [guest(client) for _ in range(n)]
    code = client.post(f"{API}/rooms", json={"name": "H", "lang": "en"}, headers=hs[0]).get_json()["code"]
    for i, h in enumerate(hs[1:], 1):
        assert client.post(f"{API}/rooms/{code}/join", json={"name": f"P{i}", "lang": "zh-Hans"},
                           headers=h).status_code == 200
    return code, hs


def by_seat(client, code, hs):
    return {client.get(f"{API}/rooms/{code}", headers=h).get_json()["me"]["seat"]: h for h in hs}


def test_routes_start_and_play(client):
    code, hs = http_room(client)
    r = client.post(f"{API}/rooms/{code}/start", headers=hs[1])
    assert r.status_code == 403
    r = client.post(f"{API}/rooms/{code}/start", headers=hs[0])
    assert r.status_code == 200, r.get_json()
    snap = r.get_json()
    assert snap["status"] == "playing" and len(snap["players"]) == 4
    assert snap["me"]["my_word"] in ALL_SECRETS
    seat_h = by_seat(client, code, hs)
    cur = snap["current_speaker"]
    wrong = next(h for s, h in seat_h.items() if s != cur)
    r = client.post(f"{API}/rooms/{code}/statement", json={"text": "hi"}, headers=wrong)
    assert r.status_code == 409
    for bad in (None, [], "x", {"text": 5}, {"text": "y" * 121}, {}):
        r = client.post(f"{API}/rooms/{code}/statement", json=bad, headers=hs[0])
        assert r.status_code in (400, 409), (bad, r.status_code)
    r = client.post(f"{API}/rooms/{code}/statement", data="{not json", headers=hs[0],
                    content_type="application/json")
    assert r.status_code == 400
    r = client.post(f"{API}/rooms/{code}/vote", json={"target_seat": 1}, headers=hs[0])
    assert r.status_code == 409  # describe phase
    for bad in ({}, {"target_seat": "1"}, [1]):
        r = client.post(f"{API}/rooms/{code}/vote", json=bad, headers=hs[0])
        assert r.status_code == 400, bad


def test_routes_own_word_and_long_statement_400(client, conn):
    code, hs = http_room(client)
    snap = client.post(f"{API}/rooms/{code}/start", headers=hs[0]).get_json()
    seat_h = by_seat(client, code, hs)
    cur = snap["current_speaker"]
    if cur not in seat_h:  # the bot's turn: let it time out
        rid = store.get_room_by_code(code)["id"]
        game.advance_phase(rid, room(rid)["phase_seq"])
        cur = client.get(f"{API}/rooms/{code}", headers=hs[0]).get_json()["current_speaker"]
    h = seat_h[cur]
    mine = client.get(f"{API}/rooms/{code}", headers=h).get_json()["me"]["my_word"]
    r = client.post(f"{API}/rooms/{code}/statement", json={"text": f"so {mine}"}, headers=h)
    assert r.status_code == 400 and r.get_json()["error"] == "own_word"
    r = client.post(f"{API}/rooms/{code}/statement", json={"text": "z" * 121}, headers=h)
    assert r.status_code == 400
    r = client.post(f"{API}/rooms/{code}/statement", json={"text": "fine 🙂"}, headers=h)
    assert r.status_code == 200
    assert r.get_json()["messages"][-1]["text"] == "fine 🙂"


def test_routes_bots_leave_rematch(client):
    code, hs = http_room(client, n=2)
    r = client.post(f"{API}/rooms/{code}/bots", json={"action": "add"}, headers=hs[1])
    assert r.status_code == 403
    r = client.post(f"{API}/rooms/{code}/bots", json={"action": "add"}, headers=hs[0])
    assert r.status_code == 200 and len(r.get_json()["players"]) == 3
    r = client.post(f"{API}/rooms/{code}/bots", json={"action": "remove"}, headers=hs[0])
    assert r.status_code == 200 and len(r.get_json()["players"]) == 2
    r = client.post(f"{API}/rooms/{code}/bots", json={"action": "remove"}, headers=hs[0])
    assert r.status_code == 409
    r = client.post(f"{API}/rooms/{code}/bots", json={"action": "boom"}, headers=hs[0])
    assert r.status_code == 400
    r = client.post(f"{API}/rooms/{code}/rematch", headers=hs[0])
    assert r.status_code == 409
    r = client.post(f"{API}/rooms/{code}/leave", headers=hs[1])
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert client.get(f"{API}/rooms/{code}", headers=hs[1]).status_code == 403
    r = client.post(f"{API}/rooms/{code}/leave", headers=hs[1])
    assert r.status_code == 403
    assert client.post(f"{API}/rooms/ZZZZ/leave", headers=hs[0]).status_code == 404
    assert client.post(f"{API}/rooms/{code}/start").status_code == 401


def test_routes_vote_and_rematch(client):
    code, hs = http_room(client, n=4)
    client.post(f"{API}/rooms/{code}/start", headers=hs[0])
    rid = store.get_room_by_code(code)["id"]
    say_all(rid)
    seat_h = by_seat(client, code, hs)
    spy = spy_seats(rid)[0]
    for s, h in seat_h.items():
        target = spy if s != spy else civ_seats(rid)[0]
        r = client.post(f"{API}/rooms/{code}/vote", json={"target_seat": target}, headers=h)
        assert r.status_code == 200, r.get_json()
    snap = client.get(f"{API}/rooms/{code}", headers=hs[0]).get_json()
    assert snap["status"] == "finished" and snap["winner"] == "civilians"
    assert client.post(f"{API}/rooms/{code}/rematch", headers=hs[1]).status_code == 403
    r = client.post(f"{API}/rooms/{code}/rematch", headers=hs[0])
    assert r.status_code == 200 and r.get_json()["status"] == "lobby" and r.get_json()["game_no"] == 2
