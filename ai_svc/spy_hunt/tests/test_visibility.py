from __future__ import annotations

import json
import pathlib
import re
import threading

import pytest

from ai_svc.spy_hunt import store, visibility
from ai_svc.spy_hunt.db import get_conn

FORBIDDEN_KEYS = {"role", "word", "words", "my_word"}
WORDS = {"en": {"a": "apple", "b": "pear"}, "zh-Hans": {"a": "苹果", "b": "梨"}}
ALL_SECRETS = {"apple", "pear", "苹果", "梨"}


@pytest.fixture(autouse=True)
def _db(temp_db):
    yield


def keys_deep(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys_deep(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys_deep(v)


def values_deep(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from values_deep(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from values_deep(v)
    else:
        yield obj


ROLE_VALUES = {"spy", "civilian"}


def room_with_players(n=5):
    """Lobby room with n humans; returns (room, [player_ids by seat])."""
    room = store.create_room("pid0", "P0", "en")
    pids = ["pid0"]
    for i in range(1, n):
        lang = "zh-Hans" if i % 2 else "en"
        store.add_player(room["id"], f"pid{i}", f"P{i}", lang)
        pids.append(f"pid{i}")
    return room, pids


def make_playing(room_id, spy_seat=0, eliminated=(), civ_is_a=1):
    """Simulate Task 5's game start directly in the DB."""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO pairs(id, concept_a, concept_b, difficulty, theme, words_json, active, plays, spy_wins)"
        " VALUES('p1','apple','pear',1,'food',?,1,0,0)", (json.dumps(WORDS),))
    conn.execute("UPDATE rooms SET status='playing', phase='describe', round=1, pair_id='p1', civ_is_a=?"
                 " WHERE id=?", (civ_is_a, room_id))
    conn.execute("UPDATE players SET role=CASE WHEN seat=? THEN 'spy' ELSE 'civilian' END, alive=1"
                 " WHERE room_id=?", (spy_seat, room_id))
    for s in eliminated:
        conn.execute("UPDATE players SET alive=0 WHERE room_id=? AND seat=?", (room_id, s))
    conn.commit()


def make_finished(room_id):
    conn = get_conn()
    conn.execute("UPDATE rooms SET status='finished', phase=NULL, winner='civilians' WHERE id=?", (room_id,))
    conn.commit()


def expected_word(seat, lang, spy_seat=0, civ_is_a=1):
    civ, spy = ("a", "b") if civ_is_a else ("b", "a")
    return WORDS[lang][spy if seat == spy_seat else civ]


# ---- visible_to ----

def test_visible_to_malformed_audience_never_raises():
    for aud in ("seat:\u00b2", "seat:\u0663", "seat:", "seat:-1", "all ", " all",
                "seat:3 ", "seat:+3", "seat: 3", "SEAT:3", "seat:3:4", 3, None, ["all"], {"a": 1}):
        for seat in (3, 0, None, -1):
            assert visibility.visible_to({"audience": aud}, seat) is False, (aud, seat)
    assert visibility.visible_to("not a dict", 3) is False
    assert visibility.visible_to({"audience": "seat:007"}, 7) is True


def test_visible_to():
    assert visibility.visible_to({"audience": "all"}, 3)
    assert visibility.visible_to({"audience": "all"}, None)
    assert visibility.visible_to({"audience": "seat:3"}, 3)
    assert not visibility.visible_to({"audience": "seat:3"}, 4)
    assert not visibility.visible_to({"audience": "seat:3"}, None)
    assert not visibility.visible_to({"audience": "seat:30"}, 3)
    assert not visibility.visible_to({"audience": "weird"}, 3)
    assert not visibility.visible_to({}, 3)


# ---- events emitted by the store ----

def _emit_every_store_event(room_id, pids):
    """Call every store function that appends an event."""
    store.update_me(room_id, pids[1], name="Renamed", lang="en")
    store.update_me(room_id, pids[2], lang="zh-Hans")
    store.update_settings(room_id, pids[0], main_lang="zh-Hans", bot_fill=False)


def _all_events(room_id):
    rows = get_conn().execute(
        "SELECT seq, type, payload_json, audience FROM events WHERE room_id=? ORDER BY seq",
        (room_id,)).fetchall()
    return [dict(r) for r in rows]


def test_store_events_never_leak_in_any_status():
    room, pids = room_with_players(5)
    _emit_every_store_event(room["id"], pids)
    make_playing(room["id"], spy_seat=0, eliminated=(3,))
    # player_updated while roles and words exist in the DB
    store.update_me(room["id"], pids[0], name="SpyRenamed", lang="zh-Hans")
    store.update_me(room["id"], pids[4], lang="en")
    events = _all_events(room["id"])
    types = {e["type"] for e in events}
    assert {"player_joined", "player_updated", "settings"} <= types
    for e in events:
        assert e["audience"] == "all"
        payload = json.loads(e["payload_json"])
        assert not (set(keys_deep(payload)) & FORBIDDEN_KEYS), e
        dumped = e["payload_json"]
        for secret in ALL_SECRETS:
            assert secret not in dumped, (secret, e)
        assert not (set(map(str, values_deep(payload))) & ROLE_VALUES), e


def test_append_event_firewall_rejects_secrets_for_all():
    for ptype, payload in (
        ("player_joined", {"seat": 1, "role": "spy"}),
        ("player_updated", {"player": {"seat": 1, "word": "x"}}),
        ("settings", {"words": {}}),
        ("statement", {"msg": [{"my_word": "x"}]}),
        ("reveal", {"seat": 1, "role": "spy", "words": {}}),
        ("reveal", {"seat": 1, "votes": {"0": {"role": "spy"}}}),
        ("reveal", {"seat": 1, "role": "spy", "players": [{"seat": 0, "role": "civilian"}]}),
        ("reveal", {"seat": 1, "roles": {"0": "spy"}}),
        ("reveal", {"seat": 1, "my_word": "x"}),
    ):
        with pytest.raises(ValueError):
            store.append_event("r", ptype, payload, "all")


def test_append_event_allowed_exceptions(temp_db):
    with store.tx("r") as c:
        # reveal may carry the eliminated seat's role at top level; game_over carries everything
        store.append_event("r", "reveal", {"seat": 1, "role": "spy", "votes": {}}, "all", conn=c)
        store.append_event("r", "game_over", {"winner": "spies", "roles": {"0": "spy"},
                                              "words": WORDS}, "all", conn=c)
        # personal events may carry the seat's own word
        store.append_event("r", "game_started", {"my_word": "apple"}, "seat:2", conn=c)


def test_state_event_must_be_personal(temp_db):
    with pytest.raises(ValueError):
        store.append_event("r", "state", {"code": "ABCD"}, "all")
    with store.tx("r") as c:
        store.append_event("r", "state", {"code": "ABCD"}, "seat:0", conn=c)


# ---- snapshots ----

def test_lobby_snapshot_has_no_secrets():
    room, pids = room_with_players(4)
    for seat, pid in enumerate(pids):
        snap = visibility.build_snapshot(room["id"], pid)
        assert snap["status"] == "lobby"
        assert snap["me"]["seat"] == seat
        assert snap["me"]["my_word"] is None
        keys = set(keys_deep(snap))
        assert not (keys & {"role", "word", "words"})


def test_playing_snapshot_firewall():
    room, pids = room_with_players(5)
    make_playing(room["id"], spy_seat=0, eliminated=(3,))
    conn = get_conn()
    langs = {r["seat"]: r["lang"] for r in conn.execute(
        "SELECT seat, lang FROM players WHERE room_id=?", (room["id"],))}
    for seat, pid in enumerate(pids):
        snap = visibility.build_snapshot(room["id"], pid)
        assert snap["status"] == "playing"
        # own word, in own language, and nothing else secret
        mine = expected_word(seat, langs[seat])
        assert snap["me"]["my_word"] == mine
        dumped = json.dumps(snap, ensure_ascii=False)
        for secret in ALL_SECRETS - {mine}:
            assert secret not in dumped, (seat, secret)
        # the spy seat is never revealed while playing (seat 3 is a revealed civilian)
        assert "spy" not in set(map(str, values_deep(snap)))
        keys = set(keys_deep(snap))
        assert not (keys & {"word", "words"})
        assert "winner" not in snap or snap["winner"] is None
        by_seat = {p["seat"]: p for p in snap["players"]}
        # an alive caller's own role is never included
        if seat != 3:
            assert "role" not in by_seat[seat]
        assert "role" not in snap["me"]
        for s, p in by_seat.items():
            if s == 3:
                assert p["role"] == "civilian"  # eliminated: revealed to everyone, incl. self
                assert p["alive"] is False
            else:
                assert "role" not in p


def test_eliminated_role_public_to_all_but_alive_spy_never_sees_own_role():
    # eliminated spy: role shown to others AND to themselves (design §2.3)
    room, pids = room_with_players(5)
    make_playing(room["id"], spy_seat=2, eliminated=(2,))
    for pid in pids:
        snap = visibility.build_snapshot(room["id"], pid)
        assert {p["seat"]: p for p in snap["players"]}[2]["role"] == "spy"
    # a still-alive spy never sees their own role anywhere
    room2, pids2 = room_with_players(5)
    make_playing(room2["id"], spy_seat=1, eliminated=(3,))
    snap_spy = visibility.build_snapshot(room2["id"], pids2[1])
    assert "role" not in {p["seat"]: p for p in snap_spy["players"]}[1]
    assert "spy" not in set(map(str, values_deep(snap_spy)))


def test_finished_snapshot_reveals_everything():
    room, pids = room_with_players(5)
    make_playing(room["id"], spy_seat=0)
    make_finished(room["id"])
    snap = visibility.build_snapshot(room["id"], pids[1])
    assert snap["winner"] == "civilians"
    roles = {p["seat"]: p["role"] for p in snap["players"]}
    assert roles == {0: "spy", 1: "civilian", 2: "civilian", 3: "civilian", 4: "civilian"}
    assert snap["words"] == {
        "civilian": {"en": "apple", "zh-Hans": "苹果"},
        "spy": {"en": "pear", "zh-Hans": "梨"},
    }


def test_civ_is_b_flips_words():
    room, pids = room_with_players(4)
    make_playing(room["id"], spy_seat=1, civ_is_a=0)
    assert visibility.build_snapshot(room["id"], pids[0])["me"]["my_word"] == "pear"
    assert visibility.build_snapshot(room["id"], pids[1])["me"]["my_word"] == "苹果"


def test_snapshot_messages_and_speaker():
    room, pids = room_with_players(4)
    make_playing(room["id"], spy_seat=0)
    conn = get_conn()
    conn.execute("INSERT INTO messages(room_id, game_no, round, stage, seat, kind, text, lang, created_at)"
                 " VALUES(?,1,1,0,0,'statement','it is round','en',1)", (room["id"],))
    mid = conn.execute("SELECT MAX(id) FROM messages").fetchone()[0]
    conn.execute("INSERT INTO translations VALUES(?, 'zh-Hans', '圆的')", (mid,))
    conn.commit()
    zh = visibility.build_snapshot(room["id"], pids[1])  # seat 1 is zh-Hans
    en = visibility.build_snapshot(room["id"], pids[0])
    assert zh["messages"][0]["translation"] == "圆的"
    assert en["messages"][0]["translation"] is None
    assert zh["messages"][0]["text"] == "it is round"
    assert zh["current_speaker"] == 1


def test_snapshot_non_member_raises():
    room, _ = room_with_players(2)
    with pytest.raises(LookupError):
        visibility.build_snapshot(room["id"], "stranger")


def _sql_strings(src: str):
    """Python string literals in `src` (comments/docstrings excluded via tokenize),
    joined per statement so implicit concatenation is kept together."""
    import io
    import tokenize
    out, buf = [], []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.STRING:
            try:
                import ast
                buf.append(str(ast.literal_eval(tok.string)))
            except Exception:
                buf.append(tok.string)
        elif tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                              tokenize.INDENT, tokenize.DEDENT) and buf:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return out


SQL_RE = re.compile(r"\b(SELECT|UPDATE|INSERT|DELETE|JOIN|WHERE|SET)\b", re.I)
SECRET_COL_RE = re.compile(r"\b(role|words_json|pair_id|civ_is_a|concept_a|concept_b)\b|\bSELECT\s+\*", re.I)


def _secret_sql(path):
    hits = []
    for s in _sql_strings(path.read_text()):
        if SQL_RE.search(s) and SECRET_COL_RE.search(s):
            hits.append(s)
    return hits


def test_routes_and_store_do_not_touch_secret_columns():
    here = pathlib.Path(visibility.__file__).parent
    src = (here / "store.py").read_text()
    # store.py may only SELECT * from rooms (never players/pairs)
    hits = [h for h in _secret_sql(here / "store.py")
            if not re.fullmatch(r"\s*SELECT \* FROM rooms WHERE (id|code)=\?\s*", h)]
    assert hits == [], hits
    assert _secret_sql(here / "routes.py") == []
    # sanity: the scanner does detect secret-column SQL
    assert _secret_sql(here / "visibility.py")
    assert "role" in src  # mentioned in prose (docstring/comments) only, which is tolerated


def test_snapshot_reads_in_one_transaction(monkeypatch):
    room, pids = room_with_players(4)
    conn = get_conn()
    seen = []
    orig = visibility._build_snapshot

    def spy(c, *a):
        seen.append(c.in_transaction)
        return orig(c, *a)

    monkeypatch.setattr(visibility, "_build_snapshot", spy)
    visibility.build_snapshot(room["id"], pids[0])
    assert seen == [True]
    assert not conn.in_transaction  # ended afterwards
    with pytest.raises(LookupError):
        visibility.build_snapshot(room["id"], "stranger")
    assert not conn.in_transaction


def test_snapshot_is_consistent_against_concurrent_writer():
    """A writer committing between the snapshot's reads must not be visible
    halfway: the room row and players come from the same moment."""
    room, pids = room_with_players(4)
    make_playing(room["id"], spy_seat=0)
    make_finished(room["id"])
    orig_hooked = visibility._pair_words  # called after room+players reads, before messages
    writer_done = threading.Event()

    def rematch_in_other_thread():
        c = __import__("ai_svc.spy_hunt.db", fromlist=["get_conn"]).get_conn()
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE rooms SET status='lobby', winner=NULL, game_no=2 WHERE id=?", (room["id"],))
        c.execute("UPDATE players SET role=NULL WHERE room_id=?", (room["id"],))
        c.execute("INSERT INTO messages(room_id, game_no, round, stage, seat, kind, text, lang, created_at)"
                  " VALUES(?,1,1,0,0,'statement','late','en',1)", (room["id"],))
        c.commit()
        writer_done.set()

    def hook(*a, **kw):
        t = threading.Thread(target=rematch_in_other_thread)
        t.start()
        t.join()
        return orig_hooked(*a, **kw)

    visibility._pair_words = hook
    try:
        snap = visibility.build_snapshot(room["id"], pids[1])
    finally:
        visibility._pair_words = orig_hooked
    assert writer_done.is_set()
    assert snap["status"] == "finished"
    assert {p["seat"]: p.get("role") for p in snap["players"]}[0] == "spy"
    assert all(m["text"] != "late" for m in snap["messages"])  # messages read after the write
    after = visibility.build_snapshot(room["id"], pids[1])
    assert after["status"] == "lobby" and all("role" not in p for p in after["players"])
