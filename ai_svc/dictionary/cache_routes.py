"""
Flask Blueprint for dictionary cache management routes

This module handles all cache-related API endpoints including:
- Cache statistics and metrics
- Cache invalidation (word-level and section-level)
- Cache listing and pagination
- Admin endpoints (reset, vacuum, detailed stats)
- Background cache refresh
"""

from flask import Blueprint, jsonify, request
import os
import logging
import time
import secrets
from typing import Optional

from .cache_service import cache_service

# Create Blueprint
cache_bp = Blueprint('cache', __name__, url_prefix='/api/dictionary/cache')

# ============================================================
# ADMIN TOKEN MANAGEMENT
# ============================================================

# Global variable to store auto-generated admin token (persistent for server lifetime)
_AUTO_GENERATED_TOKEN = None

def get_admin_token() -> str:
    """
    Get admin token from environment or generate a persistent one.
    
    Returns the same auto-generated token for the entire server lifetime
    if ADMIN_TOKEN is not set in .env
    """
    global _AUTO_GENERATED_TOKEN
    
    admin_token = os.getenv('ADMIN_TOKEN')
    
    # Use token from .env if set
    if admin_token:
        return admin_token
    
    # Generate persistent token for development (only once)
    if not _AUTO_GENERATED_TOKEN:
        _AUTO_GENERATED_TOKEN = secrets.token_urlsafe(32)
        logging.warning(f"⚠️  No ADMIN_TOKEN set. Using auto-generated token: {_AUTO_GENERATED_TOKEN}")
        logging.warning("   Add this to your .env file: ADMIN_TOKEN=" + _AUTO_GENERATED_TOKEN)
    
    return _AUTO_GENERATED_TOKEN


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def check_admin_auth() -> bool:
    """
    Check if request has valid admin token.
    Token can be provided via:
    - Header: X-Admin-Token
    - Query param: admin_token
    
    Set ADMIN_TOKEN in .env file (generates persistent random token if not set)
    """
    admin_token = get_admin_token()  # Get persistent token
    logging.info(f"Checking admin auth. Expected token: {admin_token}")
    
    # Check header
    provided_token = request.headers.get('X-Admin-Token')
    logging.info(f"Provided token from header: {provided_token}")
    
    # Check query param (fallback)
    if not provided_token:
        provided_token = request.args.get('admin_token')
        logging.info(f"Provided token from query param: {provided_token}")
    
    return provided_token == admin_token


def refresh_cache_background(word: str, section: str, entry_index: Optional[int] = None, 
                             sense_index: Optional[int] = None):
    """
    Background refresh for stale cache entries (non-blocking)
    Called by ThreadPoolExecutor when serving stale data
    
    This function must be importable by app.py for the dictionary_lookup endpoint
    """
    from . import dictionary_service  # Import here to avoid circular dependency
    
    try:
        logging.info(f"[{word}] Background refresh: {section}")
        
        # Fetch fresh data from service
        result = dictionary_service.lookup_section(word, section, sense_index, entry_index)
        
        # Update cache on success
        if result.get('success'):
            if section == 'basic':
                cache_service.set_basic(word, result)
            elif section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']:
                if entry_index is not None:
                    cache_service.set_entry_section(word, entry_index, section, result)
            elif section in ['detailed_sense', 'examples', 'usage_notes']:
                if entry_index is not None and sense_index is not None:
                    cache_service.set_sense_section(word, entry_index, sense_index, section, result)
            
            cache_service.metrics.record_refresh()
            logging.info(f"[{word}] Background refresh completed: {section}")
        else:
            logging.warning(f"[{word}] Background refresh failed: {result.get('error', 'unknown')}")
    
    except Exception as e:
        logging.error(f"[{word}] Background refresh error: {e}")


# ============================================================
# PUBLIC CACHE ENDPOINTS
# ============================================================



@cache_bp.route('/stats', methods=['GET'])
def get_stats():
    """
    Get cache statistics and performance metrics
    """
    metrics = cache_service.get_stats()
    return jsonify({
        "status": "ok",
        "metrics": metrics
    }), 200


@cache_bp.route('/clear', methods=['POST'])
def clear_cache():
    """
    Clear all cache entries
    
    Requires admin authentication via X-Admin-Token header or admin_token query param.
    """
    # Check admin authentication
    if not check_admin_auth():
        return jsonify({
            "status": "error",
            "message": "Unauthorized. Provide valid admin token via X-Admin-Token header or admin_token query param."
        }), 401
    
    try:
        cache_service.clear_all()
        return jsonify({
            "status": "ok",
            "message": "Cache cleared successfully"
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@cache_bp.route('/<word>', methods=['DELETE'])
def invalidate_word(word: str):
    """
    Invalidate cache for a specific word
    
    Requires admin authentication via X-Admin-Token header or admin_token query param.
    """
    # Check admin authentication
    if not check_admin_auth():
        return jsonify({
            "status": "error",
            "message": "Unauthorized. Provide valid admin token via X-Admin-Token header or admin_token query param."
        }), 401
    
    try:
        cache_service.invalidate_word(word)
        return jsonify({
            "status": "ok",
            "message": f"Cache invalidated for word: {word}"
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@cache_bp.route('/words', methods=['GET'])
def list_words():
    """
    List all cached words with their section information
    
    Query params:
        - limit: Max words to return (default: 100)
        - offset: Pagination offset (default: 0)
        - sort_by: Sort field - 'last_accessed' (default), 'word', 'created_at'
    
    Response:
        {
            "status": "ok",
            "data": {
                "words": [
                    {
                        "word": "hello",
                        "sections": {
                            "basic": "fresh",
                            "etymology[0]": "fresh",
                            "bilibili_videos[0]": "fresh",
                            "detailed_sense[0,0]": "fresh"
                        },
                        "created_at": "2026-02-28 17:24:33",
                        "last_accessed_at": "2026-02-28 17:24:33"
                    }
                ],
                "total": 15,
                "limit": 100,
                "offset": 0,
                "has_more": false
            }
        }
    """
    try:
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        sort_by = request.args.get('sort_by', 'last_accessed')
        
        # Validate inputs
        if limit < 1 or limit > 500:
            return jsonify({
                "status": "error",
                "message": "Limit must be between 1 and 500"
            }), 400
        
        if offset < 0:
            return jsonify({
                "status": "error",
                "message": "Offset must be non-negative"
            }), 400
        
        if sort_by not in ['last_accessed', 'word', 'created_at']:
            return jsonify({
                "status": "error",
                "message": "Invalid sort_by. Use: last_accessed, word, or created_at"
            }), 400
        
        result = cache_service.list_cached_words(limit=limit, offset=offset, sort_by=sort_by)
        
        return jsonify({
            "status": "ok",
            "data": result
        }), 200
    except Exception as e:
        logging.error(f"Error listing cached words: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@cache_bp.route('/<word>/section', methods=['DELETE'])
def invalidate_section(word: str):
    """
    Invalidate specific section cache for a word
    
    Requires admin authentication via X-Admin-Token header or admin_token query param.
    
    Query params:
        - section: Section name (required)
        - entry_index: Entry index (optional, for entry-level sections)
        - sense_index: Sense index (optional, for sense-level sections)
    
    Examples:
        DELETE /api/dictionary/cache/hello/section?section=basic
        DELETE /api/dictionary/cache/hello/section?section=etymology&entry_index=0
        DELETE /api/dictionary/cache/hello/section?section=bilibili_videos
        DELETE /api/dictionary/cache/hello/section?section=detailed_sense&entry_index=0&sense_index=0
    
    Response:
        {
            "status": "ok",
            "message": "Section cache invalidated: hello - etymology (entry 0)"
        }
    """
    # Check admin authentication
    if not check_admin_auth():
        return jsonify({
            "status": "error",
            "message": "Unauthorized. Provide valid admin token via X-Admin-Token header or admin_token query param."
        }), 401
    
    try:
        section = request.args.get('section')
        if not section:
            return jsonify({
                "status": "error",
                "message": "Missing required parameter: section"
            }), 400
        
        entry_index = request.args.get('entry_index')
        sense_index = request.args.get('sense_index')
        
        # Convert to int if provided
        if entry_index is not None:
            try:
                entry_index = int(entry_index)
            except ValueError:
                return jsonify({
                    "status": "error",
                    "message": "entry_index must be an integer"
                }), 400
        
        if sense_index is not None:
            try:
                sense_index = int(sense_index)
            except ValueError:
                return jsonify({
                    "status": "error",
                    "message": "sense_index must be an integer"
                }), 400
        
        # Validate section name
        valid_sections = ['basic', 'etymology', 'word_family', 'usage_context', 'cultural_notes', 
                         'frequency', 'bilibili_videos', 'detailed_sense', 'examples', 'usage_notes']
        if section not in valid_sections:
            return jsonify({
                "status": "error",
                "message": f"Invalid section. Valid sections: {', '.join(valid_sections)}"
            }), 400
        
        # Auto-default entry_index for entry-level sections if not provided
        if section in ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']:
            if entry_index is None:
                entry_index = 0
        
        cache_service.invalidate_word_section(word, section, entry_index, sense_index)
        
        # Build message
        msg = f"Section cache invalidated: {word} - {section}"
        if entry_index is not None:
            msg += f" (entry {entry_index})"
        if sense_index is not None:
            msg += f", sense {sense_index}"
        
        return jsonify({
            "status": "ok",
            "message": msg
        }), 200
    except Exception as e:
        logging.error(f"Error invalidating section cache: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@cache_bp.route('/<word>/phrase/<phrase>', methods=['DELETE'])
def invalidate_phrase_videos(word: str, phrase: str):
    """
    Invalidate phrase-specific video cache
    
    Requires admin authentication.
    
    Example:
        DELETE /api/dictionary/cache/hello/phrase/hello%20world
    
    Response:
        {
            "status": "ok",
            "message": "Phrase videos deleted: hello - hello world"
        }
    """
    if not check_admin_auth():
        return jsonify({
            "status": "error",
            "message": "Unauthorized"
        }), 401
    
    try:
        with cache_service._write_lock:
            conn = cache_service._read_connection()
            try:
                normalized = cache_service._normalize_word(word)
                conn.execute("DELETE FROM phrase_cache WHERE word = ? AND phrase = ?", (normalized, phrase))
                conn.commit()
                
                return jsonify({
                    "status": "ok",
                    "message": f"Phrase videos deleted: {word} - {phrase}"
                }), 200
            finally:
                conn.close()
    except Exception as e:
        logging.error(f"Error deleting phrase videos: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@cache_bp.route('/words/<word>/details', methods=['GET'])
def get_word_details(word: str):
    """
    Get detailed cache information for a specific word
    
    Returns entries, sections, and individual video information
    """
    try:
        details = cache_service.get_word_details(word)
        
        if not details:
            return jsonify({
                "status": "error",
                "message": f"Word '{word}' not found in cache"
            }), 404
        
        return jsonify({
            "status": "ok",
            "data": details
        }), 200
    except Exception as e:
        logging.error(f"Error getting word details: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================
# ADMIN ENDPOINTS (Protected by admin token)
# ============================================================

@cache_bp.route('/admin/reset', methods=['POST'])
def admin_reset():
    """
    Admin endpoint: Reset entire cache database
    
    Requires authentication via X-Admin-Token header or admin_token query param.
    Set ADMIN_TOKEN in .env file.
    
    Returns:
        - 200: Success with deleted counts
        - 401: Unauthorized (missing/invalid token)
        - 500: Server error
    """
    if not check_admin_auth():
        return jsonify({
            "status": "error",
            "message": "Unauthorized. Provide valid admin token via X-Admin-Token header or admin_token query param."
        }), 401
    
    try:
        # Get stats before clearing
        stats = cache_service.get_stats()
        total_words = stats['database']['total_words']
        total_entries = stats['database']['total_entries']
        total_senses = stats['database']['total_senses']
        
        # Clear all cache
        cache_service.clear_all()
        
        logging.info(f"Admin cache reset: {total_words} words, {total_entries} entries, {total_senses} senses deleted")
        
        return jsonify({
            "status": "ok",
            "message": "Cache reset successful",
            "deleted": {
                "words": total_words,
                "entries": total_entries,
                "senses": total_senses
            }
        }), 200
    except Exception as e:
        logging.error(f"Error in admin cache reset: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@cache_bp.route('/admin/vacuum', methods=['POST'])
def admin_vacuum():
    """
    Admin endpoint: Vacuum/optimize SQLite database
    
    This reclaims unused space and optimizes database performance.
    Run this after deleting large amounts of data.
    
    Requires authentication via X-Admin-Token header or admin_token query param.
    """
    if not check_admin_auth():
        return jsonify({
            "status": "error",
            "message": "Unauthorized. Provide valid admin token via X-Admin-Token header or admin_token query param."
        }), 401
    
    try:
        import sqlite3
        
        # Get size before
        size_before = os.path.getsize(cache_service.db_path) / 1024 / 1024  # MB
        
        # Vacuum database
        conn = sqlite3.connect(cache_service.db_path)
        conn.execute("VACUUM")
        conn.close()
        
        # Get size after
        size_after = os.path.getsize(cache_service.db_path) / 1024 / 1024  # MB
        space_saved = size_before - size_after
        
        logging.info(f"Admin cache vacuum: {space_saved:.2f} MB reclaimed")
        
        return jsonify({
            "status": "ok",
            "message": "Database vacuumed successfully",
            "size_before_mb": round(size_before, 2),
            "size_after_mb": round(size_after, 2),
            "space_saved_mb": round(space_saved, 2)
        }), 200
    except Exception as e:
        logging.error(f"Error in admin cache vacuum: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@cache_bp.route('/admin/stats', methods=['GET'])
def admin_detailed_stats():
    """
    Admin endpoint: Get detailed cache statistics including top words
    
    Requires authentication via X-Admin-Token header or admin_token query param.
    """
    if not check_admin_auth():
        return jsonify({
            "status": "error",
            "message": "Unauthorized. Provide valid admin token via X-Admin-Token header or admin_token query param."
        }), 401
    
    try:
        import sqlite3
        
        stats = cache_service.get_stats()
        
        # Add top cached words
        conn = sqlite3.connect(cache_service.db_path)
        cursor = conn.execute("""
            SELECT word, datetime(last_accessed_at, 'unixepoch', 'localtime') as last_access
            FROM word_cache
            ORDER BY last_accessed_at DESC
            LIMIT 20
        """)
        top_words = [{'word': row[0], 'last_accessed': row[1]} for row in cursor.fetchall()]
        conn.close()
        
        # Database file size
        db_size_mb = os.path.getsize(cache_service.db_path) / 1024 / 1024
        
        return jsonify({
            "status": "ok",
            "stats": stats,
            "top_words": top_words,
            "db_size_mb": round(db_size_mb, 2),
            "db_path": cache_service.db_path
        }), 200
    except Exception as e:
        logging.error(f"Error fetching admin stats: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
