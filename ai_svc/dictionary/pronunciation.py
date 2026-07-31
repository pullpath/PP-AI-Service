# ai_svc/dictionary/pronunciation.py
"""
Standalone pronunciation audio URL resolver using Oxford Learner's Dictionaries.

Provides get_pronunciation_url(word) — a single public function that
returns a stable MP3 URL for English word pronunciations,
or an empty string if the word cannot be resolved.

URL construction is fully deterministic (no HTTP call required).
Oxford Learner's Dictionaries CDN follows a fixed directory hierarchy
based on the word string, making lookups instantaneous.

This module has no dependencies on other ai_svc modules.
"""
import requests
import logging

logger = logging.getLogger(__name__)

# Oxford Learner's Dictionaries US pronunciation CDN base
_OXFORD_BASE = "https://www.oxfordlearnersdictionaries.com/media/english/us_pron"

# Timeout for the optional URL existence check (seconds)
_TIMEOUT = 5

# Oxford CDN requires a browser-like User-Agent; requests without it get 403
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_pronunciation_url(word: str) -> str:
    """
    Return an Oxford Learner's Dictionaries MP3 URL for the given English word.

    URL construction is deterministic — the Oxford CDN organises files in a
    hierarchy derived from the word string itself, so no API call is needed
    to build the URL.  A lightweight HEAD request verifies the file exists
    before returning it; returns empty string on miss or network error.

    Args:
        word: An English word (single token, e.g. "hello", "run").

    Returns:
        A direct MP3 URL string, or "" if not found / unreachable.
    """
    normalized = word.strip().lower()
    if not normalized:
        return ""

    url = _build_oxford_url(normalized)

    # Verify the file actually exists via a HEAD request (no body download).
    # Falls back to empty string on timeout or HTTP error.
    try:
        response = requests.head(url, timeout=_TIMEOUT, allow_redirects=True, headers=_HEADERS)
        if response.status_code == 200:
            return url
    except requests.RequestException as exc:
        # Network or HTTP error — log at debug level, do not raise
        logger.debug(f"[pronunciation] HEAD check failed for '{normalized}': {exc}")

    return ""


def _build_oxford_url(word: str) -> str:
    """
    Construct the Oxford CDN URL for a word's US pronunciation MP3.

    Oxford organises pronunciation files in a three-level directory hierarchy:
      - Level 1: first character of the word
      - Level 2: first 3 characters of the word, right-padded with "_" to length 3
      - Level 3: first 5 characters of the filename (word + "__us_1.mp3"),
                 right-padded with "_" to length 5

    Example:
      "hello"   -> h/hel/hello/hello__us_1.mp3
      "run"     -> r/run/run__/run__us_1.mp3
      "go"      -> g/go_/go__u/go__us_1.mp3
      "a"       -> a/a__/a__us/a__us_1.mp3

    Args:
        word: Normalised (lowercase, stripped) English word.

    Returns:
        Full CDN URL string.
    """
    filename = f"{word}__us_1.mp3"

    # Pad word and filename with underscores to safely slice directory segments
    padded_word = word + "_____"
    padded_filename = filename + "_____"

    level1 = padded_word[0]          # single character
    level2 = padded_word[:3]         # 3 characters
    level3 = padded_filename[:5]     # 5 characters (first 5 of the mp3 filename)

    return f"{_OXFORD_BASE}/{level1}/{level2}/{level3}/{filename}"
