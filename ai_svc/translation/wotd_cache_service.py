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
from typing import Optional, Tuple

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

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
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

    def get_cached(self, word: str, target_lang: str) -> Optional[Tuple[str, str]]:
        """Return (example_sentence, translation) if an entry exists, without validation.

        Fast path: no dictionary call needed. Returns whatever is stored.
        Returns None if no entry exists for (word, target_lang).
        Updates last_accessed_at on hit.
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

        now = int(time.time())
        with self._write_transaction() as conn:
            conn.execute(
                "UPDATE wotd_translation_cache SET last_accessed_at = ? "
                "WHERE word = ? AND target_lang = ?",
                (now, word, target_lang)
            )

        logger.info(f"[wotd_cache] Fast cache hit for '{word}' ({target_lang})")
        return (row["example_sentence"], row["translation"])

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
