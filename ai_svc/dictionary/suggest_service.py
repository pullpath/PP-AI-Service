"""
Word Suggestion Service for Dictionary Autocomplete
Hybrid 3-tier architecture: Datamuse API → Local RapidFuzz → Cache
"""
import requests
import logging
import bisect
import os
import json
from pathlib import Path
from functools import lru_cache
from typing import List, Optional
from rapidfuzz import process, fuzz, utils

logger = logging.getLogger(__name__)


class DatamuseClient:
    """Datamuse API client for word suggestions (Tier 1)"""
    
    BASE_URL = "https://api.datamuse.com/sug"
    
    def __init__(self, timeout: float = 1.0, max_results: int = 10):
        """
        Initialize Datamuse client with connection pooling
        
        Args:
            timeout: Request timeout in seconds (fail fast for <100ms target)
            max_results: Maximum number of suggestions to return
        """
        self.timeout = timeout
        self.max_results = max_results
        self.session = requests.Session()  # Connection pooling for performance
    
    def suggest(self, prefix: str, limit: Optional[int] = None) -> Optional[List[str]]:
        """
        Get word suggestions from Datamuse API
        
        Args:
            prefix: User input prefix (e.g., "he")
            limit: Override max_results
            
        Returns:
            List of word suggestions, or None if API fails
        """
        if not prefix or len(prefix) < 2:
            return []
        
        try:
            response = self.session.get(
                self.BASE_URL,
                params={"s": prefix.lower(), "max": limit or self.max_results},
                timeout=self.timeout
            )
            response.raise_for_status()
            
            results = response.json()
            suggestions = [item["word"] for item in results]
            
            logger.info(f"[Datamuse] prefix='{prefix}' → {len(suggestions)} suggestions")
            return suggestions
            
        except requests.Timeout:
            logger.warning(f"[Datamuse] Timeout for prefix '{prefix}' (>{self.timeout}s)")
            return None
        except requests.RequestException as e:
            logger.error(f"[Datamuse] Request error for prefix '{prefix}': {e}")
            return None
        except Exception as e:
            logger.error(f"[Datamuse] Unexpected error for prefix '{prefix}': {e}")
            return None


class LocalClient:
    """Local fuzzy matching client with word list (Tier 2)"""
    
    def __init__(self, words: List[str]):
        """
        Initialize with sorted word list
        
        Args:
            words: List of English words (frequency-ranked preferred)
        """
        # Deduplicate and sort for binary search
        self.words = sorted(set(word.lower() for word in words))
        logger.info(f"[Local] Initialized with {len(self.words)} words")
    
    def _prefix_match(self, prefix: str, limit: int = 50) -> List[str]:
        """
        Binary search for prefix matches - O(log n + k)
        
        Args:
            prefix: User input prefix
            limit: Maximum matches to collect
            
        Returns:
            List of words starting with prefix
        """
        prefix_lower = prefix.lower()
        
        # Find insertion point with binary search
        start_idx = bisect.bisect_left(self.words, prefix_lower)
        
        # Collect matching prefixes
        matches = []
        for i in range(start_idx, min(start_idx + 100, len(self.words))):
            if i >= len(self.words):
                break
            
            if self.words[i].startswith(prefix_lower):
                matches.append(self.words[i])
                if len(matches) >= limit:
                    break
            else:
                break  # No more prefix matches (sorted)
        
        return matches
    
    @lru_cache(maxsize=1000)
    def suggest(self, query: str, limit: int = 10) -> List[str]:
        """
        Hybrid suggestion: prefix match + fuzzy fallback for typos
        
        Args:
            query: User input
            limit: Maximum suggestions to return
            
        Returns:
            List of word suggestions
        """
        if not query or len(query) < 2:
            return []
        
        # Step 1: Try exact prefix match (fast)
        prefix_matches = self._prefix_match(query, limit=limit)
        
        if len(prefix_matches) >= limit:
            logger.info(f"[Local] prefix_match '{query}' → {len(prefix_matches)} results")
            return prefix_matches[:limit]
        
        # Step 2: Fuzzy match for typos (slower, better quality)
        try:
            fuzzy_results = process.extract(
                query,
                self.words,
                scorer=fuzz.WRatio,  # Best for partial matches
                processor=utils.default_process,  # Lowercase + strip
                limit=limit,
                score_cutoff=70.0  # Minimum match quality
            )
            
            # Combine and deduplicate (preserve order)
            combined = prefix_matches + [word for word, score, idx in fuzzy_results]
            seen = set()
            unique = []
            for word in combined:
                if word not in seen:
                    seen.add(word)
                    unique.append(word)
            
            logger.info(f"[Local] fuzzy_match '{query}' → {len(unique)} results (prefix: {len(prefix_matches)}, fuzzy: {len(fuzzy_results)})")
            return unique[:limit]
            
        except Exception as e:
            logger.error(f"[Local] Fuzzy match error for '{query}': {e}")
            return prefix_matches[:limit]


class WordListManager:
    """Manages word list download and caching"""
    
    # Google 10K most common English words (frequency-ranked)
    WORD_LIST_URL = "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-usa-no-swears.txt"
    CACHE_DIR = "data"
    CACHE_FILE = "word_list_cache.txt"
    
    @classmethod
    def load_words(cls) -> List[str]:
        """
        Load word list with caching
        
        Returns:
            List of English words (frequency-ranked)
        """
        cache_path = Path(cls.CACHE_DIR) / cls.CACHE_FILE
        
        # Try loading from cache first
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    words = [line.strip() for line in f if line.strip()]
                logger.info(f"[WordList] Loaded {len(words)} words from cache: {cache_path}")
                return words
            except Exception as e:
                logger.warning(f"[WordList] Failed to load cache: {e}")
        
        # Download on first run
        logger.info(f"[WordList] Downloading from {cls.WORD_LIST_URL}")
        words = cls._download_words()
        
        # Cache to disk
        cls._save_cache(words, cache_path)
        
        return words
    
    @classmethod
    def _download_words(cls) -> List[str]:
        """Download word list from GitHub"""
        try:
            response = requests.get(cls.WORD_LIST_URL, timeout=10)
            response.raise_for_status()
            words = response.text.strip().split("\n")
            logger.info(f"[WordList] Downloaded {len(words)} words")
            return words
        except Exception as e:
            logger.error(f"[WordList] Download failed: {e}")
            # Fallback to minimal word list
            return ["the", "be", "to", "of", "and", "a", "in", "that", "have", "it"]
    
    @classmethod
    def _save_cache(cls, words: List[str], cache_path: Path):
        """Save word list to cache file"""
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(words))
            logger.info(f"[WordList] Cached {len(words)} words to {cache_path}")
        except Exception as e:
            logger.warning(f"[WordList] Failed to save cache: {e}")


class SuggestionService:
    """Hybrid word suggestion service (Tier 1 + Tier 2)"""
    
    def __init__(self):
        """Initialize suggestion service with Datamuse + Local clients"""
        # Load word list
        words = WordListManager.load_words()
        
        # Initialize clients
        self.datamuse = DatamuseClient(timeout=1.0, max_results=10)
        self.local = LocalClient(words)
        
        logger.info("[SuggestionService] Initialized (Datamuse + Local)")
    
    def suggest(self, query: str, limit: int = 10) -> dict:
        """
        Get word suggestions with hybrid fallback
        
        Args:
            query: User input
            limit: Maximum suggestions to return
            
        Returns:
            {
                "query": str,
                "suggestions": List[str],
                "source": "datamuse" | "local",
                "success": bool
            }
        """
        if not query or len(query) < 2:
            return {
                "query": query,
                "suggestions": [],
                "source": "none",
                "success": True
            }
        
        # Normalize query
        query_normalized = query.strip().lower()
        
        # Tier 1: Try Datamuse API (fast + comprehensive)
        suggestions = self.datamuse.suggest(query_normalized, limit=limit)
        
        if suggestions is not None and len(suggestions) > 0:
            return {
                "query": query,
                "suggestions": suggestions[:limit],
                "source": "datamuse",
                "success": True
            }
        
        # Tier 2: Fallback to local (reliable)
        logger.info(f"[SuggestionService] Datamuse failed, using local fallback for '{query}'")
        suggestions = self.local.suggest(query_normalized, limit=limit)
        
        return {
            "query": query,
            "suggestions": suggestions[:limit],
            "source": "local",
            "success": True
        }


# Global singleton instance
suggestion_service = SuggestionService()
