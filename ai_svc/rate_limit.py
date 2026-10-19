"""
Simple in-memory sliding-window rate limiter (per process, reset on restart).
"""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def is_limited(self, key: str) -> bool:
        """Record a hit for key; return True when it exceeds the limit."""
        now = time.time()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if not hits:
                # Drop idle keys so the dict doesn't grow forever
                self._hits.pop(key, None)
                hits = self._hits[key]
            if len(hits) >= self.max_requests:
                return True
            hits.append(now)
            return False

    def reset(self):
        with self._lock:
            self._hits.clear()
