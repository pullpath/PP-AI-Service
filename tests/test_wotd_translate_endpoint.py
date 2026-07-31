"""Integration tests for POST /api/wotd/translate."""
import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(tmp_path):
    """Flask test client with mocked services."""
    import app as flask_app

    flask_app.app.config["TESTING"] = True

    # Patch the cache service so tests use a temp DB, not the real cache.db
    with patch.object(flask_app, "wotd_translation_cache_service") as mock_cache, \
         patch.object(flask_app, "dictionary_service") as mock_dict, \
         patch.object(flask_app, "translation_service") as mock_trans:

        flask_app._test_mock_cache = mock_cache
        flask_app._test_mock_dict = mock_dict
        flask_app._test_mock_trans = mock_trans

        with flask_app.app.test_client() as c:
            c._mock_cache = mock_cache
            c._mock_dict = mock_dict
            c._mock_trans = mock_trans
            yield c


def post_wotd_translate(client, body):
    return client.post(
        "/api/wotd/translate",
        data=json.dumps(body),
        content_type="application/json"
    )


def test_missing_word_returns_400(client):
    resp = post_wotd_translate(client, {"target_lang": "zh-cn"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "word" in data["error"]


def test_missing_target_lang_returns_400(client):
    resp = post_wotd_translate(client, {"word": "serendipity"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "target_lang" in data["error"]


def test_empty_word_returns_400(client):
    resp = post_wotd_translate(client, {"word": "  ", "target_lang": "zh-cn"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False


def test_cache_hit_returns_cached_translation(client):
    client._mock_dict.get_example_for_word.return_value = "She found it by serendipity."
    client._mock_cache.get.return_value = "她偶然发现了它。"

    resp = post_wotd_translate(client, {"word": "serendipity", "target_lang": "zh-cn"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["translation"] == "她偶然发现了它。"
    assert data["cache_status"] == "hit"
    assert data["example_sentence"] == "She found it by serendipity."
    # LLM should NOT have been called
    client._mock_trans.translate.assert_not_called()


def test_cache_miss_calls_llm_and_caches(client):
    client._mock_dict.get_example_for_word.return_value = "She found it by serendipity."
    client._mock_cache.get.return_value = None  # miss
    client._mock_trans.translate.return_value = {
        "success": True, "translation": "她偶然发现了它。"
    }

    resp = post_wotd_translate(client, {"word": "serendipity", "target_lang": "zh-cn"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["translation"] == "她偶然发现了它。"
    assert data["cache_status"] == "miss"
    # Cache should have been written
    client._mock_cache.set.assert_called_once_with(
        "serendipity", "zh-cn", "She found it by serendipity.", "她偶然发现了它。"
    )


def test_no_example_returns_500(client):
    client._mock_dict.get_example_for_word.return_value = ""
    client._mock_cache.get.return_value = None

    resp = post_wotd_translate(client, {"word": "unknownword", "target_lang": "zh-cn"})
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["success"] is False
    assert "example" in data["error"].lower()


def test_translation_failure_returns_500(client):
    client._mock_dict.get_example_for_word.return_value = "She found it by serendipity."
    client._mock_cache.get.return_value = None
    client._mock_trans.translate.return_value = {
        "success": False, "error": "DeepSeek timeout"
    }

    resp = post_wotd_translate(client, {"word": "serendipity", "target_lang": "zh-cn"})
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["success"] is False
