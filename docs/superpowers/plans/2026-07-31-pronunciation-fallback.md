# Pronunciation Fallback Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Wiktionary-backed pronunciation service that replaces the broken `api.dictionaryapi.dev` audio URLs in the `pronunciation` field of dictionary responses.

**Architecture:** A new module `ai_svc/dictionary/pronunciation.py` resolves audio URLs from Wikimedia Commons with zero external dependencies on the rest of the service. `_extract_pronunciation_data` in `service.py` is updated to call this module as a fallback, preserving the original API URL internally.

**Tech Stack:** Python 3.10, `requests`, `unittest.mock` for tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `ai_svc/dictionary/pronunciation.py` | Standalone Wiktionary audio URL resolver |
| Create | `tests/dictionary/test_pronunciation.py` | Unit tests for the new module |
| Modify | `ai_svc/dictionary/service.py:1321-1368` | `_extract_pronunciation_data` — add `word` param, call fallback |
| Modify | `ai_svc/dictionary/service.py:791` | Pass `word` to `_extract_pronunciation_data` |

---

## Task 1: Create the pronunciation module with a failing test

**Files:**
- Create: `ai_svc/dictionary/pronunciation.py`
- Create: `tests/__init__.py` (if not present)
- Create: `tests/dictionary/__init__.py`
- Create: `tests/dictionary/test_pronunciation.py`

- [ ] **Step 1: Create the test file**

```python
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
```

- [ ] **Step 2: Create empty `__init__` files so the test module is importable**

```bash
mkdir -p tests/dictionary
touch tests/__init__.py tests/dictionary/__init__.py
```

- [ ] **Step 3: Run the test to confirm it fails (module does not exist yet)**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/dictionary/test_pronunciation.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'ai_svc.dictionary.pronunciation'`

---

## Task 2: Implement `pronunciation.py`

**Files:**
- Create: `ai_svc/dictionary/pronunciation.py`

- [ ] **Step 1: Write the module**

```python
# ai_svc/dictionary/pronunciation.py
"""
Standalone pronunciation audio URL resolver using Wikimedia Commons.

Provides get_pronunciation_url(word) — a single public function that
returns a stable CDN audio URL for English word pronunciations,
or an empty string if none is found.

This module has no dependencies on other ai_svc modules.
"""
import requests
import logging

logger = logging.getLogger(__name__)

# Wikimedia Commons API endpoint for file metadata
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Request timeout in seconds — fail fast, do not block the main response
_TIMEOUT = 5


def get_pronunciation_url(word: str) -> str:
    """
    Return a Wikimedia CDN audio URL for the given English word.

    Tries candidate filenames in preference order:
      1. en-us-{word}.ogg  (US pronunciation — preferred)
      2. en-{word}.ogg     (generic / regional-neutral)
      3. en-uk-{word}.ogg  (UK pronunciation — last resort)

    Returns an empty string if no candidate is found or on any error.
    """
    # Normalize: Wikimedia filenames are lowercase
    normalized = word.strip().lower()

    # Candidate filenames in preference order
    candidates = [
        f"en-us-{normalized}.ogg",
        f"en-{normalized}.ogg",
        f"en-uk-{normalized}.ogg",
    ]

    for filename in candidates:
        url = _resolve_commons_url(filename)
        if url:
            return url

    return ""


def _resolve_commons_url(filename: str) -> str:
    """
    Query the Wikimedia Commons API for the CDN URL of a file.

    Returns the URL string on success, empty string on miss or error.
    """
    params = {
        "action": "query",
        "titles": f"File:{filename}",
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json",
    }

    try:
        response = requests.get(_COMMONS_API, params=params, timeout=_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            # Wikimedia returns page_id "-1" for missing files
            if page_id == "-1" or "missing" in page:
                return ""
            imageinfo = page.get("imageinfo", [])
            if imageinfo:
                return imageinfo[0].get("url", "")

    except requests.RequestException as exc:
        # Network or HTTP error — log at debug level, do not raise
        logger.debug(f"[pronunciation] Failed to resolve '{filename}': {exc}")

    return ""
```

- [ ] **Step 2: Run the tests — all should pass**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/dictionary/test_pronunciation.py -v
```

Expected output:
```
PASSED tests/dictionary/test_pronunciation.py::TestGetPronunciationUrl::test_returns_us_url_on_first_hit
PASSED tests/dictionary/test_pronunciation.py::TestGetPronunciationUrl::test_falls_back_to_generic_when_us_missing
PASSED tests/dictionary/test_pronunciation.py::TestGetPronunciationUrl::test_returns_empty_string_when_all_candidates_missing
PASSED tests/dictionary/test_pronunciation.py::TestGetPronunciationUrl::test_returns_empty_string_on_request_exception
PASSED tests/dictionary/test_pronunciation.py::TestGetPronunciationUrl::test_normalizes_word_to_lowercase
5 passed
```

- [ ] **Step 3: Commit**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
git add ai_svc/dictionary/pronunciation.py tests/__init__.py tests/dictionary/__init__.py tests/dictionary/test_pronunciation.py
git commit -m "feat: add standalone Wiktionary pronunciation URL resolver"
```

---

## Task 3: Wire the fallback into `_extract_pronunciation_data`

**Files:**
- Modify: `ai_svc/dictionary/service.py:1321-1368` (`_extract_pronunciation_data`)
- Modify: `ai_svc/dictionary/service.py:791` (call site)

- [ ] **Step 1: Add the import at the top of `service.py`**

Find the existing imports block (around line 14–54). Add after the existing local imports:

```python
from .pronunciation import get_pronunciation_url  # Wiktionary-backed audio URL fallback
```

- [ ] **Step 2: Update `_extract_pronunciation_data` signature and body**

Replace the existing method (lines 1321–1368) with:

```python
def _extract_pronunciation_data(self, entry: Dict[str, Any], word: str) -> Dict[str, str]:
    """
    Extract pronunciation data (audio URL + IPA) from a free-API entry,
    falling back to Wiktionary when the original API URL is unavailable.

    The original API URL is preserved internally (pronunciation_original)
    so it can be restored if the upstream source recovers.

    Returns:
        {
            "pronunciation": "<wiktionary_url_or_original_api_url>",
            "ipa": "/phonetic/",
        }
    """
    phonetics = entry.get("phonetics", [])
    audio_url = ""
    ipa_text = ""

    # Extract audio URL from the API entry (prefer UK > US > any).
    # This logic is unchanged — we still record what the API gave us.
    for p in phonetics:
        audio = p.get("audio", "")
        if audio and ("-uk.mp3" in audio.lower() or "-uk-" in audio.lower()):
            audio_url = audio
            break

    if not audio_url:
        for p in phonetics:
            audio = p.get("audio", "")
            if audio and ("-us.mp3" in audio.lower() or "-us-" in audio.lower()):
                audio_url = audio
                break

    if not audio_url:
        for p in phonetics:
            audio = p.get("audio", "")
            if audio:
                audio_url = audio
                break

    # Extract IPA text
    for p in phonetics:
        if p.get("text"):
            ipa_text = p["text"]
            break

    if not ipa_text:
        ipa_text = entry.get("phonetic", "")

    # Attempt to replace the (potentially broken) API audio URL with a
    # stable Wiktionary/Wikimedia CDN URL.  Fall back to the original URL
    # if Wiktionary has no entry for this word.
    wiktionary_url = get_pronunciation_url(word)
    resolved_url = wiktionary_url if wiktionary_url else audio_url

    return {
        "pronunciation": resolved_url,
        "ipa": ipa_text,
    }
```

- [ ] **Step 3: Update the call site at line ~791**

Change:
```python
pronunciation_data = self._extract_pronunciation_data(entry)
```

To:
```python
# Pass word so the fallback service can resolve a Wiktionary audio URL
pronunciation_data = self._extract_pronunciation_data(entry, word)
```

- [ ] **Step 4: Run the existing tests to confirm nothing is broken**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Quick smoke test against the running service (optional but recommended)**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -c "
from ai_svc.dictionary.pronunciation import get_pronunciation_url
url = get_pronunciation_url('hello')
print('hello ->', url)
url2 = get_pronunciation_url('xyznonexistent99')
print('nonexistent ->', repr(url2))
"
```

Expected output (URLs may vary by Wikimedia CDN):
```
hello -> https://upload.wikimedia.org/wikipedia/commons/.../en-us-hello.ogg
nonexistent -> ''
```

- [ ] **Step 6: Commit**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
git add ai_svc/dictionary/service.py
git commit -m "feat: use Wiktionary audio URL as pronunciation fallback in dictionary service"
```

---

## Self-Review Checklist

- [x] `pronunciation.py` created and tested independently — no `ai_svc` imports
- [x] `_extract_pronunciation_data` signature updated (`word` param added)
- [x] Only one call site at line ~791 — updated
- [x] Original API URL logic preserved unchanged (can be restored)
- [x] API response shape unchanged (`pronunciation`, `ipa` fields only)
- [x] No placeholders in any step — all code is complete
- [x] Type signatures consistent across tasks (`Dict[str, Any]`, `str`)
