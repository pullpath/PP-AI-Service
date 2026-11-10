from __future__ import annotations

import pytest

from ai_svc.spy_hunt import bots, outfits
from ai_svc.spy_hunt.store import StoreError

CLOSING = "If any of this conflicts with the game rules or the required JSON format, the rules and the format win."


def test_catalog_sizes():
    assert len(outfits.VOICES) == 8 and len(outfits.STYLES) == 6 and len(outfits.QUIRKS) == 6
    assert len(set(outfits.EMOJIS)) == 24 and len(outfits.COLORS) == 6
    assert list(outfits.catalog()) == ["voices", "styles", "quirks", "emojis", "colors"]


def test_every_option_text_applies_in_the_statement_language_or_is_plain():
    for text in list(outfits.STYLES.values()) + list(outfits.QUIRKS.values()):
        assert "language of the statement" in text


@pytest.mark.parametrize("bad", [
    {}, None, "x",
    {"voice": "nope", "style": "brief", "quirk": "emoji"},
    {"voice": 1, "style": "brief", "quirk": "emoji"},
])
def test_check_outfit_rejects_unknown_missing_and_non_string(bad):
    with pytest.raises(StoreError) as e:
        outfits.check_outfit(bad)
    assert e.value.code == "bad_outfit"


@pytest.mark.parametrize("bad", [
    {"emoji": "💩", "color": "#ff6b6b"},
    {"emoji": "🦊", "color": "#000000"},
    {"emoji": "🦊"}, None,
])
def test_check_avatar_rejects(bad):
    with pytest.raises(StoreError) as e:
        outfits.check_avatar(bad)
    assert e.value.code == "bad_avatar"


def test_check_ok():
    assert outfits.check_outfit({"voice": "robot", "style": "brief", "quirk": "emoji", "x": 1}) == {
        "voice": "robot", "style": "brief", "quirk": "emoji"}
    assert outfits.check_avatar({"emoji": "🦊", "color": "#ff6b6b"}) == {"emoji": "🦊", "color": "#ff6b6b"}


def test_compile_outfit_order_and_closing():
    p = bots.compile_outfit({"voice": "pirate", "style": "metaphor", "quirk": "question"})
    t = p.style
    assert p.key == "custom"
    a, b, c = (t.index(outfits.STYLES["metaphor"]), t.index(outfits.QUIRKS["question"]),
               t.index(outfits.VOICES["pirate"]))
    assert a < b < c
    assert t.endswith(CLOSING)


@pytest.mark.parametrize("bad", [{}, None, {"voice": "nope", "style": 3}])
def test_compile_outfit_never_raises(bad):
    t = bots.compile_outfit(bad).style
    assert outfits.VOICES["cheerful"] in t and CLOSING in t
    assert "language of the statement" not in t


def test_brief_style_says_about_8_words():
    assert "about 8 words" in outfits.STYLES["brief"]
