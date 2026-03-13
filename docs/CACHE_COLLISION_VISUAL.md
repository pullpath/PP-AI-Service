# Cache Collision Bug - Visual Explanation

## Before Fix (Bug Present)

```
┌─────────────────────────────────────────────────────┐
│              word_cache table                       │
├─────────────────────────────────────────────────────┤
│ word         │ basic_data    │ basic_updated_at    │
│ "hello"      │ {...}         │ 1234567890          │
└─────────────────────────────────────────────────────┘
              ↑                ↑
              │                │
              │                │
    ┌─────────┴────────┐      ┌┴─────────────────┐
    │   basic section  │      │ common_phrases   │
    │   GET request    │      │ GET request      │
    └──────────────────┘      └──────────────────┘
              ↓                       ↓
    Writes basic data        ❌ OVERWRITES basic data
    to basic_data           (Should write phrases,
                            but uses same column!)

Result: common_phrases request returns basic data ❌
```

## After Fix (Correct Behavior)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         word_cache table                                   │
├────────────────────────────────────────────────────────────────────────────┤
│ word    │ basic_data    │ basic_updated_at │ common_phrases_data │ common_phrases_updated_at │
│ "hello" │ {...entries}  │ 1234567890       │ {...phrases}        │ 1234567891                │
└────────────────────────────────────────────────────────────────────────────┘
           ↑                                   ↑
           │                                   │
           │                                   │
    ┌──────┴───────┐                   ┌──────┴────────────┐
    │   basic      │                   │ common_phrases    │
    │   section    │                   │ section           │
    │   GET        │                   │ GET               │
    └──────────────┘                   └───────────────────┘
           ↓                                   ↓
    Writes basic data             ✅ Writes phrases data
    to basic_data                to common_phrases_data
    (entries, definitions)        (common phrases list)

Result: Both sections cached independently ✅
```

## Cache Method Mapping

### Before Fix (Collision)

```python
# Both sections used the SAME methods! ❌

section = 'basic'
cached = self.get_basic(word)           # Reads basic_data column
self.set_basic(word, result)            # Writes basic_data column

section = 'common_phrases'  
cached = self.get_basic(word)           # ❌ Reads basic_data column (WRONG!)
self.set_basic(word, result)            # ❌ Writes basic_data column (WRONG!)
```

### After Fix (Separate Storage)

```python
# Each section has dedicated methods ✅

section = 'basic'
cached = self.get_basic(word)                  # Reads basic_data column
self.set_basic(word, result)                   # Writes basic_data column

section = 'common_phrases'
cached = self.get_common_phrases(word)         # ✅ Reads common_phrases_data column
self.set_common_phrases(word, result)          # ✅ Writes common_phrases_data column
```

## Frontend Request Flow (Sequential Loading)

### Bug Scenario (Before Fix)

```
Frontend sends requests in sequence:
1. POST /api/dictionary {"word": "hello", "section": "basic"}
   → Caches to basic_data column ✅
   
2. POST /api/dictionary {"word": "hello", "section": "frequency"}
   → Caches to entry_cache ✅
   
3. POST /api/dictionary {"word": "hello", "section": "etymology"}
   → Caches to entry_cache ✅
   
4. POST /api/dictionary {"word": "hello", "section": "common_phrases"}
   → ❌ Reads from basic_data column (gets basic data instead of phrases!)
   → ❌ Overwrites basic_data with phrases (corrupts basic cache!)
```

### Fixed Behavior (After Fix)

```
Frontend sends requests in sequence:
1. POST /api/dictionary {"word": "hello", "section": "basic"}
   → Caches to basic_data column ✅
   
2. POST /api/dictionary {"word": "hello", "section": "frequency"}
   → Caches to entry_cache ✅
   
3. POST /api/dictionary {"word": "hello", "section": "etymology"}
   → Caches to entry_cache ✅
   
4. POST /api/dictionary {"word": "hello", "section": "common_phrases"}
   → ✅ Reads from common_phrases_data column (independent storage)
   → ✅ Writes to common_phrases_data column (no collision)
```

## Database Schema Change

### Migration SQL

```sql
-- Auto-executed on service startup
ALTER TABLE word_cache ADD COLUMN common_phrases_data TEXT;
ALTER TABLE word_cache ADD COLUMN common_phrases_updated_at INTEGER;
ALTER TABLE word_cache ADD COLUMN common_phrases_status TEXT DEFAULT 'empty';
```

### Result

```
word_cache table columns:
├── word (TEXT, PRIMARY KEY)
├── created_at (INTEGER)
├── last_accessed_at (INTEGER)
├── basic_data (TEXT) ────────────────┐
├── basic_updated_at (INTEGER)        │ ✅ Separate storage
├── basic_status (TEXT)               │    for basic section
└── ──────────────────────────────────┘
├── common_phrases_data (TEXT) ───────┐
├── common_phrases_updated_at (INT)   │ ✅ Separate storage
└── common_phrases_status (TEXT)      │    for common_phrases
    ──────────────────────────────────┘
```

## Key Insight

The bug occurred because `common_phrases` is a **word-level section** (like `basic`), but the code treated it as an entry-level section and fell back to using `basic` cache methods.

**Word-level sections** (apply to entire word):
- `basic` → stores in `basic_data` ✅
- `common_phrases` → NOW stores in `common_phrases_data` ✅ (was using `basic_data` ❌)

**Entry-level sections** (apply to each entry/meaning):
- `etymology`, `word_family`, `usage_context`, etc. → store in `entry_cache` ✅

**Sense-level sections** (apply to each sense/definition):
- `detailed_sense`, `examples`, `usage_notes` → store in `sense_cache` ✅

## Testing The Fix

```bash
# 1. Clear cache
curl -X POST http://localhost:8000/api/dictionary/cache/clear

# 2. Request basic (caches to basic_data)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"basic"}'

# 3. Request common_phrases (should cache to common_phrases_data, not overwrite basic_data)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"common_phrases"}'

# Expected: common_phrases returns phrases (not basic data) ✅
```

---

**Status**: ✅ Fixed - Dedicated cache storage prevents collision
