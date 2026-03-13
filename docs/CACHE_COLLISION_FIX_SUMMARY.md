# Cache Collision Fix Summary

## Problem Statement

**Bug**: When frontend requests sections sequentially (`basic` → `frequency` → `etymology` → ... → `common_phrases`), the `common_phrases` section returns `basic` section data instead of phrases.

**Root Cause**: Cache collision in `cache_service.py` where `common_phrases` reads/writes to the `basic_data` column instead of having its own dedicated column.

## Solution Overview

Added dedicated database columns and cache methods for `common_phrases` section to prevent collision with `basic` section data.

## Files Modified

### 1. `ai_svc/dictionary/cache_service.py`

#### Database Schema Changes
- **Added 3 new columns to `word_cache` table**:
  ```sql
  common_phrases_data TEXT
  common_phrases_updated_at INTEGER
  common_phrases_status TEXT DEFAULT 'empty'
  ```

#### New Methods
- `_migrate_add_common_phrases_columns()` - Auto-migration on service startup
- `get_common_phrases(word)` - Read common_phrases from dedicated column
- `set_common_phrases(word, data, status)` - Write common_phrases to dedicated column

#### Updated Methods
1. **`_make_cache_key()`** (line ~303)
   - Added `common_phrases` branch to return `{word}:common_phrases` key

2. **`invalidate_word_section()`** (line ~685-693)
   - Added `common_phrases` case to invalidate dedicated columns

3. **`list_cached_words()`** (line ~770-780)
   - Added query for `common_phrases_status` from word_cache
   - Include `common_phrases` in sections summary

4. **`get_word_details()`** (line ~837-844, ~969-983)
   - Added `common_phrases_status` and `common_phrases_data` to SELECT query
   - Parse and include `common_phrases` in response

5. **`lookup_with_cache()`** (3 locations)
   - **Read logic** (line ~1041): `cached = self.get_common_phrases(word)`
   - **Write logic** (line ~1112): `self.set_common_phrases(word, result)`
   - **In-flight coordination** (line ~1148): Uses correct cache key

#### Configuration
- Added `common_phrases: 30 * 24 * 3600` to `FIELD_TTL` dict (30 days TTL)

### 2. `static/cache_manager.html`

✅ Already completed in previous session - no additional changes needed

- Added `renderCommonPhrases()` function
- Updated `renderWordItem()` to display common_phrases section
- Added delete handler for common_phrases
- Shows phrase count badge and expandable phrase list

### 3. `test_cache_collision.py` (NEW)

Created comprehensive test script to verify the fix:
- **Test 1**: Sequential request pattern (reproduces original bug scenario)
- **Test 2**: Separate caching verification (ensures both sections cache independently)

## API Changes (Frontend Impact)

### No Breaking Changes ✅

The `common_phrases` section API remains **identical** to before:

```bash
# Request common_phrases section (unchanged)
POST /api/dictionary
{
  "word": "hello",
  "section": "common_phrases"
}

# Response format (unchanged)
{
  "common_phrases": [
    {
      "phrase": "hello world",
      "translation": "你好世界",
      "explanation": "A traditional first program..."
    },
    ...
  ],
  "cache_hit": true,
  "request_duration_ms": 150
}
```

### Internal Changes (No Frontend Action Required)

1. **Cache storage**: `common_phrases` now stored in dedicated `common_phrases_data` column (was incorrectly stored in `basic_data`)
2. **Cache keys**: Uses `{word}:common_phrases` key (was using `{word}:basic` key)
3. **Cache invalidation**: Can independently invalidate `common_phrases` without affecting `basic`

### Frontend Compatibility

✅ **Fully backward compatible** - frontend code requires **no changes**

- Same request format
- Same response format
- Same section name: `"common_phrases"`
- Cache behavior now correct (no more collision)

## Migration

### Auto-Migration on Startup

The migration runs automatically when `CacheService` initializes:

```python
def _migrate_add_common_phrases_columns(self, conn):
    """Add common_phrases columns if they don't exist"""
    cursor = conn.execute("PRAGMA table_info(word_cache)")
    columns = {row[1] for row in cursor.fetchall()}
    
    if 'common_phrases_data' not in columns:
        logger.info("Migrating: Adding common_phrases columns to word_cache...")
        conn.execute("""
            ALTER TABLE word_cache ADD COLUMN common_phrases_data TEXT
        """)
        conn.execute("""
            ALTER TABLE word_cache ADD COLUMN common_phrases_updated_at INTEGER
        """)
        conn.execute("""
            ALTER TABLE word_cache ADD COLUMN common_phrases_status TEXT DEFAULT 'empty'
        """)
        logger.info("Migration complete: common_phrases columns added")
```

### Zero Downtime

- Migration runs on first service startup after deployment
- Existing cache data preserved
- No manual database operations required
- No service restart needed

## Testing

### Manual Testing Steps

1. **Start the Flask server**:
   ```bash
   python app.py
   ```

2. **Run the test script**:
   ```bash
   python test_cache_collision.py
   ```

3. **Expected output**:
   ```
   ✅ Basic request successful
   ✅ Common phrases request successful
   ✅ common_phrases section returned phrases (6 phrases)
   ✅ Both sections cached separately
   🎉 All tests passed! Cache collision fix verified.
   ```

### Frontend Testing

1. Open your frontend application
2. Search for a word (e.g., "hello")
3. Load sections sequentially: `basic` → `frequency` → `etymology` → ... → `common_phrases`
4. **Verify**: `common_phrases` section shows actual phrases (not basic data)
5. **Verify**: Cache manager shows both `basic` and `common_phrases` sections separately

## Verification Checklist

- [x] Database migration code added
- [x] Dedicated cache methods (`get_common_phrases`, `set_common_phrases`)
- [x] Cache key generation updated
- [x] Read logic updated (3 locations)
- [x] Write logic updated
- [x] Invalidation logic updated
- [x] `list_cached_words()` includes `common_phrases`
- [x] `get_word_details()` includes `common_phrases`
- [x] Test script created
- [x] Cache manager UI updated (previous session)
- [x] No breaking API changes

## Deployment Steps

1. **Pull latest code**:
   ```bash
   git pull origin main
   ```

2. **Restart Flask service**:
   ```bash
   ./stop.sh && ./start.sh
   # or
   docker compose down && docker compose up -d
   ```

3. **Verify migration**:
   - Check logs for "Migration complete: common_phrases columns added"
   - Run test script: `python test_cache_collision.py`

4. **Monitor**:
   - Check Flask logs for any errors
   - Test frontend sequential loading
   - Verify cache manager displays both sections

## Rollback Plan

If issues occur, revert with:

```bash
git revert <commit-hash>
./stop.sh && ./start.sh
```

**Note**: Cache database will retain new columns (harmless) but service will not use them.

## Performance Impact

- **Negligible**: Added 3 columns to existing table
- **No additional queries**: Same query pattern as other sections
- **No schema changes**: Additive only (ALTER TABLE ADD COLUMN)
- **Cache efficiency**: Improved (no collision, correct invalidation)

## Related Issues

- **Issue**: Cache collision between `basic` and `common_phrases`
- **Symptom**: Frontend sequential loading returns wrong data
- **Fix**: Dedicated cache storage for `common_phrases`

## Future Improvements

1. Add cache metrics for `common_phrases` section
2. Consider adding cache version field for easier migrations
3. Add integration tests for all section cache operations

---

**Author**: AI Assistant  
**Date**: 2026-03-13  
**Status**: ✅ Complete - Ready for Testing
