# Design: WOTD Translation Cache

**Date:** 2026-07-31
**Status:** Approved

## Problem

The WOTD page calls `POST /api/translate` on every page load to translate the word's example sentence into Chinese. This hits the DeepSeek LLM every time — incurring cost and ~1–2s latency — even though the word and its example sentence do not change throughout the day (or across the 180-day reuse window).

There is currently no caching layer for translations. The original translate API design explicitly left caching out of scope. This design adds WOTD-specific translation caching.

## Goal

- Cache the translated example sentence for each WOTD word in SQLite
- Serve subsequent requests from cache instantly at zero LLM cost
- Detect when the source example sentence changes and refresh the translation automatically
- Keep the general `/api/translate` endpoint unchanged and generic
- Design the new table and service to be extendable to other consumers in the future

## Architecture Overview

```
WOTD Frontend
  POST /api/wotd/translate  { word, target_lang }
    → WotdTranslateHandler (app.py)
        → DictionaryService: fetch current example sentence for word
        → WotdTranslationCacheService.get(word, target_lang, example)
            ├── HIT (example unchanged) → return cached translation
            └── MISS or example changed
                → TranslationService.translate(example, target_lang)
                → WotdTranslationCacheService.set(word, target_lang, example, translation)
                → return fresh translation
```

## Database

### Table: `wotd_translation_cache` (in existing `cache.db`)

```sql
CREATE TABLE IF NOT EXISTS wotd_translation_cache (
    word              TEXT NOT NULL,
    target_lang       TEXT NOT NULL,
    example_sentence  TEXT NOT NULL,
    translation       TEXT NOT NULL,
    created_at        INTEGER NOT NULL,
    last_accessed_at  INTEGER NOT NULL,
    PRIMARY KEY (word, target_lang)
);
```

**Key decisions:**

| Decision | Rationale |
|---|---|
| `(word, target_lang)` as primary key | Stable, human-readable, no hashing needed. One WOTD word maps to one translation per language. |
| `example_sentence` stored as column | Enables staleness detection: if the dictionary returns a different example for the same word, the cached translation is invalid and must be refreshed. |
| No `status` column | Translation is atomic — either cached or not. No `fetching`/`stale` lifecycle needed. |
| No TTL/expiry | WOTD example sentences don't change retroactively. Invalidation is driven by example sentence mismatch, not by time. |
| Lives in `cache.db` | Consistent with all other caching (word_cache, sense_cache, etc.). One DB to operate, back up, and vacuum. |

## Backend: `WotdTranslationCacheService`

**File:** `ai_svc/translation/wotd_cache_service.py`

Public interface:

```python
class WotdTranslationCacheService:
    def __init__(self, db_path: str): ...

    def get(self, word: str, target_lang: str, current_example: str) -> str | None:
        """Return cached translation if present and example matches. None otherwise."""

    def set(self, word: str, target_lang: str, example_sentence: str, translation: str) -> None:
        """Store or overwrite a translation for (word, target_lang)."""

    def invalidate(self, word: str, target_lang: str) -> None:
        """Delete cache entry. For admin/cache-clear use."""
```

**Staleness logic in `get()`:**
- If no row exists for `(word, target_lang)` → return `None` (cache miss)
- If row exists but `stored example_sentence != current_example` → return `None` (stale, triggers refresh)
- If row exists and example matches → update `last_accessed_at`, return `translation`

Follows the same WAL + `threading.Lock` + `BEGIN IMMEDIATE` pattern as `DictionaryCacheService` for write safety.

## Backend: New Endpoint `POST /api/wotd/translate`

**Registered in:** `app.py`

### Request

```
POST /api/wotd/translate
Content-Type: application/json
```

```json
{
  "word": "serendipity",
  "target_lang": "zh-cn"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `word` | string | yes | The WOTD word to translate the example for. |
| `target_lang` | string | yes | BCP-47 language tag (e.g. `zh-cn`, `ja`). |

### Response (success, HTTP 200)

```json
{
  "word": "serendipity",
  "target_lang": "zh-cn",
  "example_sentence": "It was a serendipity that they met.",
  "translation": "他们相遇是一种缘分。",
  "cache_status": "hit",
  "success": true
}
```

`cache_status` values:

| Value | Meaning |
|---|---|
| `"hit"` | Served from cache, no LLM call made |
| `"miss"` | No cache entry existed; LLM called and result cached |
| `"refreshed"` | Cache entry existed but example sentence changed; LLM called and cache updated |

### Response (validation error, HTTP 400)

```json
{
  "error": "Missing 'word' parameter in request body",
  "success": false
}
```

### Response (server error, HTTP 500)

```json
{
  "error": "Translation failed: <reason>",
  "success": false
}
```

### Handler logic (pseudocode)

```python
@app.route('/api/wotd/translate', methods=['POST'])
def wotd_translate():
    word = body.get('word', '').strip()
    target_lang = body.get('target_lang', '').strip()
    # 1. Validate inputs
    # 2. Fetch current example sentence via dictionary_service
    # 3. Check wotd_translation_cache_service.get(word, target_lang, example)
    # 4. On hit: return immediately with cache_status="hit"
    # 5. On miss/stale: call translation_service.translate(example, target_lang)
    # 6. wotd_translation_cache_service.set(word, target_lang, example, translation)
    # 7. Return with cache_status="miss" or "refreshed"
```

## Error Handling

| Condition | HTTP | Response |
|---|---|---|
| Missing `word` | 400 | `{"error": "Missing 'word' parameter", "success": false}` |
| Missing `target_lang` | 400 | `{"error": "Missing 'target_lang' parameter", "success": false}` |
| Empty `word` after strip | 400 | `{"error": "word cannot be empty", "success": false}` |
| Empty `target_lang` after strip | 400 | `{"error": "target_lang cannot be empty", "success": false}` |
| Dictionary returns no example | 500 | `{"error": "No example sentence found for word", "success": false}` |
| LLM translation fails | 500 | `{"error": "Translation failed: <msg>", "success": false}` |

## Frontend: WOTD Page Change

**File:** `clients/web/word-of-the-day/script.js`

The frontend switches from the generic translate endpoint to the new WOTD-specific one. Because the backend now fetches and returns the example sentence, the frontend no longer needs to fetch it separately — `loadWordOfTheDay()` simplifies.

```js
// Before
var TRANSLATE_URL = (configApiHost || '') + '/api/translate';
async function translateText(text, targetLang) { /* POST { text, target_lang } */ }
// caller fetches example first, then calls translateText(example, 'zh-cn')

// After
var WOTD_TRANSLATE_URL = (configApiHost || '') + '/api/wotd/translate';
async function translateWotd(word, targetLang) {
    var res = await fetch(WOTD_TRANSLATE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word, target_lang: targetLang })
    });
    var json = await res.json();
    if (!json.success) throw new Error(json.error || 'WOTD translate failed');
    return { example: json.example_sentence, translation: json.translation };
}
// loadWordOfTheDay() gets both example + translation from one call
```

## File Map

| File | Change |
|---|---|
| `ai_svc/translation/wotd_cache_service.py` | **Create** — `WotdTranslationCacheService` |
| `ai_svc/translation/__init__.py` | **Update** — export `WotdTranslationCacheService` |
| `app.py` | **Update** — instantiate service, add `POST /api/wotd/translate` route |
| `clients/web/word-of-the-day/script.js` | **Update** — switch to new endpoint, simplify example fetch |

The `cache.db` schema migration (CREATE TABLE IF NOT EXISTS) runs automatically on `WotdTranslationCacheService.__init__()`, consistent with how `DictionaryCacheService` initialises its tables.

## Out of Scope

- Cache admin/invalidation endpoints for WOTD translations (can add later)
- Proactive cache warming when the WOTD scheduler runs
- General-purpose translation caching for non-WOTD consumers
- Batch translation
- Source language detection
