# WOTD Translation Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `POST /api/wotd/translate` endpoint that caches WOTD example sentence translations in SQLite, eliminating repeated DeepSeek LLM calls for the same word.

**Architecture:** A new `WotdTranslationCacheService` reads/writes a `wotd_translation_cache` table in the existing `ai_svc/dictionary/cache.db`. The new endpoint fetches the word's example sentence via the existing dictionary service, checks the cache (validating that the stored example still matches), falls back to `TranslationService` on miss, and writes the result. The WOTD frontend switches from `POST /api/translate` to `POST /api/wotd/translate`, passing `word` instead of `text`.

**Tech Stack:** Python 3, Flask, SQLite3 (WAL mode), threading.Lock, vanilla JS (frontend)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `ai_svc/translation/wotd_cache_service.py` | **Create** | SQLite cache CRUD for WOTD translations |
| `ai_svc/translation/__init__.py` | **Update** | Export `WotdTranslationCacheService` |
| `app.py` | **Update** | Instantiate service, register `POST /api/wotd/translate` |
| `clients/web/word-of-the-day/script.js` | **Update** | Switch to new endpoint, remove separate example fetch |
| `tests/test_wotd_cache_service.py` | **Create** | Unit tests for cache service |
| `tests/test_wotd_translate_endpoint.py` | **Create** | Integration tests for the Flask endpoint |

---

## Task 1: Create `WotdTranslationCacheService`

**Files:**
- Create: `ai_svc/translation/wotd_cache_service.py`
- Create: `tests/test_wotd_cache_service.py`

### Step 1.1: Create the tests directory and write failing tests

```bash
mkdir -p /Users/jiali/personal_github_repos/PP-AI-Service/tests
```

Create `tests/test_wotd_cache_service.py`:

```python
"""Tests for WotdTranslationCacheService."""
import os
import time
import tempfile
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
```

- [ ] **Step 1.1:** Write the test file above to `tests/test_wotd_cache_service.py`

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/test_wotd_cache_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_svc.translation.wotd_cache_service'`

- [ ] **Step 1.3: Implement `WotdTranslationCacheService`**

Create `ai_svc/translation/wotd_cache_service.py`:

```python
"""
WOTD translation cache service.
Stores translated example sentences in SQLite, keyed by (word, target_lang).
Detects staleness by comparing the stored example sentence against the current one.
"""
import time
import sqlite3
import logging
import threading
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# Shared path: same cache.db used by DictionaryCacheService
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "dictionary" / "cache.db"


class WotdTranslationCacheService:
    """Cache for WOTD translated example sentences.

    Primary key: (word, target_lang)
    Staleness is detected by comparing the stored example_sentence
    against the current example returned by the dictionary service.
    """

    def __init__(self, db_path: str = None):
        self.db_path = str(db_path) if db_path else str(_DEFAULT_DB_PATH)
        self._write_lock = threading.Lock()
        self._init_db()
        logger.info(f"WotdTranslationCacheService initialized at {self.db_path}")

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wotd_translation_cache (
                    word              TEXT NOT NULL,
                    target_lang       TEXT NOT NULL,
                    example_sentence  TEXT NOT NULL,
                    translation       TEXT NOT NULL,
                    created_at        INTEGER NOT NULL,
                    last_accessed_at  INTEGER NOT NULL,
                    PRIMARY KEY (word, target_lang)
                )
            """)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _write_transaction(self):
        with self._write_lock:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"[wotd_cache] Transaction rollback: {e}")
                raise
            finally:
                conn.close()

    def _read_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, word: str, target_lang: str, current_example: str) -> Optional[str]:
        """Return the cached translation if present and the example matches.

        Returns None on cache miss or if the stored example sentence differs
        from current_example (stale — example changed upstream).
        Updates last_accessed_at on a hit.
        """
        conn = self._read_connection()
        try:
            row = conn.execute(
                "SELECT example_sentence, translation FROM wotd_translation_cache "
                "WHERE word = ? AND target_lang = ?",
                (word, target_lang)
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None
        if row["example_sentence"] != current_example:
            logger.info(f"[wotd_cache] Stale entry for '{word}' ({target_lang}): example changed")
            return None

        # Hit — update last_accessed_at asynchronously-safe via write lock
        now = int(time.time())
        with self._write_transaction() as conn:
            conn.execute(
                "UPDATE wotd_translation_cache SET last_accessed_at = ? "
                "WHERE word = ? AND target_lang = ?",
                (now, word, target_lang)
            )

        logger.info(f"[wotd_cache] Cache hit for '{word}' ({target_lang})")
        return row["translation"]

    def set(self, word: str, target_lang: str, example_sentence: str, translation: str) -> None:
        """Store or overwrite a translation for (word, target_lang)."""
        now = int(time.time())
        with self._write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO wotd_translation_cache
                    (word, target_lang, example_sentence, translation, created_at, last_accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(word, target_lang) DO UPDATE SET
                    example_sentence  = excluded.example_sentence,
                    translation       = excluded.translation,
                    last_accessed_at  = excluded.last_accessed_at
                """,
                (word, target_lang, example_sentence, translation, now, now)
            )
        logger.info(f"[wotd_cache] Cached translation for '{word}' ({target_lang})")

    def invalidate(self, word: str, target_lang: str) -> None:
        """Delete the cache entry for (word, target_lang). No-op if not present."""
        with self._write_transaction() as conn:
            conn.execute(
                "DELETE FROM wotd_translation_cache WHERE word = ? AND target_lang = ?",
                (word, target_lang)
            )
        logger.info(f"[wotd_cache] Invalidated '{word}' ({target_lang})")
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/test_wotd_cache_service.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 1.5: Commit**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
git add ai_svc/translation/wotd_cache_service.py tests/test_wotd_cache_service.py
git commit -m "feat: add WotdTranslationCacheService with SQLite-backed WOTD translation cache"
```

---

## Task 2: Export from `ai_svc/translation/__init__.py`

**Files:**
- Modify: `ai_svc/translation/__init__.py`

- [ ] **Step 2.1: Read the current `__init__.py`**

```bash
cat /Users/jiali/personal_github_repos/PP-AI-Service/ai_svc/translation/__init__.py
```

- [ ] **Step 2.2: Add the export**

The file is currently empty (created as a package marker). Replace its contents with:

```python
from .service import TranslationService
from .wotd_cache_service import WotdTranslationCacheService

__all__ = ["TranslationService", "WotdTranslationCacheService"]
```

- [ ] **Step 2.3: Verify import works**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -c "from ai_svc.translation import WotdTranslationCacheService; print('OK')"
```

Expected output: `OK`

- [ ] **Step 2.4: Commit**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
git add ai_svc/translation/__init__.py
git commit -m "feat: export WotdTranslationCacheService from ai_svc.translation"
```

---

## Task 3: Add `POST /api/wotd/translate` endpoint in `app.py`

**Files:**
- Modify: `app.py`
- Create: `tests/test_wotd_translate_endpoint.py`

### Step 3.1: Write failing endpoint tests

Create `tests/test_wotd_translate_endpoint.py`:

```python
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
```

- [ ] **Step 3.1:** Write the test file above to `tests/test_wotd_translate_endpoint.py`

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/test_wotd_translate_endpoint.py -v
```

Expected: Tests fail because `POST /api/wotd/translate` does not exist and `dictionary_service.get_example_for_word` does not exist yet.

### Step 3.3: Add `get_example_for_word` to `DictionaryService`

The endpoint needs a way to fetch a word's first example sentence. The WOTD frontend currently does this via two calls: the `basic` section (inline example from first sense), then falls back to the `examples` section. We need to encapsulate this logic server-side.

Open `ai_svc/dictionary/service.py` and add the following method to `DictionaryService`. Find the end of the class (before any module-level code) and add:

```python
def get_example_for_word(self, word: str) -> str:
    """Return the first available example sentence for a word.

    Tries the inline example from the first sense of the basic section first.
    Falls back to the dedicated examples section (entry 0, sense 0) if the
    inline example is missing.
    Returns an empty string if no example can be found.
    """
    try:
        basic_result = self.lookup_section(word, "basic", entry_index=0)
        if basic_result.get("success"):
            entries = basic_result.get("entries", [])
            if entries:
                entry = entries[0]
                meanings_summary = entry.get("meanings_summary", [])
                if meanings_summary:
                    first_summary = meanings_summary[0]
                    senses = first_summary.get("senses", [])
                    if senses and senses[0].get("example"):
                        return senses[0]["example"]
    except Exception as e:
        logger.warning(f"[get_example_for_word] basic section failed for '{word}': {e}")

    # Fallback: dedicated examples section
    try:
        examples_result = self.lookup_section(
            word, "examples", entry_index=0, sense_index=0
        )
        if examples_result.get("success"):
            examples = examples_result.get("examples", [])
            if examples and examples[0]:
                return examples[0]
    except Exception as e:
        logger.warning(f"[get_example_for_word] examples section failed for '{word}': {e}")

    return ""
```

- [ ] **Step 3.3:** Add the `get_example_for_word` method to `DictionaryService` in `ai_svc/dictionary/service.py`

### Step 3.4: Add the endpoint to `app.py`

Locate the section in `app.py` where `translation_service` is instantiated (search for `TranslationService()`). After that instantiation, add:

```python
from ai_svc.translation import WotdTranslationCacheService
wotd_translation_cache_service = WotdTranslationCacheService()
```

Then locate the `POST /api/translate` route handler and add the new route **after** it:

```python
@app.route('/api/wotd/translate', methods=['POST'])
def wotd_translate():
    """Translate the WOTD example sentence with SQLite caching.

    Request body: { "word": str, "target_lang": str }
    Response: {
        "word": str,
        "target_lang": str,
        "example_sentence": str,
        "translation": str,
        "cache_status": "hit" | "miss" | "refreshed",
        "success": true
    }
    """
    data = request.get_json(silent=True) or {}
    word = (data.get('word') or '').strip()
    target_lang = (data.get('target_lang') or '').strip()

    if not word:
        return jsonify({'error': "Missing or empty 'word' parameter", 'success': False}), 400
    if not target_lang:
        return jsonify({'error': "Missing or empty 'target_lang' parameter", 'success': False}), 400

    # Fetch current example sentence server-side
    example = dictionary_service.get_example_for_word(word)
    if not example:
        return jsonify({
            'error': f"No example sentence found for word '{word}'",
            'success': False
        }), 500

    # Check cache (validates that the stored example still matches)
    cached = wotd_translation_cache_service.get(word, target_lang, example)
    if cached is not None:
        return jsonify({
            'word': word,
            'target_lang': target_lang,
            'example_sentence': example,
            'translation': cached,
            'cache_status': 'hit',
            'success': True
        })

    # Cache miss or example changed — call LLM
    result = translation_service.translate(example, target_lang)
    if not result.get('success'):
        return jsonify({
            'error': f"Translation failed: {result.get('error', 'unknown error')}",
            'success': False
        }), 500

    translation = result['translation']

    # Determine cache_status: "refreshed" if there was a stale entry, "miss" if brand new
    # (The cache service already deleted/overwrote stale on get(); we just detect via existence)
    # Simple approach: always use "miss" for first write; if the example changed, use "refreshed"
    # We distinguish by checking if invalidate() had been called implicitly by get():
    # — get() returns None both for true miss and for stale (example changed). We check the DB.
    import sqlite3 as _sqlite3
    _conn = _sqlite3.connect(wotd_translation_cache_service.db_path)
    _row = _conn.execute(
        "SELECT 1 FROM wotd_translation_cache WHERE word=? AND target_lang=?",
        (word, target_lang)
    ).fetchone()
    _conn.close()
    cache_status = 'refreshed' if _row else 'miss'

    wotd_translation_cache_service.set(word, target_lang, example, translation)

    return jsonify({
        'word': word,
        'target_lang': target_lang,
        'example_sentence': example,
        'translation': translation,
        'cache_status': cache_status,
        'success': True
    })
```

- [ ] **Step 3.4:** Add the import + instantiation + route to `app.py` as described above.

- [ ] **Step 3.5: Run endpoint tests**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/test_wotd_translate_endpoint.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 3.6: Run all tests to check for regressions**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3.7: Commit**

```bash
cd /Users/jiali/personal_github_repos/PP-AI-Service
git add ai_svc/dictionary/service.py app.py tests/test_wotd_translate_endpoint.py
git commit -m "feat: add POST /api/wotd/translate endpoint with SQLite translation cache"
```

---

## Task 4: Update WOTD Frontend

**Files:**
- Modify: `clients/web/word-of-the-day/script.js` (in the `advanced-english-dictionary` repo)

- [ ] **Step 4.1: Replace the translate URL and function**

In `clients/web/word-of-the-day/script.js`, make the following changes:

**Change 1** — Replace line 7:
```js
// Before
var TRANSLATE_URL = (configApiHost || '') + '/api/translate';

// After
var WOTD_TRANSLATE_URL = (configApiHost || '') + '/api/wotd/translate';
```

**Change 2** — Replace the `translateText` function (lines 62–73) with `translateWotd`:
```js
// Before
async function translateText(text, targetLang) {
    if (!text) return '';
    var res = await fetch(TRANSLATE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ text: text, target_lang: targetLang })
    });
    if (!res.ok) throw new Error('Translate API returned ' + res.status);
    var json = await res.json();
    if (!json.success) throw new Error(json.error || 'Translate API error');
    return json.translation || '';
}

// After
async function translateWotd(word, targetLang) {
    var res = await fetch(WOTD_TRANSLATE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ word: word, target_lang: targetLang })
    });
    if (!res.ok) throw new Error('WOTD translate API returned ' + res.status);
    var json = await res.json();
    if (!json.success) throw new Error(json.error || 'WOTD translate API error');
    return { example: json.example_sentence || '', translation: json.translation || '' };
}
```

**Change 3** — Replace the end of `loadWordOfTheDay` (lines 173–190). The backend now fetches the example and returns it alongside the translation, so we remove the client-side example fetching:

```js
// Before (lines 173–190)
        const data = await fetchWordData(word);
        // Get the English example, translate it, then render
        currentData = data; // needed so getExample() can read it
        var englishExample = getExample();
        // If the first sense has no inline example, load the dedicated
        // examples section (as the main dictionary does) before rendering.
        if (!englishExample) {
            try {
                englishExample = await fetchFirstSenseExample(word);
            } catch (exErr) {
                console.warn('WOTD: failed to load examples section:', exErr);
            }
        }
        var translateResult = await Promise.allSettled([
            translateText(englishExample, 'zh-cn')
        ]);
        var exampleZh = (translateResult[0].status === 'fulfilled') ? translateResult[0].value : '';
        renderWord(data, englishExample, exampleZh);

// After
        const data = await fetchWordData(word);
        currentData = data;
        var englishExample = '';
        var exampleZh = '';
        var translateResult = await Promise.allSettled([
            translateWotd(word, 'zh-cn')
        ]);
        if (translateResult[0].status === 'fulfilled') {
            englishExample = translateResult[0].value.example;
            exampleZh = translateResult[0].value.translation;
        }
        renderWord(data, englishExample, exampleZh);
```

- [ ] **Step 4.1:** Apply the three changes above to `clients/web/word-of-the-day/script.js`

- [ ] **Step 4.2: Verify the page loads correctly**

Start the backend locally (if possible) and open the WOTD page in a browser. Verify:
- The English example sentence renders correctly
- The Chinese translation renders correctly
- Browser DevTools Network tab shows `POST /api/wotd/translate` being called (not `/api/translate`)
- On a second page load, the Network tab response shows `"cache_status": "hit"`

- [ ] **Step 4.3: Commit (frontend repo)**

```bash
cd /Users/jiali/personal_github_repos/advanced-english-dictionary
git add clients/web/word-of-the-day/script.js
git commit -m "feat: switch WOTD page to POST /api/wotd/translate (cached endpoint)"
```

---

## Self-Review

### Spec Coverage Check

| Spec requirement | Covered by |
|---|---|
| New table `wotd_translation_cache` in `cache.db` | Task 1 — `_init_db` creates the table |
| Primary key `(word, target_lang)` | Task 1 — table DDL |
| `example_sentence` column for staleness detection | Task 1 — table DDL + `get()` comparison |
| No TTL / time-based expiry | Task 1 — no TTL column or logic |
| `WotdTranslationCacheService` with `get/set/invalidate` | Task 1 |
| Export from `__init__.py` | Task 2 |
| `POST /api/wotd/translate` endpoint | Task 3 |
| Validation: missing/empty `word` → 400 | Task 3 — endpoint handler |
| Validation: missing/empty `target_lang` → 400 | Task 3 — endpoint handler |
| Fetch example server-side via dictionary service | Task 3 — `get_example_for_word` |
| No example found → 500 | Task 3 — endpoint handler |
| Cache hit → return immediately, `cache_status: "hit"` | Task 3 — endpoint handler |
| Cache miss → call LLM, write cache, `cache_status: "miss"` | Task 3 — endpoint handler |
| Example changed → `cache_status: "refreshed"` | Task 3 — endpoint handler |
| LLM failure → 500 | Task 3 — endpoint handler |
| Frontend switches to `/api/wotd/translate` | Task 4 |
| Frontend receives `example_sentence` + `translation` from one call | Task 4 |

All spec requirements covered. ✓

### Placeholder Scan

No TBDs, TODOs, or vague steps found. All steps include exact code or commands. ✓

### Type Consistency Check

- `WotdTranslationCacheService.get(word, target_lang, current_example)` → `Optional[str]` — consistent across Task 1 (definition) and Task 3 (call site: `cached = wotd_translation_cache_service.get(word, target_lang, example)`) ✓
- `WotdTranslationCacheService.set(word, target_lang, example_sentence, translation)` — consistent across Task 1 (definition) and Task 3 (call site + test assertions) ✓
- `dictionary_service.get_example_for_word(word)` → `str` — consistent across Task 3 (definition in service.py) and test mocks ✓
- `translateWotd()` returns `{ example, translation }` — consistent with Task 4 usage: `translateResult[0].value.example` / `.translation` ✓
