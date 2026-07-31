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
from urllib.parse import urlencode

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
    url = f"{_COMMONS_API}?{urlencode(params)}"

    try:
        response = requests.get(url, timeout=_TIMEOUT)
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
