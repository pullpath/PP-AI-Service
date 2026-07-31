# Pronunciation Fallback Service — Design Spec

**Date:** 2026-07-31  
**Status:** Approved

## Problem

The `pronunciation` field in dictionary API responses currently contains audio URLs from
`api.dictionaryapi.dev/media/pronunciations/en/...`. These URLs are broken/unreliable.
The field must continue to be populated with a working audio URL.

## Goals

- Replace the broken audio URL with a stable alternative from Wiktionary/Wikimedia Commons
- Keep the existing API response shape identical (`pronunciation` field remains a direct audio URL)
- Preserve the original API URL internally so it can be restored if the source is fixed
- The pronunciation resolution logic is a standalone module with no dependencies on other service code
- Minimal changes to `service.py`

## New Module: `ai_svc/dictionary/pronunciation.py`

Single public function:

```python
def get_pronunciation_url(word: str) -> str:
    """
    Returns a stable Wikimedia CDN audio URL for the word's pronunciation.
    Returns empty string if not found or on error.
    """
```

### Internal logic

1. Build candidate Wikimedia Commons filenames in preference order:
   - `en-us-{word}.ogg`  (US pronunciation — primary)
   - `en-{word}.ogg`     (generic)
   - `en-uk-{word}.ogg`  (UK pronunciation — fallback)

2. For each candidate, query the Wikimedia Commons API:
   ```
   GET https://commons.wikimedia.org/w/api.php
     ?action=query
     &titles=File:{filename}
     &prop=imageinfo
     &iiprop=url
     &format=json
   ```

3. On a hit (page ID is not `-1`), extract `imageinfo[0].url` and return it.

4. On miss or any exception: return `""`. Timeout is 5 seconds. No retries.

### Properties

- No auth, no API key
- No imports from other `ai_svc` modules
- Covered by a simple unit test (mock HTTP)

## Changes to `service.py`

### `_extract_pronunciation_data(self, entry, word)`

- Add `word: str` parameter (callers already have it in scope)
- After extracting `audio_url` from the API entry (logic unchanged), store it as
  `pronunciation_original` in the return dict
- Call `get_pronunciation_url(word)` from the new module
- Set `pronunciation` to: Wiktionary URL if non-empty, else `audio_url` (original fallback)

Return shape (unchanged externally):
```python
{
    "pronunciation": "<wiktionary_url_or_original>",
    "ipa": "<ipa_text>",
    "pronunciation_original": "<original_api_url>"  # internal, not surfaced in API response
}
```

Note: `pronunciation_original` is only used internally within `_extract_pronunciation_data`
and is not forwarded to the API response. The caller (`entries_info`) only reads
`pronunciation` and `ipa`.

### Call sites

Two places call `_extract_pronunciation_data`:
- `service.py:791` — already has `word` in scope, pass it through
- Any other call sites — same treatment

## Out of Scope

- Caching pronunciation URLs (can be added later)
- Supporting non-English languages
- Retrying on Wikimedia timeout
- Exposing `pronunciation_original` in the API response
