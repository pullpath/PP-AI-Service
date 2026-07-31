"""Tests for WotdTranslationCacheService."""
import os
import time
import pytest
from ai_svc.translation.wotd_cache_service import WotdTranslationCacheService


@pytest.fixture
def cache(tmp_path):
    db_path = str(tmp_path / "test_cache.db")
    svc = WotdTranslationCacheService(db_path=db_path)
    return svc


def test_get_returns_none_on_miss(cache):
    result = cache.get("serendipity", "zh-cn", "She found it by serendipity.")
    assert result is None


def test_set_and_get_hit(cache):
    cache.set("serendipity", "zh-cn", "She found it by serendipity.", "她偶然发现了它。")
    result = cache.get("serendipity", "zh-cn", "She found it by serendipity.")
    assert result == "她偶然发现了它。"


def test_get_returns_none_when_example_changed(cache):
    cache.set("serendipity", "zh-cn", "She found it by serendipity.", "她偶然发现了它。")
    # Example sentence changed — cache should be considered stale
    result = cache.get("serendipity", "zh-cn", "It was pure serendipity.")
    assert result is None


def test_set_overwrites_existing_entry(cache):
    cache.set("serendipity", "zh-cn", "She found it by serendipity.", "她偶然发现了它。")
    cache.set("serendipity", "zh-cn", "She found it by serendipity.", "她是偶然找到的。")
    result = cache.get("serendipity", "zh-cn", "She found it by serendipity.")
    assert result == "她是偶然找到的。"


def test_invalidate_removes_entry(cache):
    cache.set("serendipity", "zh-cn", "She found it by serendipity.", "她偶然发现了它。")
    cache.invalidate("serendipity", "zh-cn")
    result = cache.get("serendipity", "zh-cn", "She found it by serendipity.")
    assert result is None


def test_different_target_langs_are_independent(cache):
    cache.set("ephemeral", "zh-cn", "It was ephemeral.", "它是短暂的。")
    cache.set("ephemeral", "ja", "It was ephemeral.", "それは束の間だった。")
    assert cache.get("ephemeral", "zh-cn", "It was ephemeral.") == "它是短暂的。"
    assert cache.get("ephemeral", "ja", "It was ephemeral.") == "それは束の間だった。"


def test_invalidate_is_scoped_to_target_lang(cache):
    cache.set("ephemeral", "zh-cn", "It was ephemeral.", "它是短暂的。")
    cache.set("ephemeral", "ja", "It was ephemeral.", "それは束の間だった。")
    cache.invalidate("ephemeral", "zh-cn")
    assert cache.get("ephemeral", "zh-cn", "It was ephemeral.") is None
    assert cache.get("ephemeral", "ja", "It was ephemeral.") == "それは束の間だった。"
