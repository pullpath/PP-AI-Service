# tests/dictionary/test_pronunciation.py
"""Unit tests for the standalone pronunciation URL resolver."""
import pytest
from unittest.mock import patch, MagicMock
from ai_svc.dictionary.pronunciation import get_pronunciation_url


class TestGetPronunciationUrl:

    def _make_commons_response(self, page_id: int, url: str) -> dict:
        """Helper: build a fake Wikimedia Commons API response."""
        return {
            "query": {
                "pages": {
                    str(page_id): {
                        "pageid": page_id,
                        "imageinfo": [{"url": url}]
                    }
                }
            }
        }

    def _make_missing_response(self) -> dict:
        """Helper: Wikimedia page-not-found response (page id is -1)."""
        return {
            "query": {
                "pages": {
                    "-1": {"missing": ""}
                }
            }
        }

    @patch("ai_svc.dictionary.pronunciation.requests.get")
    def test_returns_us_url_on_first_hit(self, mock_get):
        """Should return the CDN URL for the en-us candidate on first match."""
        cdn_url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/en-us-hello.ogg"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_commons_response(12345, cdn_url)
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = get_pronunciation_url("hello")
        assert result == cdn_url

    @patch("ai_svc.dictionary.pronunciation.requests.get")
    def test_falls_back_to_generic_when_us_missing(self, mock_get):
        """Should try en-{word}.ogg when en-us-{word}.ogg is missing."""
        cdn_url = "https://upload.wikimedia.org/wikipedia/commons/b/bc/en-hello.ogg"

        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if "en-us-hello" in url:
                resp.json.return_value = self._make_missing_response()
            else:
                resp.json.return_value = self._make_commons_response(99, cdn_url)
            return resp

        mock_get.side_effect = side_effect
        result = get_pronunciation_url("hello")
        assert result == cdn_url

    @patch("ai_svc.dictionary.pronunciation.requests.get")
    def test_returns_empty_string_when_all_candidates_missing(self, mock_get):
        """Should return empty string when no candidate is found."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = self._make_missing_response()
        mock_get.return_value = mock_resp

        result = get_pronunciation_url("xyznonexistent")
        assert result == ""

    @patch("ai_svc.dictionary.pronunciation.requests.get")
    def test_returns_empty_string_on_request_exception(self, mock_get):
        """Should return empty string when the HTTP request fails."""
        import requests as req
        mock_get.side_effect = req.RequestException("network error")

        result = get_pronunciation_url("hello")
        assert result == ""

    @patch("ai_svc.dictionary.pronunciation.requests.get")
    def test_normalizes_word_to_lowercase(self, mock_get):
        """Should normalize word to lowercase before building filenames."""
        cdn_url = "https://upload.wikimedia.org/wikipedia/commons/x/xx/en-us-hello.ogg"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = self._make_commons_response(1, cdn_url)
        mock_get.return_value = mock_resp

        result = get_pronunciation_url("HELLO")
        assert result == cdn_url
        # Confirm the URL sent to requests used lowercase
        call_url = mock_get.call_args[0][0]
        assert "en-us-hello" in call_url
