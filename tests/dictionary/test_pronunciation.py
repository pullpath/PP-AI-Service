# tests/dictionary/test_pronunciation.py
"""Unit tests for the standalone pronunciation URL resolver."""
from unittest.mock import patch, MagicMock
from ai_svc.dictionary.pronunciation import get_pronunciation_url, _build_oxford_url


class TestBuildOxfordUrl:
    """Tests for the deterministic URL construction (no network)."""

    def test_hello(self):
        url = _build_oxford_url("hello")
        assert url == "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/h/hel/hello/hello__us_1.mp3"

    def test_run(self):
        # 3-char word: level2="run", level3="run__"
        url = _build_oxford_url("run")
        assert url == "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/r/run/run__/run__us_1.mp3"

    def test_go(self):
        # 2-char word: level2="go_", level3="go__u"
        url = _build_oxford_url("go")
        assert url == "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/g/go_/go__u/go__us_1.mp3"

    def test_a(self):
        # 1-char word: level2="a__", level3="a__us"
        url = _build_oxford_url("a")
        assert url == "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/a/a__/a__us/a__us_1.mp3"

    def test_beautiful(self):
        # 9-char word: level2="bea", level3="beaut"
        url = _build_oxford_url("beautiful")
        assert url == "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/b/bea/beaut/beautiful__us_1.mp3"


class TestGetPronunciationUrl:
    """Tests for the public function (mocked HEAD request)."""

    def _mock_head_200(self):
        resp = MagicMock()
        resp.status_code = 200
        return resp

    def _mock_head_404(self):
        resp = MagicMock()
        resp.status_code = 404
        return resp

    @patch("ai_svc.dictionary.pronunciation.requests.head")
    def test_returns_url_when_head_200(self, mock_head):
        """Should return the constructed URL when the HEAD check succeeds."""
        mock_head.return_value = self._mock_head_200()
        result = get_pronunciation_url("hello")
        expected = "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/h/hel/hello/hello__us_1.mp3"
        assert result == expected

    @patch("ai_svc.dictionary.pronunciation.requests.head")
    def test_returns_empty_string_when_head_404(self, mock_head):
        """Should return empty string when the file doesn't exist on CDN."""
        mock_head.return_value = self._mock_head_404()
        result = get_pronunciation_url("xyznonexistent")
        assert result == ""

    @patch("ai_svc.dictionary.pronunciation.requests.head")
    def test_returns_empty_string_on_request_exception(self, mock_head):
        """Should return empty string when the HEAD request raises."""
        import requests as req
        mock_head.side_effect = req.RequestException("timeout")
        result = get_pronunciation_url("hello")
        assert result == ""

    @patch("ai_svc.dictionary.pronunciation.requests.head")
    def test_normalizes_word_to_lowercase(self, mock_head):
        """Should normalize word to lowercase before constructing URL."""
        mock_head.return_value = self._mock_head_200()
        result = get_pronunciation_url("HELLO")
        expected = "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/h/hel/hello/hello__us_1.mp3"
        assert result == expected

    @patch("ai_svc.dictionary.pronunciation.requests.head")
    def test_returns_empty_string_for_empty_word(self, mock_head):
        """Should return empty string without making a request for empty input."""
        result = get_pronunciation_url("")
        mock_head.assert_not_called()
        assert result == ""
