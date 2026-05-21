import time
import threading
import sqlite3
import os
import json
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
DB_PATH = os.path.join(os.path.dirname(__file__), "metrics.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ai_requests (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            REAL    NOT NULL,
    agent_name           TEXT    NOT NULL,
    word                 TEXT    NOT NULL,
    section              TEXT    NOT NULL,
    input_tokens         INTEGER NOT NULL DEFAULT 0,
    output_tokens        INTEGER NOT NULL DEFAULT 0,
    cache_hit            INTEGER NOT NULL DEFAULT 0,
    cache_miss           INTEGER NOT NULL DEFAULT 0,
    cache_write          INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens     INTEGER NOT NULL DEFAULT 0,
    latency_ms           REAL    NOT NULL DEFAULT 0,
    time_to_first_token  REAL,
    success              INTEGER NOT NULL DEFAULT 1,
    error                TEXT,
    model                TEXT,
    model_provider       TEXT,
    estimated_cost       REAL,
    prompt_len           INTEGER NOT NULL DEFAULT 0,
    run_id               TEXT,
    provider_metrics_raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_timestamp ON ai_requests (timestamp);
CREATE INDEX IF NOT EXISTS idx_agent     ON ai_requests (agent_name);
"""

_MIGRATIONS = [
    "ALTER TABLE ai_requests ADD COLUMN cache_write         INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ai_requests ADD COLUMN reasoning_tokens    INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ai_requests ADD COLUMN time_to_first_token REAL",
    "ALTER TABLE ai_requests ADD COLUMN model               TEXT",
    "ALTER TABLE ai_requests ADD COLUMN model_provider      TEXT",
    "ALTER TABLE ai_requests ADD COLUMN estimated_cost      REAL",
    "ALTER TABLE ai_requests ADD COLUMN prompt_len          INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ai_requests ADD COLUMN run_id              TEXT",
    "ALTER TABLE ai_requests ADD COLUMN provider_metrics_raw TEXT",
    "CREATE INDEX IF NOT EXISTS idx_model ON ai_requests (model)",
]


class MetricsCollector:

    def __init__(self, db_path: str = DB_PATH, retention_days: int = RETENTION_DAYS):
        self._db_path = db_path
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(_CREATE_TABLE)
            for stmt in _MIGRATIONS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _cutoff(self) -> float:
        return time.time() - self._retention_days * 86400

    def _purge_old(self, conn: sqlite3.Connection):
        conn.execute("DELETE FROM ai_requests WHERE timestamp < ?", (self._cutoff(),))

    def record(self, rec: "_Record"):
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO ai_requests "
                    "(timestamp,agent_name,word,section,input_tokens,output_tokens,"
                    " cache_hit,cache_miss,cache_write,reasoning_tokens,"
                    " latency_ms,time_to_first_token,success,error,"
                    " model,model_provider,estimated_cost,prompt_len,run_id,provider_metrics_raw) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rec.timestamp, rec.agent_name, rec.word, rec.section,
                     rec.input_tokens, rec.output_tokens,
                     rec.cache_hit_tokens, rec.cache_miss_tokens,
                     rec.cache_write_tokens, rec.reasoning_tokens,
                     rec.latency_ms, rec.time_to_first_token,
                     int(rec.success), rec.error,
                     rec.model, rec.model_provider,
                     rec.estimated_cost, rec.prompt_len,
                     rec.run_id, rec.provider_metrics_raw),
                )
                self._purge_old(conn)

    @contextmanager
    def track(self, agent_name: str, word: str, section: str, prompt: str = ""):
        """
        Times execution and persists metrics to SQLite after the block exits.

            with metrics_collector.track("EtymologyAgent", word, "etymology", prompt) as t:
                response = agent.run(prompt)
                t.set_response(response)
        """
        tracker = _Tracker(agent_name, word, section, prompt)
        t0 = time.perf_counter()
        try:
            yield tracker
            tracker._latency_ms = (time.perf_counter() - t0) * 1000
            tracker._success = True
        except Exception as exc:
            tracker._latency_ms = (time.perf_counter() - t0) * 1000
            tracker._success = False
            tracker._error = str(exc)
            raise
        finally:
            self.record(tracker._build_record())

    def get_summary(self) -> Dict[str, Any]:
        cutoff = self._cutoff()
        with self._conn() as conn:
            totals = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(success) as successes, "
                "SUM(input_tokens) as inp, SUM(output_tokens) as out, "
                "SUM(cache_hit) as hits, SUM(cache_miss) as misses, "
                "SUM(cache_write) as writes, SUM(reasoning_tokens) as reasoning, "
                "SUM(estimated_cost) as total_cost, "
                "AVG(latency_ms) as avg_lat "
                "FROM ai_requests WHERE timestamp >= ?",
                (cutoff,)
            ).fetchone()

            if not totals or totals["total"] == 0:
                return self._empty_summary()

            total = totals["total"]
            successes = totals["successes"] or 0
            total_input = totals["inp"] or 0
            total_output = totals["out"] or 0
            total_hits = totals["hits"] or 0
            total_misses = totals["misses"] or 0
            total_writes = totals["writes"] or 0
            total_reasoning = totals["reasoning"] or 0
            total_cost = totals["total_cost"]
            avg_lat = totals["avg_lat"] or 0

            latencies = [
                row[0] for row in conn.execute(
                    "SELECT latency_ms FROM ai_requests WHERE timestamp >= ? ORDER BY latency_ms",
                    (cutoff,)
                ).fetchall()
            ]

            def pct(p):
                return round(latencies[int(len(latencies) * p / 100)], 1)

            agent_rows = conn.execute(
                "SELECT agent_name, "
                "COUNT(*) as cnt, SUM(success) as ok, "
                "SUM(input_tokens) as inp, SUM(output_tokens) as out, "
                "SUM(cache_hit) as hits, SUM(cache_miss) as misses, "
                "SUM(cache_write) as writes, SUM(reasoning_tokens) as reasoning, "
                "SUM(estimated_cost) as total_cost, "
                "AVG(latency_ms) as avg_lat, "
                "model "
                "FROM ai_requests WHERE timestamp >= ? "
                "GROUP BY agent_name ORDER BY cnt DESC",
                (cutoff,)
            ).fetchall()

            agent_list = []
            for r in agent_rows:
                cnt = r["cnt"]
                inp = r["inp"] or 0
                hit = r["hits"] or 0
                agent_list.append({
                    "agent_name": r["agent_name"],
                    "count": cnt,
                    "success_rate": round((r["ok"] or 0) / cnt * 100, 1),
                    "errors": cnt - (r["ok"] or 0),
                    "input_tokens": inp,
                    "output_tokens": r["out"] or 0,
                    "cache_hit_tokens": hit,
                    "cache_miss_tokens": r["misses"] or 0,
                    "cache_write_tokens": r["writes"] or 0,
                    "reasoning_tokens": r["reasoning"] or 0,
                    "cache_hit_rate": round(hit / inp * 100, 1) if inp > 0 else 0,
                    "avg_latency_ms": round(r["avg_lat"] or 0, 1),
                    "total_cost": r["total_cost"],
                    "model": r["model"],
                })

            now = time.time()
            bucket_rows = conn.execute(
                "SELECT CAST((? - timestamp) / 60 AS INTEGER) as age_min, "
                "COUNT(*) as cnt, "
                "SUM(input_tokens) as inp, SUM(output_tokens) as out, "
                "SUM(cache_hit) as hits, "
                "AVG(latency_ms) as avg_lat "
                "FROM ai_requests WHERE timestamp >= ? AND timestamp >= ? "
                "GROUP BY age_min",
                (now, now - 3600, cutoff)
            ).fetchall()

            buckets: Dict[int, Any] = {}
            for row in bucket_rows:
                age = row["age_min"]
                if 0 <= age <= 59:
                    buckets[59 - age] = row

            timeseries = []
            for i in range(60):
                b = buckets.get(i)
                timeseries.append({
                    "minute": i,
                    "count": b["cnt"] if b else 0,
                    "input_tokens": (b["inp"] or 0) if b else 0,
                    "output_tokens": (b["out"] or 0) if b else 0,
                    "cache_hit_tokens": (b["hits"] or 0) if b else 0,
                    "avg_latency_ms": round(b["avg_lat"] or 0, 1) if b else 0,
                })

        cache_total = total_hits + total_misses
        return {
            "uptime_seconds": round(time.time() - self._start_time),
            "total_requests": total,
            "successful_requests": successes,
            "failed_requests": total - successes,
            "success_rate": round(successes / total * 100, 1),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_cache_hit_tokens": total_hits,
            "total_cache_miss_tokens": total_misses,
            "total_cache_write_tokens": total_writes,
            "total_reasoning_tokens": total_reasoning,
            "total_cost": total_cost,
            "overall_cache_hit_rate": round(total_hits / cache_total * 100, 1) if cache_total > 0 else 0,
            "avg_latency_ms": round(avg_lat, 1),
            "p50_latency_ms": pct(50),
            "p95_latency_ms": pct(95),
            "p99_latency_ms": pct(99),
            "agents": agent_list,
            "timeseries": timeseries,
            "retention_days": self._retention_days,
        }

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_requests ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [
            {
                "timestamp": r["timestamp"],
                "agent_name": r["agent_name"],
                "word": r["word"],
                "section": r["section"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cache_hit_tokens": r["cache_hit"],
                "cache_miss_tokens": r["cache_miss"],
                "cache_write_tokens": r["cache_write"],
                "reasoning_tokens": r["reasoning_tokens"],
                "latency_ms": round(r["latency_ms"], 1),
                "time_to_first_token": r["time_to_first_token"],
                "success": bool(r["success"]),
                "error": r["error"],
                "model": r["model"],
                "model_provider": r["model_provider"],
                "estimated_cost": r["estimated_cost"],
                "prompt_len": r["prompt_len"],
                "run_id": r["run_id"],
                "provider_metrics_raw": r["provider_metrics_raw"],
            }
            for r in rows
        ]

    def _empty_summary(self) -> Dict[str, Any]:
        return {
            "uptime_seconds": round(time.time() - self._start_time),
            "total_requests": 0, "successful_requests": 0, "failed_requests": 0,
            "success_rate": 0, "total_input_tokens": 0, "total_output_tokens": 0,
            "total_tokens": 0, "total_cache_hit_tokens": 0, "total_cache_miss_tokens": 0,
            "total_cache_write_tokens": 0, "total_reasoning_tokens": 0, "total_cost": None,
            "overall_cache_hit_rate": 0, "avg_latency_ms": 0,
            "p50_latency_ms": 0, "p95_latency_ms": 0, "p99_latency_ms": 0,
            "agents": [],
            "timeseries": [{"minute": i, "count": 0, "input_tokens": 0,
                             "output_tokens": 0, "cache_hit_tokens": 0,
                             "avg_latency_ms": 0} for i in range(60)],
            "retention_days": self._retention_days,
        }


class _Record:
    __slots__ = (
        "timestamp", "agent_name", "word", "section",
        "input_tokens", "output_tokens",
        "cache_hit_tokens", "cache_miss_tokens", "cache_write_tokens",
        "reasoning_tokens", "latency_ms", "time_to_first_token",
        "success", "error",
        "model", "model_provider", "estimated_cost",
        "prompt_len", "run_id", "provider_metrics_raw",
    )

    def __init__(self, agent_name, word, section,
                 input_tokens=0, output_tokens=0,
                 cache_hit_tokens=0, cache_miss_tokens=0, cache_write_tokens=0,
                 reasoning_tokens=0, latency_ms=0.0, time_to_first_token=None,
                 success=True, error=None,
                 model=None, model_provider=None, estimated_cost=None,
                 prompt_len=0, run_id=None, provider_metrics_raw=None):
        self.timestamp = time.time()
        self.agent_name = agent_name
        self.word = word
        self.section = section
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_hit_tokens = cache_hit_tokens
        self.cache_miss_tokens = cache_miss_tokens
        self.cache_write_tokens = cache_write_tokens
        self.reasoning_tokens = reasoning_tokens
        self.latency_ms = latency_ms
        self.time_to_first_token = time_to_first_token
        self.success = success
        self.error = error
        self.model = model
        self.model_provider = model_provider
        self.estimated_cost = estimated_cost
        self.prompt_len = prompt_len
        self.run_id = run_id
        self.provider_metrics_raw = provider_metrics_raw


class _Tracker:

    def __init__(self, agent_name: str, word: str, section: str, prompt: str = ""):
        self._agent_name = agent_name
        self._word = word
        self._section = section
        self._prompt_len = len(prompt)
        self._latency_ms = 0.0
        self._success = True
        self._error: Optional[str] = None
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_hit_tokens = 0
        self._cache_miss_tokens = 0
        self._cache_write_tokens = 0
        self._reasoning_tokens = 0
        self._time_to_first_token: Optional[float] = None
        self._model: Optional[str] = None
        self._model_provider: Optional[str] = None
        self._estimated_cost: Optional[float] = None
        self._run_id: Optional[str] = None
        self._provider_metrics_raw: Optional[str] = None

    def set_prompt(self, prompt: str):
        self._prompt_len = len(prompt)

    def set_response(self, response):
        try:
            if response is None:
                return

            self._model = getattr(response, "model", None)
            self._model_provider = getattr(response, "model_provider", None)
            self._run_id = getattr(response, "run_id", None)

            m = getattr(response, "metrics", None)
            if m is None:
                return

            self._input_tokens = getattr(m, "input_tokens", 0) or 0
            self._output_tokens = getattr(m, "output_tokens", 0) or 0
            self._cache_hit_tokens = getattr(m, "cache_read_tokens", 0) or 0
            self._cache_write_tokens = getattr(m, "cache_write_tokens", 0) or 0
            self._reasoning_tokens = getattr(m, "reasoning_tokens", 0) or 0
            self._time_to_first_token = getattr(m, "time_to_first_token", None)
            self._estimated_cost = getattr(m, "cost", None)

            provider_metrics = getattr(m, "provider_metrics", None) or {}

            provider_miss = provider_metrics.get("prompt_cache_miss_tokens")

            self._cache_miss_tokens = (
                provider_miss if provider_miss is not None
                else max(0, self._input_tokens - self._cache_hit_tokens)
            )

            if provider_metrics:
                self._provider_metrics_raw = json.dumps(provider_metrics)

        except Exception as e:
            logger.debug(f"MetricsCollector: failed to parse response metrics: {e}")

    def _build_record(self) -> _Record:
        return _Record(
            agent_name=self._agent_name,
            word=self._word,
            section=self._section,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cache_hit_tokens=self._cache_hit_tokens,
            cache_miss_tokens=self._cache_miss_tokens,
            cache_write_tokens=self._cache_write_tokens,
            reasoning_tokens=self._reasoning_tokens,
            latency_ms=self._latency_ms,
            time_to_first_token=self._time_to_first_token,
            success=self._success,
            error=self._error,
            model=self._model,
            model_provider=self._model_provider,
            estimated_cost=self._estimated_cost,
            prompt_len=self._prompt_len,
            run_id=self._run_id,
            provider_metrics_raw=self._provider_metrics_raw,
        )


metrics_collector = MetricsCollector()
