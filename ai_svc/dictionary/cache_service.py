"""
SQLite-based caching service for dictionary lookups
Implements field-level granularity, partial caching, and stale-while-revalidate patterns
Based on production patterns from OpenAI Agents, Kolibri, and Roampal
"""
import sqlite3
import json
import time
import threading
import math
import logging
from typing import Dict, Any, Optional, List, Tuple
from contextlib import contextmanager
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)


class CacheMetrics:
    """Thread-safe cache metrics tracker"""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'cache_partial': 0,
            'cache_stale': 0,
            'api_calls': 0,
            'ai_calls': 0,
            'refresh_count': 0,
        }
        self.response_times = []
    
    def record_hit(self, response_time: float):
        with self.lock:
            self.metrics['cache_hits'] += 1
            self.response_times.append(response_time)
    
    def record_miss(self, response_time: float, source: str):
        with self.lock:
            self.metrics['cache_misses'] += 1
            if source == 'api':
                self.metrics['api_calls'] += 1
            elif source == 'ai':
                self.metrics['ai_calls'] += 1
            self.response_times.append(response_time)
    
    def record_stale(self):
        with self.lock:
            self.metrics['cache_stale'] += 1
    
    def record_partial(self):
        with self.lock:
            self.metrics['cache_partial'] += 1
    
    def record_refresh(self):
        with self.lock:
            self.metrics['refresh_count'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            total = self.metrics['cache_hits'] + self.metrics['cache_misses']
            hit_rate = self.metrics['cache_hits'] / total if total > 0 else 0
            
            avg_time = sum(self.response_times) / len(self.response_times) if self.response_times else 0
            
            return {
                **self.metrics,
                'cache_hit_rate': round(hit_rate, 3),
                'cache_miss_rate': round(1 - hit_rate, 3),
                'total_requests': total,
                'avg_response_time_ms': round(avg_time * 1000, 2),
            }


class DictionaryCacheService:
    """
    Production-ready SQLite cache with field-level granularity and partial caching
    
    Features:
    - WAL mode for concurrent reads
    - BEGIN IMMEDIATE for write safety
    - Per-field TTLs and status tracking
    - Stale-while-revalidate pattern
    - Background refresh via ThreadPoolExecutor
    - Comprehensive metrics tracking
    """
    
    # TTL values (seconds) based on content stability research
    FIELD_TTL = {
        'basic': 7 * 24 * 3600,           # 7 days (API data, stable)
        'common_phrases': 30 * 24 * 3600,  # 30 days (phrases are stable like word_family)
        'etymology': 30 * 24 * 3600,       # 30 days (linguistic, very stable)
        'word_family': 30 * 24 * 3600,     # 30 days
        'usage_context': 7 * 24 * 3600,    # 7 days (modern usage evolves)
        'cultural_notes': 14 * 24 * 3600,  # 14 days
        'frequency': 30 * 24 * 3600,       # 30 days
        'detailed_sense': 14 * 24 * 3600,  # 14 days
        'examples': 7 * 24 * 3600,         # 7 days
        'usage_notes': 7 * 24 * 3600,      # 7 days
        'bilibili_videos': 1 * 24 * 3600,  # 1 day (videos change frequently)
    }
    
    def __init__(self, db_path: str = None):
        """
        Initialize cache service with SQLite database
        
        Args:
            db_path: Path to SQLite database file. Defaults to ai_svc/dictionary/cache.db
        """
        if db_path is None:
            # Default to ai_svc/dictionary/cache.db
            db_path = Path(__file__).parent / "cache.db"
        
        self.db_path = str(db_path)
        self._write_lock = threading.Lock()
        self._inflight_requests = {}  # Track in-flight requests to prevent duplicates
        self._inflight_lock = threading.Lock()  # Protect _inflight_requests dict
        self.metrics = CacheMetrics()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache_refresh")
        
        self._init_db()
        logger.info(f"Dictionary cache initialized at {self.db_path}")
    
    def _init_db(self):
        """Initialize database with optimized settings and schema"""
        with sqlite3.connect(self.db_path) as conn:
            # Enable WAL mode for concurrent reads (OpenAI Agents pattern)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA busy_timeout=5000")  # 5 second timeout
            conn.execute("PRAGMA foreign_keys=ON")  # Enable foreign keys
            
            # Create schema
            self._create_schema(conn)
            
            logger.info("Cache database schema initialized with WAL mode")
    
    def _create_schema(self, conn: sqlite3.Connection):
        """Create cache tables with field-level granularity"""
        
        # Core word cache
        conn.execute("""
            CREATE TABLE IF NOT EXISTS word_cache (
                word TEXT PRIMARY KEY,
                normalized_word TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_accessed_at INTEGER NOT NULL,
                access_count INTEGER DEFAULT 1,
                
                basic_data TEXT,
                basic_updated_at INTEGER,
                basic_status TEXT DEFAULT 'empty' CHECK(basic_status IN ('empty', 'fetching', 'fresh', 'stale', 'failed')),
                
                common_phrases_data TEXT,
                common_phrases_updated_at INTEGER,
                common_phrases_status TEXT DEFAULT 'empty' CHECK(common_phrases_status IN ('empty', 'fetching', 'fresh', 'stale', 'failed')),
                
                api_success BOOLEAN DEFAULT TRUE,
                api_last_attempt INTEGER,
                total_entries INTEGER
            )
        """)
        
        # Entry-level sections
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entry_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                entry_index INTEGER NOT NULL,
                
                etymology_data TEXT,
                etymology_updated_at INTEGER,
                etymology_status TEXT DEFAULT 'empty',
                
                word_family_data TEXT,
                word_family_updated_at INTEGER,
                word_family_status TEXT DEFAULT 'empty',
                
                usage_context_data TEXT,
                usage_context_updated_at INTEGER,
                usage_context_status TEXT DEFAULT 'empty',
                
                cultural_notes_data TEXT,
                cultural_notes_updated_at INTEGER,
                cultural_notes_status TEXT DEFAULT 'empty',
                
                frequency_data TEXT,
                frequency_updated_at INTEGER,
                frequency_status TEXT DEFAULT 'empty',
                
                bilibili_videos_data TEXT,
                bilibili_videos_updated_at INTEGER,
                bilibili_videos_status TEXT DEFAULT 'empty',
                
                UNIQUE(word, entry_index),
                FOREIGN KEY (word) REFERENCES word_cache(word) ON DELETE CASCADE
            )
        """)
        
        # Sense-level sections
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sense_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                entry_index INTEGER NOT NULL,
                sense_index INTEGER NOT NULL,
                
                detailed_sense_data TEXT,
                detailed_sense_updated_at INTEGER,
                detailed_sense_status TEXT DEFAULT 'empty',
                
                examples_data TEXT,
                examples_updated_at INTEGER,
                examples_status TEXT DEFAULT 'empty',
                
                usage_notes_data TEXT,
                usage_notes_updated_at INTEGER,
                usage_notes_status TEXT DEFAULT 'empty',
                
                UNIQUE(word, entry_index, sense_index),
                FOREIGN KEY (word) REFERENCES word_cache(word) ON DELETE CASCADE
            )
        """)
        
        # Phrase-level cache (for phrase-specific videos)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phrase_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                phrase TEXT NOT NULL,
                
                bilibili_videos_data TEXT,
                bilibili_videos_updated_at INTEGER,
                bilibili_videos_status TEXT DEFAULT 'empty',
                
                created_at INTEGER NOT NULL,
                last_accessed_at INTEGER NOT NULL,
                
                UNIQUE(word, phrase),
                FOREIGN KEY (word) REFERENCES word_cache(word) ON DELETE CASCADE
            )
        """)
        
        # AI-generated phrase video cache (links to video_tasks.db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_phrase_video_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                phrase TEXT NOT NULL,
                conversation_script TEXT,
                style TEXT NOT NULL,
                duration INTEGER NOT NULL,
                resolution TEXT NOT NULL,
                ratio TEXT NOT NULL,
                
                task_id TEXT NOT NULL,
                video_url TEXT,
                status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
                
                created_at INTEGER NOT NULL,
                last_accessed_at INTEGER NOT NULL,
                completed_at INTEGER,
                
                UNIQUE(word, phrase, style, duration, resolution, ratio),
                FOREIGN KEY (word) REFERENCES word_cache(word) ON DELETE CASCADE
            )
        """)
        
        # User feedback (future extensibility)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_type TEXT NOT NULL CHECK(content_type IN ('definition', 'etymology', 'video', 'example')),
                word TEXT NOT NULL,
                entry_index INTEGER,
                sense_index INTEGER,
                section_type TEXT NOT NULL,
                rating TEXT NOT NULL CHECK(rating IN ('like', 'dislike', 'outdated')),
                feedback_text TEXT,
                user_id TEXT,
                submitted_at INTEGER NOT NULL,
                
                FOREIGN KEY (word) REFERENCES word_cache(word) ON DELETE CASCADE
            )
        """)
        
        # Cache metrics
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                metric_type TEXT NOT NULL CHECK(metric_type IN ('hit', 'miss', 'partial', 'stale', 'refresh')),
                word TEXT NOT NULL,
                section_type TEXT,
                response_time_ms REAL,
                source TEXT CHECK(source IN ('cache', 'api', 'ai', 'hybrid')),
                metadata TEXT
            )
        """)
        
        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entry_cache_word ON entry_cache(word)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sense_cache_word_entry ON sense_cache(word, entry_index)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_phrase_cache_word_phrase ON phrase_cache(word, phrase)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_phrase_video_cache_word_phrase ON ai_phrase_video_cache(word, phrase)")
        
        try:
            conn.execute("SELECT conversation_script FROM ai_phrase_video_cache LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating database: adding conversation_script column to ai_phrase_video_cache")
            conn.execute("ALTER TABLE ai_phrase_video_cache ADD COLUMN conversation_script TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_phrase_video_cache_task_id ON ai_phrase_video_cache(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_word ON user_feedback(word, section_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON cache_metrics(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_word_cache_accessed ON word_cache(last_accessed_at)")
        
        # Migration: Add common_phrases columns if they don't exist (for existing databases)
        self._migrate_add_common_phrases_columns(conn)
        
        conn.commit()
    
    def _migrate_add_common_phrases_columns(self, conn: sqlite3.Connection):
        try:
            cursor = conn.execute("PRAGMA table_info(word_cache)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'common_phrases_data' not in columns:
                logger.info("Migrating database: adding common_phrases columns...")
                conn.execute("""
                    ALTER TABLE word_cache 
                    ADD COLUMN common_phrases_data TEXT
                """)
                conn.execute("""
                    ALTER TABLE word_cache 
                    ADD COLUMN common_phrases_updated_at INTEGER
                """)
                conn.execute("""
                    ALTER TABLE word_cache 
                    ADD COLUMN common_phrases_status TEXT DEFAULT 'empty'
                """)
                logger.info("Migration complete: common_phrases columns added")
        except Exception as e:
            logger.warning(f"Migration warning (may be expected): {e}")
    
    
    def _make_cache_key(self, word: str, section: str, entry_index: int = None, sense_index: int = None) -> str:
        """Generate unique cache key for tracking in-flight requests"""
        if section == 'basic':
            return f"{word}:basic"
        elif section == 'common_phrases':
            return f"{word}:common_phrases"
        elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']:
            return f"{word}:entry:{entry_index}:{section}"
        else:
            return f"{word}:sense:{entry_index}:{sense_index}:{section}"
    
    def mark_inflight(self, cache_key: str) -> bool:
        """
        Mark a request as in-flight. Returns True if successfully marked,
        False if already in-flight (duplicate request).
        """
        with self._inflight_lock:
            if cache_key in self._inflight_requests:
                logger.debug(f"Request already in-flight: {cache_key}")
                return False
            self._inflight_requests[cache_key] = time.time()
            return True
    
    def clear_inflight(self, cache_key: str):
        """Clear in-flight marker after request completes"""
        with self._inflight_lock:
            self._inflight_requests.pop(cache_key, None)
    @contextmanager
    def _write_transaction(self):
        """
        Safe write transaction with IMMEDIATE lock (Kolibri/AutoForge pattern)
        Prevents SQLITE_BUSY errors in concurrent environments
        """
        with self._write_lock:  # Python-level lock first
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("BEGIN IMMEDIATE")  # Acquire SQLite write lock immediately
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Transaction rollback: {e}")
                raise
            finally:
                conn.close()
    
    def _read_connection(self) -> sqlite3.Connection:
        """Create read-only connection (safe for concurrent reads with WAL mode)"""
        conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _normalize_word(self, word: str) -> str:
        """Normalize word for consistent cache keys (matches service.py logic)"""
        return word.strip().lower()
    
    def _is_stale(self, updated_at: Optional[int], section: str) -> bool:
        """Check if cached data has exceeded TTL"""
        if updated_at is None:
            return True
        
        ttl = self.FIELD_TTL.get(section, 7 * 24 * 3600)
        age = time.time() - updated_at
        return age > ttl
    
    def get_basic(self, word: str) -> Optional[Dict[str, Any]]:
        """
        Get cached basic section data
        
        Returns:
            Dict with 'data', 'is_stale', 'cache_hit' keys, or None if not cached
        """
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            row = conn.execute("""
                SELECT basic_data, basic_updated_at, basic_status
                FROM word_cache
                WHERE word = ?
            """, (normalized,)).fetchone()
            
            if not row:
                return None
            
            if not row['basic_data'] or row['basic_status'] not in ('fresh', 'stale'):
                return None
            
            is_stale = self._is_stale(row['basic_updated_at'], 'basic')
            
            return {
                'data': json.loads(row['basic_data']),
                'updated_at': row['basic_updated_at'],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()
    
    def get_entry_section(self, word: str, entry_index: int, section: str) -> Optional[Dict[str, Any]]:
        """
        Get cached entry-level section (etymology, word_family, etc.)
        
        Args:
            word: Dictionary word
            entry_index: Entry index (0-based)
            section: Section name ('etymology', 'word_family', etc.)
        
        Returns:
            Dict with cached data or None
        """
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            data_col = f"{section}_data"
            time_col = f"{section}_updated_at"
            status_col = f"{section}_status"
            
            row = conn.execute(f"""
                SELECT {data_col}, {time_col}, {status_col}
                FROM entry_cache
                WHERE word = ? AND entry_index = ?
            """, (normalized, entry_index)).fetchone()
            
            if not row:
                return None
            
            if not row[data_col] or row[status_col] not in ('fresh', 'stale'):
                return None
            
            is_stale = self._is_stale(row[time_col], section)
            
            return {
                'data': json.loads(row[data_col]),
                'updated_at': row[time_col],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()
    
    def get_sense_section(self, word: str, entry_index: int, sense_index: int, section: str) -> Optional[Dict[str, Any]]:
        """
        Get cached sense-level section (detailed_sense, examples, usage_notes)
        
        Args:
            word: Dictionary word
            entry_index: Entry index (0-based)
            sense_index: Sense index (0-based)
            section: Section name ('detailed_sense', 'examples', 'usage_notes')
        
        Returns:
            Dict with cached data or None
        """
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            data_col = f"{section}_data"
            time_col = f"{section}_updated_at"
            status_col = f"{section}_status"
            
            row = conn.execute(f"""
                SELECT {data_col}, {time_col}, {status_col}
                FROM sense_cache
                WHERE word = ? AND entry_index = ? AND sense_index = ?
            """, (normalized, entry_index, sense_index)).fetchone()
            
            if not row:
                return None
            
            if not row[data_col] or row[status_col] not in ('fresh', 'stale'):
                return None
            
            is_stale = self._is_stale(row[time_col], section)
            
            return {
                'data': json.loads(row[data_col]),
                'updated_at': row[time_col],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()
    
    def set_basic(self, word: str, data: Dict[str, Any], status: str = 'fresh'):
        """Cache basic section data"""
        normalized = self._normalize_word(word)
        now = int(time.time())
        
        with self._write_transaction() as conn:
            conn.execute("""
                INSERT INTO word_cache (
                    word, normalized_word, basic_data, basic_updated_at, basic_status,
                    created_at, last_accessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    basic_data = excluded.basic_data,
                    basic_updated_at = excluded.basic_updated_at,
                    basic_status = excluded.basic_status,
                    last_accessed_at = excluded.last_accessed_at
            """, (normalized, normalized, json.dumps(data), now, status, now, now))
        
        logger.info(f"[{word}] Cached 'basic' section - status: {status}")
    
    def get_common_phrases(self, word: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            row = conn.execute("""
                SELECT common_phrases_data, common_phrases_updated_at, common_phrases_status
                FROM word_cache
                WHERE word = ?
            """, (normalized,)).fetchone()
            
            if not row:
                return None
            
            if not row['common_phrases_data'] or row['common_phrases_status'] not in ('fresh', 'stale'):
                return None
            
            is_stale = self._is_stale(row['common_phrases_updated_at'], 'common_phrases')
            
            return {
                'data': json.loads(row['common_phrases_data']),
                'updated_at': row['common_phrases_updated_at'],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()
    
    def set_common_phrases(self, word: str, data: Dict[str, Any], status: str = 'fresh'):
        normalized = self._normalize_word(word)
        now = int(time.time())
        
        with self._write_transaction() as conn:
            conn.execute("""
                INSERT INTO word_cache (
                    word, normalized_word, common_phrases_data, common_phrases_updated_at, common_phrases_status,
                    created_at, last_accessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    common_phrases_data = excluded.common_phrases_data,
                    common_phrases_updated_at = excluded.common_phrases_updated_at,
                    common_phrases_status = excluded.common_phrases_status,
                    last_accessed_at = excluded.last_accessed_at
            """, (normalized, normalized, json.dumps(data), now, status, now, now))
        
        logger.info(f"[{word}] Cached 'common_phrases' section - status: {status}")
    
    def get_phrase_videos(self, word: str, phrase: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            row = conn.execute("""
                SELECT bilibili_videos_data, bilibili_videos_updated_at, bilibili_videos_status
                FROM phrase_cache
                WHERE word = ? AND phrase = ?
            """, (normalized, phrase)).fetchone()
            
            if not row:
                return None
            
            if not row['bilibili_videos_data'] or row['bilibili_videos_status'] not in ('fresh', 'stale'):
                return None
            
            is_stale = self._is_stale(row['bilibili_videos_updated_at'], 'bilibili_videos')
            
            return {
                'data': json.loads(row['bilibili_videos_data']),
                'updated_at': row['bilibili_videos_updated_at'],
                'is_stale': is_stale,
                'cache_hit': True
            }
        finally:
            conn.close()
    
    def set_phrase_videos(self, word: str, phrase: str, data: Dict[str, Any], status: str = 'fresh'):
        normalized = self._normalize_word(word)
        now = int(time.time())
        
        with self._write_transaction() as conn:
            conn.execute("""
                INSERT INTO phrase_cache (
                    word, phrase, bilibili_videos_data, bilibili_videos_updated_at, bilibili_videos_status,
                    created_at, last_accessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(word, phrase) DO UPDATE SET
                    bilibili_videos_data = excluded.bilibili_videos_data,
                    bilibili_videos_updated_at = excluded.bilibili_videos_updated_at,
                    bilibili_videos_status = excluded.bilibili_videos_status,
                    last_accessed_at = excluded.last_accessed_at
            """, (normalized, phrase, json.dumps(data), now, status, now, now))
        
        logger.info(f"[{word}] Cached phrase '{phrase}' videos - status: {status}")
    
    def get_ai_phrase_video(
        self,
        word: str,
        phrase: str,
        style: str = "kids_cartoon",
        duration: int = 4,
        resolution: str = "480p",
        ratio: str = "16:9"
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            row = conn.execute("""
                SELECT task_id, video_url, status, created_at, completed_at
                FROM ai_phrase_video_cache
                WHERE word = ? AND phrase = ? AND style = ? AND duration = ? AND resolution = ? AND ratio = ?
            """, (normalized, phrase, style, duration, resolution, ratio)).fetchone()
            
            if not row:
                return None
            
            conn.execute("""
                UPDATE ai_phrase_video_cache
                SET last_accessed_at = ?
                WHERE word = ? AND phrase = ? AND style = ? AND duration = ? AND resolution = ? AND ratio = ?
            """, (int(time.time()), normalized, phrase, style, duration, resolution, ratio))
            conn.commit()
            
            return {
                'task_id': row['task_id'],
                'video_url': row['video_url'],
                'status': row['status'],
                'created_at': row['created_at'],
                'completed_at': row['completed_at'],
                'cache_hit': True
            }
        finally:
            conn.close()
    
    def set_ai_phrase_video(
        self,
        word: str,
        phrase: str,
        task_id: str,
        conversation_script: Optional[Dict[str, Any]] = None,
        style: str = "kids_cartoon",
        duration: int = 4,
        resolution: str = "480p",
        ratio: str = "16:9",
        video_url: Optional[str] = None,
        status: str = "pending"
    ):
        import json
        
        normalized = self._normalize_word(word)
        now = int(time.time())
        
        conversation_json = json.dumps(conversation_script) if conversation_script else None
        
        with self._write_transaction() as conn:
            conn.execute("""
                INSERT INTO ai_phrase_video_cache (
                    word, phrase, conversation_script, style, duration, resolution, ratio,
                    task_id, video_url, status, created_at, last_accessed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(word, phrase, style, duration, resolution, ratio) DO UPDATE SET
                    conversation_script = excluded.conversation_script,
                    task_id = excluded.task_id,
                    video_url = excluded.video_url,
                    status = excluded.status,
                    last_accessed_at = excluded.last_accessed_at
            """, (normalized, phrase, conversation_json, style, duration, resolution, ratio, task_id, video_url, status, now, now))
        
        logger.info(f"[{word}] Cached AI phrase video task '{phrase}' with conversation script - task_id: {task_id}, status: {status}")
    
    def update_ai_phrase_video_status(
        self,
        task_id: str,
        status: str,
        video_url: Optional[str] = None
    ):
        now = int(time.time())
        
        with self._write_transaction() as conn:
            if status in ('completed', 'failed'):
                conn.execute("""
                    UPDATE ai_phrase_video_cache
                    SET status = ?, video_url = ?, completed_at = ?, last_accessed_at = ?
                    WHERE task_id = ?
                """, (status, video_url, now, now, task_id))
            else:
                conn.execute("""
                    UPDATE ai_phrase_video_cache
                    SET status = ?, video_url = ?, last_accessed_at = ?
                    WHERE task_id = ?
                """, (status, video_url, now, task_id))
        
        logger.info(f"Updated AI phrase video task {task_id} - status: {status}")
    
    def list_ai_phrase_videos(
        self,
        word: str,
        phrase: str,
        status_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        List all AI-generated videos for a specific phrase
        
        Args:
            word: The word being looked up
            phrase: The phrase to filter by
            status_filter: Optional list of statuses to filter by (e.g., ['completed'], ['processing', 'pending'])
                          If None, returns all videos regardless of status
        
        Returns:
            List of video dictionaries with task_id, status, parameters, timestamps
            Sorted by created_at DESC (newest first)
        """
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            if status_filter:
                placeholders = ', '.join(['?' for _ in status_filter])
                query = f"""
                    SELECT task_id, video_url, status, style, duration, resolution, ratio,
                           created_at, completed_at, last_accessed_at
                    FROM ai_phrase_video_cache
                    WHERE word = ? AND phrase = ? AND status IN ({placeholders})
                    ORDER BY created_at DESC
                """
                params = [normalized, phrase] + status_filter
            else:
                query = """
                    SELECT task_id, video_url, status, style, duration, resolution, ratio,
                           created_at, completed_at, last_accessed_at
                    FROM ai_phrase_video_cache
                    WHERE word = ? AND phrase = ?
                    ORDER BY created_at DESC
                """
                params = [normalized, phrase]
            
            rows = conn.execute(query, params).fetchall()
            
            results = []
            for row in rows:
                results.append({
                    'task_id': row['task_id'],
                    'video_url': row['video_url'],
                    'status': row['status'],
                    'style': row['style'],
                    'duration': row['duration'],
                    'resolution': row['resolution'],
                    'ratio': row['ratio'],
                    'created_at': row['created_at'],
                    'completed_at': row['completed_at'],
                    'last_accessed_at': row['last_accessed_at']
                })
            
            if results:
                conn.execute("""
                    UPDATE ai_phrase_video_cache
                    SET last_accessed_at = ?
                    WHERE word = ? AND phrase = ?
                """, (int(time.time()), normalized, phrase))
                conn.commit()
            
            logger.info(f"[{word}] Listed {len(results)} AI videos for phrase '{phrase}' (status_filter={status_filter})")
            return results
            
        finally:
            conn.close()
    
    def set_entry_section(self, word: str, entry_index: int, section: str, data: Dict[str, Any], status: str = 'fresh'):
        """Cache entry-level section data"""
        normalized = self._normalize_word(word)
        now = int(time.time())
        
        with self._write_transaction() as conn:
            data_col = f"{section}_data"
            time_col = f"{section}_updated_at"
            status_col = f"{section}_status"
            
            # Upsert pattern
            conn.execute(f"""
                INSERT INTO entry_cache (word, entry_index, {data_col}, {time_col}, {status_col})
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(word, entry_index) DO UPDATE SET
                    {data_col} = excluded.{data_col},
                    {time_col} = excluded.{time_col},
                    {status_col} = excluded.{status_col}
            """, (normalized, entry_index, json.dumps(data), now, status))
        
        logger.info(f"[{word}] Cached '{section}' (entry {entry_index}) - status: {status}")
    
    def set_sense_section(self, word: str, entry_index: int, sense_index: int, section: str, data: Dict[str, Any], status: str = 'fresh'):
        """Cache sense-level section data"""
        normalized = self._normalize_word(word)
        now = int(time.time())
        
        with self._write_transaction() as conn:
            data_col = f"{section}_data"
            time_col = f"{section}_updated_at"
            status_col = f"{section}_status"
            
            conn.execute(f"""
                INSERT INTO sense_cache (word, entry_index, sense_index, {data_col}, {time_col}, {status_col})
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(word, entry_index, sense_index) DO UPDATE SET
                    {data_col} = excluded.{data_col},
                    {time_col} = excluded.{time_col},
                    {status_col} = excluded.{status_col}
            """, (normalized, entry_index, sense_index, json.dumps(data), now, status))
        
        logger.info(f"[{word}] Cached '{section}' (entry {entry_index}, sense {sense_index}) - status: {status}")
    
    def track_metric(self, metric_type: str, word: str, section_type: str = None, response_time_ms: float = None, source: str = None):
        """Record cache metric to database"""
        now = int(time.time())
        
        try:
            with self._write_transaction() as conn:
                conn.execute("""
                    INSERT INTO cache_metrics (timestamp, metric_type, word, section_type, response_time_ms, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (now, metric_type, word, section_type, response_time_ms, source))
        except Exception as e:
            logger.warning(f"Failed to track metric: {e}")
    
    def cleanup_old_entries(self, max_age_days: int = 90):
        """Remove cache entries not accessed in max_age_days"""
        cutoff = int(time.time()) - (max_age_days * 24 * 3600)
        
        with self._write_transaction() as conn:
            result = conn.execute("""
                DELETE FROM word_cache
                WHERE last_accessed_at < ?
            """, (cutoff,))
            
            deleted = result.rowcount
            logger.info(f"Cleaned up {deleted} old cache entries (older than {max_age_days} days)")
            return deleted
    
    
    def clear_all(self):
        """Clear all cache entries"""
        with self._write_transaction() as conn:
            conn.execute("DELETE FROM sense_cache")
            conn.execute("DELETE FROM entry_cache")
            conn.execute("DELETE FROM phrase_cache")
            conn.execute("DELETE FROM ai_phrase_video_cache")
            conn.execute("DELETE FROM word_cache")
            conn.execute("DELETE FROM cache_metrics")
            logger.info("All cache entries and metrics cleared")
    
    def invalidate_word(self, word: str):
        """Invalidate all cache entries for a specific word"""
        with self._write_transaction() as conn:
            conn.execute("DELETE FROM sense_cache WHERE word = ?", (word,))
            conn.execute("DELETE FROM entry_cache WHERE word = ?", (word,))
            conn.execute("DELETE FROM phrase_cache WHERE word = ?", (word,))
            conn.execute("DELETE FROM ai_phrase_video_cache WHERE word = ?", (word,))
            conn.execute("DELETE FROM word_cache WHERE word = ?", (word,))
            logger.info(f"Cache invalidated for word: {word}")
    
    def invalidate_word_section(self, word: str, section: str, entry_index: int = None, sense_index: int = None):
        """
        Invalidate specific section cache for a word
        
        Args:
            word: Word to invalidate
            section: Section name to invalidate
            entry_index: Entry index (for entry-level sections)
            sense_index: Sense index (for sense-level sections)
        """
        normalized = self._normalize_word(word)
        
        with self._write_transaction() as conn:
            if section == 'basic':
                # Clear basic section only
                conn.execute("""
                    UPDATE word_cache
                    SET basic_data = NULL, basic_updated_at = NULL, basic_status = 'empty'
                    WHERE word = ?
                """, (normalized,))
                logger.info(f"Cache invalidated: {word} - basic")
                
            elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']:
                # Entry-level section
                data_col = f"{section}_data"
                time_col = f"{section}_updated_at"
                status_col = f"{section}_status"
                
                if entry_index is not None:
                    conn.execute(f"""
                        UPDATE entry_cache
                        SET {data_col} = NULL, {time_col} = NULL, {status_col} = 'empty'
                        WHERE word = ? AND entry_index = ?
                    """, (normalized, entry_index))
                    logger.info(f"Cache invalidated: {word} - {section} (entry {entry_index})")
                else:
                    # Clear for all entries
                    conn.execute(f"""
                        UPDATE entry_cache
                        SET {data_col} = NULL, {time_col} = NULL, {status_col} = 'empty'
                        WHERE word = ?
                    """, (normalized,))
                    logger.info(f"Cache invalidated: {word} - {section} (all entries)")
            
            elif section == 'common_phrases':
                # Word-level section (separate from basic)
                conn.execute("""
                    UPDATE word_cache
                    SET common_phrases_data = NULL, common_phrases_updated_at = NULL, 
                        common_phrases_status = 'empty'
                    WHERE word = ?
                """, (normalized,))
                logger.info(f"Cache invalidated: {word} - {section}")
                    
            elif section in ['detailed_sense', 'examples', 'usage_notes']:
                # Sense-level section
                data_col = f"{section}_data"
                time_col = f"{section}_updated_at"
                status_col = f"{section}_status"
                
                if entry_index is not None and sense_index is not None:
                    conn.execute(f"""
                        UPDATE sense_cache
                        SET {data_col} = NULL, {time_col} = NULL, {status_col} = 'empty'
                        WHERE word = ? AND entry_index = ? AND sense_index = ?
                    """, (normalized, entry_index, sense_index))
                    logger.info(f"Cache invalidated: {word} - {section} (entry {entry_index}, sense {sense_index})")
                else:
                    # Clear for all entries/senses
                    conn.execute(f"""
                        UPDATE sense_cache
                        SET {data_col} = NULL, {time_col} = NULL, {status_col} = 'empty'
                        WHERE word = ?
                    """, (normalized,))
                    logger.info(f"Cache invalidated: {word} - {section} (all entries/senses)")
    
    def list_cached_words(self, limit: int = 100, offset: int = 0, sort_by: str = 'last_accessed') -> Dict[str, Any]:
        """
        List all cached words with their section information
        
        Args:
            limit: Maximum number of words to return
            offset: Pagination offset
            sort_by: Sort field ('last_accessed', 'word', 'created_at')
        
        Returns:
            Dict with words list and pagination info
        """
        conn = self._read_connection()
        
        try:
            # Validate sort_by
            valid_sorts = {'last_accessed': 'last_accessed_at', 'word': 'word', 'created_at': 'created_at'}
            sort_col = valid_sorts.get(sort_by, 'last_accessed_at')
            
            # Get total count
            total = conn.execute("SELECT COUNT(*) FROM word_cache").fetchone()[0]
            
            # Get words with basic info
            words_query = f"""
                SELECT 
                    word,
                    basic_status,
                    datetime(created_at, 'unixepoch', 'localtime') as created_at,
                    datetime(last_accessed_at, 'unixepoch', 'localtime') as last_accessed_at
                FROM word_cache
                ORDER BY {sort_col} DESC
                LIMIT ? OFFSET ?
            """
            
            words = []
            for row in conn.execute(words_query, (limit, offset)):
                word = row['word']
                
                # Get entry-level sections for this word
                entry_sections = conn.execute("""
                    SELECT 
                        entry_index,
                        etymology_status, word_family_status, usage_context_status,
                        cultural_notes_status, frequency_status, bilibili_videos_status
                    FROM entry_cache
                    WHERE word = ?
                    ORDER BY entry_index
                """, (word,)).fetchall()
                
                # Get sense-level sections for this word
                sense_sections = conn.execute("""
                    SELECT 
                        entry_index, sense_index,
                        detailed_sense_status, examples_status, usage_notes_status
                    FROM sense_cache
                    WHERE word = ?
                    ORDER BY entry_index, sense_index
                """, (word,)).fetchall()
                
                # Build sections summary
                sections = {
                    'basic': row['basic_status']
                }
                
                # Word-level common_phrases section
                common_phrases_status = conn.execute("""
                    SELECT common_phrases_status
                    FROM word_cache
                    WHERE word = ?
                """, (word,)).fetchone()
                
                if common_phrases_status and common_phrases_status['common_phrases_status'] not in ('empty', None):
                    sections['common_phrases'] = common_phrases_status['common_phrases_status']
                
                # Entry-level sections
                for entry_row in entry_sections:
                    entry_idx = entry_row['entry_index']
                    for section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']:
                        status = entry_row[f'{section}_status']
                        if status not in ('empty', None):
                            sections[f'{section}[{entry_idx}]'] = status
                
                # Sense-level sections
                for sense_row in sense_sections:
                    entry_idx = sense_row['entry_index']
                    sense_idx = sense_row['sense_index']
                    for section in ['detailed_sense', 'examples', 'usage_notes']:
                        status = sense_row[f'{section}_status']
                        if status not in ('empty', None):
                            sections[f'{section}[{entry_idx},{sense_idx}]'] = status
                
                words.append({
                    'word': word,
                    'sections': sections,
                    'created_at': row['created_at'],
                    'last_accessed_at': row['last_accessed_at']
                })
            
            return {
                'words': words,
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total
            }
        finally:
            conn.close()
    
    def get_word_details(self, word: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed cache information for a specific word including all entries and videos
        
        Returns:
            Dict with word details, entries, and video information
        """
        normalized = self._normalize_word(word)
        conn = self._read_connection()
        
        try:
            # Get basic word info
            word_row = conn.execute("""
                SELECT word, basic_status, basic_data,
                       common_phrases_status, common_phrases_data,
                       datetime(created_at, 'unixepoch', 'localtime') as created_at,
                       datetime(last_accessed_at, 'unixepoch', 'localtime') as last_accessed_at
                FROM word_cache
                WHERE word = ?
            """, (normalized,)).fetchone()
            
            if not word_row:
                return None
            
            # Get all entries for this word
            entry_rows = conn.execute("""
                SELECT entry_index,
                       etymology_data, etymology_status,
                       word_family_data, word_family_status,
                       usage_context_data, usage_context_status,
                       cultural_notes_data, cultural_notes_status,
                       frequency_data, frequency_status,
                       bilibili_videos_data, bilibili_videos_status
                FROM entry_cache
                WHERE word = ?
                ORDER BY entry_index
            """, (normalized,)).fetchall()
            
            # Get all senses for this word
            sense_rows = conn.execute("""
                SELECT entry_index, sense_index,
                       detailed_sense_data, detailed_sense_status,
                       examples_data, examples_status,
                       usage_notes_data, usage_notes_status
                FROM sense_cache
                WHERE word = ?
                ORDER BY entry_index, sense_index
            """, (normalized,)).fetchall()
            
            # Parse basic_data to get sense metadata (definition, part_of_speech, etc.)
            basic_data = None
            if word_row['basic_data']:
                try:
                    basic_data = json.loads(word_row['basic_data'])
                except:
                    pass
            
            # Build entries structure
            entries = []
            for entry_row in entry_rows:
                entry_idx = entry_row['entry_index']
                
                # Parse bilibili videos
                videos = []
                if entry_row['bilibili_videos_data']:
                    try:
                        videos_data = json.loads(entry_row['bilibili_videos_data'])
                        videos = videos_data.get('bilibili_videos', [])
                    except:
                        pass
                
                # Build section statuses and data
                sections = {}
                for section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
                    status = entry_row[f'{section}_status']
                    data_raw = entry_row[f'{section}_data']
                    if status not in ('empty', None):
                        try:
                            data = json.loads(data_raw) if data_raw else None
                            sections[section] = {'status': status, 'data': data}
                        except:
                            sections[section] = {'status': status, 'data': None}
                
                # Get senses for this entry
                senses = []
                
                # Build a mapping of (entry_index, sense_index) -> basic sense metadata
                basic_senses_map = {}
                if basic_data and 'entries' in basic_data:
                    for entry in basic_data['entries']:
                        if entry['entry_index'] == entry_idx and 'meanings_summary' in entry:
                            sense_counter = 0
                            for meaning in entry['meanings_summary']:
                                part_of_speech = meaning.get('part_of_speech', 'N/A')
                                for sense in meaning.get('senses', []):
                                    basic_senses_map[sense_counter] = {
                                        'definition': sense.get('definition', 'N/A'),
                                        'part_of_speech': part_of_speech,
                                        'example': sense.get('example'),
                                        'synonyms': sense.get('synonyms', []),
                                        'antonyms': sense.get('antonyms', [])
                                    }
                                    sense_counter += 1
                
                # Merge AI sections with basic metadata
                for sense_row in sense_rows:
                    if sense_row['entry_index'] == entry_idx:
                        sense_idx = sense_row['sense_index']
                        
                        # Get basic metadata for this sense
                        basic_metadata = basic_senses_map.get(sense_idx, {})
                        
                        # Build AI section data
                        sense_sections = {}
                        for section in ['detailed_sense', 'examples', 'usage_notes']:
                            status = sense_row[f'{section}_status']
                            data_raw = sense_row[f'{section}_data']
                            if status not in ('empty', None):
                                try:
                                    data = json.loads(data_raw) if data_raw else None
                                    sense_sections[section] = {'status': status, 'data': data}
                                except:
                                    sense_sections[section] = {'status': status, 'data': None}
                        
                        # Only add sense if it has either basic metadata or AI sections
                        if basic_metadata or sense_sections:
                            senses.append({
                                'sense_index': sense_idx,
                                'definition': basic_metadata.get('definition', 'N/A'),
                                'part_of_speech': basic_metadata.get('part_of_speech', 'N/A'),
                                'example': basic_metadata.get('example'),
                                'synonyms': basic_metadata.get('synonyms', []),
                                'antonyms': basic_metadata.get('antonyms', []),
                                'sections': sense_sections
                            })
                
                entries.append({
                    'entry_index': entry_idx,
                    'sections': sections,
                    'videos': videos,
                    'videos_status': entry_row['bilibili_videos_status'],
                    'senses': senses
                })
            
            common_phrases_data = None
            if word_row['common_phrases_data']:
                try:
                    common_phrases_data = json.loads(word_row['common_phrases_data'])
                except:
                    pass
            
            phrase_videos = conn.execute("""
                SELECT phrase, bilibili_videos_data, bilibili_videos_status,
                       datetime(last_accessed_at, 'unixepoch', 'localtime') as last_accessed_at
                FROM phrase_cache
                WHERE word = ?
                ORDER BY last_accessed_at DESC
            """, (normalized,)).fetchall()
            
            phrase_videos_list = []
            for pv_row in phrase_videos:
                try:
                    videos_data = json.loads(pv_row['bilibili_videos_data']) if pv_row['bilibili_videos_data'] else {}
                    
                    # Handle both single video (dict) and array formats
                    bilibili_videos = videos_data.get('bilibili_videos', [])
                    if isinstance(bilibili_videos, dict):
                        # Single video - wrap in array
                        bilibili_videos = [bilibili_videos]
                    elif not isinstance(bilibili_videos, list):
                        # Invalid format - use empty array
                        bilibili_videos = []
                    
                    phrase_videos_list.append({
                        'phrase': pv_row['phrase'],
                        'videos': bilibili_videos,
                        'status': pv_row['bilibili_videos_status'],
                        'last_accessed_at': pv_row['last_accessed_at']
                    })
                except:
                    pass
            
            # Get AI-generated phrase videos
            ai_videos = conn.execute("""
                SELECT phrase, task_id, video_url, status, style, duration, resolution, ratio,
                       datetime(created_at, 'unixepoch', 'localtime') as created_at,
                       datetime(completed_at, 'unixepoch', 'localtime') as completed_at,
                       datetime(last_accessed_at, 'unixepoch', 'localtime') as last_accessed_at
                FROM ai_phrase_video_cache
                WHERE word = ?
                ORDER BY phrase, created_at DESC
            """, (normalized,)).fetchall()
            
            # Group AI videos by phrase
            ai_videos_by_phrase = {}
            for av_row in ai_videos:
                phrase = av_row['phrase']
                if phrase not in ai_videos_by_phrase:
                    ai_videos_by_phrase[phrase] = []
                
                ai_videos_by_phrase[phrase].append({
                    'task_id': av_row['task_id'],
                    'video_url': av_row['video_url'],
                    'status': av_row['status'],
                    'style': av_row['style'],
                    'duration': av_row['duration'],
                    'resolution': av_row['resolution'],
                    'ratio': av_row['ratio'],
                    'created_at': av_row['created_at'],
                    'completed_at': av_row['completed_at'],
                    'last_accessed_at': av_row['last_accessed_at']
                })
            
            # Convert to list format
            ai_phrase_videos_list = []
            for phrase, videos in ai_videos_by_phrase.items():
                ai_phrase_videos_list.append({
                    'phrase': phrase,
                    'videos': videos
                })
            
            return {
                'word': word_row['word'],
                'basic_status': word_row['basic_status'],
                'common_phrases_status': word_row['common_phrases_status'],
                'common_phrases': common_phrases_data,
                'phrase_videos': phrase_videos_list,
                'ai_phrase_videos': ai_phrase_videos_list,
                'created_at': word_row['created_at'],
                'last_accessed_at': word_row['last_accessed_at'],
                'entries': entries
            }
        finally:
            conn.close()
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        conn = self._read_connection()
        
        try:
            # Database stats
            db_stats = conn.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM word_cache) as total_words,
                    (SELECT COUNT(*) FROM entry_cache) as total_entries,
                    (SELECT COUNT(*) FROM sense_cache) as total_senses,
                    (SELECT COUNT(*) FROM phrase_cache) as total_phrase_videos,
                    (SELECT COUNT(*) FROM ai_phrase_video_cache) as total_ai_phrase_videos,
                    (SELECT COUNT(*) FROM cache_metrics) as total_metrics
            """).fetchone()
            
            # Recent metrics (last 24 hours)
            yesterday = int(time.time()) - (24 * 3600)
            recent_metrics = conn.execute("""
                SELECT metric_type, COUNT(*) as count
                FROM cache_metrics
                WHERE timestamp >= ?
                GROUP BY metric_type
            """, (yesterday,)).fetchall()
            
            metrics_by_type = {row['metric_type']: row['count'] for row in recent_metrics}
            
            return {
                'database': dict(db_stats),
                'metrics_24h': metrics_by_type,
                'in_memory_stats': self.metrics.get_stats()
            }
        finally:
            conn.close()

    def lookup_with_cache(self, word, section, entry_index, sense_index, phrase, fetch_func):
        """
        Unified cache orchestration for dictionary lookups.
        
        Handles:
        - Cache read with stale detection
        - Stale-while-revalidate pattern
        - In-flight request coordination
        - Service call + cache write
        - Metrics tracking
        
        Args:
            word: Word to lookup
            section: Section to fetch
            entry_index: Entry index (for entry-level sections)
            sense_index: Sense index (for sense-level sections)
            phrase: Phrase for bilibili_videos section (optional)
            fetch_func: Function to call on cache miss. Should accept no args and return dict.
        
        Returns:
            Tuple: (result_dict, http_status_code)
        """
        import time
        start_time = time.time()
        
        # --- CACHE READ (Fast Path) ---
        cached = None
        if section == 'basic':
            cached = self.get_basic(word)
        elif section == 'common_phrases':
            cached = self.get_common_phrases(word)
        elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
            if entry_index is not None:
                cached = self.get_entry_section(word, entry_index, section)
        elif section == 'bilibili_videos':
            if phrase:
                cached = self.get_phrase_videos(word, phrase)
        elif section in ['detailed_sense', 'examples', 'usage_notes']:
            if entry_index is not None and sense_index is not None:
                cached = self.get_sense_section(word, entry_index, sense_index, section)
        
        # Cache hit handling
        if cached and cached.get('cache_hit'):
            response_time = (time.time() - start_time) * 1000
            
            if cached.get('is_stale'):
                # Stale-while-revalidate: serve stale + refresh in background
                logger.info(f"[{word}] Cache HIT (stale) - serving + bg refresh")
                self.metrics.record_stale()
                self.track_metric('stale', word, section, response_time, 'cache')
                
                # Trigger background refresh (non-blocking)
                # Import refresh function to avoid circular dependency
                from ai_svc.dictionary.cache_routes import refresh_cache_background
                self.executor.submit(
                    refresh_cache_background, word, section, entry_index, sense_index
                )
                
                # Return stale data immediately
                result = cached['data']
                result['_cache_status'] = 'stale'
                result['_cache_age_seconds'] = int(time.time() - cached.get('updated_at', time.time()))
                return result, 200
            else:
                # Fresh cache hit
                logger.info(f"[{word}] Cache HIT (fresh) - {section}")
                self.metrics.record_hit(time.time() - start_time)
                self.track_metric('hit', word, section, response_time, 'cache')
                
                result = cached['data']
                result['_cache_status'] = 'fresh'
                return result, 200
        
        # --- CACHE MISS: Check for in-flight request ---
        cache_key = self._make_cache_key(word, section, entry_index, sense_index)
        
        # Try to mark this request as in-flight
        if not self.mark_inflight(cache_key):
            # Another request is already fetching this - wait and retry
            logger.info(f"[{word}] Request already in-flight for {section} - waiting...")
            
            # Wait up to 10 seconds with exponential backoff
            max_wait = 10.0
            wait_interval = 0.5
            elapsed = 0
            
            while elapsed < max_wait:
                time.sleep(wait_interval)
                elapsed += wait_interval
                
                # Re-check cache
                if section == 'basic':
                    cached = self.get_basic(word)
                elif section == 'common_phrases':
                    cached = self.get_common_phrases(word)
                elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
                    if entry_index is not None:
                        cached = self.get_entry_section(word, entry_index, section)
                elif section == 'bilibili_videos':
                    if phrase:
                        cached = self.get_phrase_videos(word, phrase)
                elif section in ['detailed_sense', 'examples', 'usage_notes']:
                    if entry_index is not None and sense_index is not None:
                        cached = self.get_sense_section(word, entry_index, sense_index, section)
                
                if cached and cached.get('cache_hit'):
                    logger.info(f"[{word}] Cache now available after waiting {elapsed}s - serving")
                    result = cached['data']
                    result['_cache_status'] = 'fresh'
                    result['_waited_for_inflight'] = True
                    self.metrics.record_hit(time.time() - start_time)
                    return result, 200
                
                # Increase wait interval (exponential backoff)
                wait_interval = min(wait_interval * 1.5, 2.0)
        
        try:
            # --- Fetch from service ---
            logger.info(f"[{word}] Cache MISS - fetching {section} from service")
            result = fetch_func()
            
            response_time = (time.time() - start_time) * 1000
            self.metrics.record_miss(time.time() - start_time, result.get('data_source', 'unknown'))
            self.track_metric('miss', word, section, response_time, result.get('data_source', 'service'))
            
            # --- CACHE WRITE (only on success) ---
            if result.get('success'):
                try:
                    if section == 'basic':
                        self.set_basic(word, result)
                    elif section == 'common_phrases':
                        self.set_common_phrases(word, result)
                    elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']:
                        if entry_index is not None:
                            self.set_entry_section(word, entry_index, section, result)
                    elif section == 'bilibili_videos':
                        if phrase:
                            self.set_phrase_videos(word, phrase, result)
                    elif section in ['detailed_sense', 'examples', 'usage_notes']:
                        if entry_index is not None and sense_index is not None:
                            self.set_sense_section(word, entry_index, sense_index, section, result)
                except Exception as cache_error:
                    logger.warning(f"Failed to write cache for {word}/{section}: {cache_error}")
            
            return result, 200
        finally:
            # Always clear in-flight marker
            self.clear_inflight(cache_key)

# Global cache instance
cache_service = DictionaryCacheService()
