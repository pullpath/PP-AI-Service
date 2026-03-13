# Cache Management - Quick Reference

## 🚀 What's New

You now have **full control** over your dictionary cache with:

1. ✅ **List all cached words** with their sections
2. ✅ **Delete specific sections** (e.g., only bilibili_videos)
3. ✅ **Delete entire words**
4. ✅ **Visual cache manager UI** at `/cache-manager`
5. ✅ **CLI script** for manual cache management

---

## 📋 Quick Access

### Web UI (Easiest)
```
http://localhost:8000/cache-manager
```

Beautiful interface to:
- View all cached words
- See which sections are cached
- Delete individual sections or entire words
- View cache statistics
- Sort and paginate results

### CLI Script
```bash
# View stats
python reset_cache.py --stats

# Reset entire cache
python reset_cache.py --force

# Reset specific word
python reset_cache.py --word hello --force
```

---

## 🔧 API Endpoints

### 1. List Cached Words
```bash
# Default (last 100 words, sorted by last accessed)
curl http://localhost:8000/api/dictionary/cache/words

# Pagination
curl "http://localhost:8000/api/dictionary/cache/words?limit=20&offset=0"

# Sort by word name
curl "http://localhost:8000/api/dictionary/cache/words?sort_by=word"
```

**Response Example:**
```json
{
  "status": "ok",
  "data": {
    "words": [
      {
        "word": "hello",
        "sections": {
          "basic": "fresh",
          "etymology[0]": "fresh",
          "bilibili_videos[0]": "fresh"
        },
        "created_at": "2026-02-28 17:24:33",
        "last_accessed_at": "2026-02-28 17:24:33"
      }
    ],
    "total": 15,
    "has_more": false
  }
}
```

### 2. Delete Specific Section
```bash
# Delete bilibili_videos
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=bilibili_videos"

# Delete etymology for specific entry
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=etymology&entry_index=0"

# Delete detailed_sense for specific entry and sense
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=detailed_sense&entry_index=0&sense_index=0"
```

### 3. Delete Entire Word
```bash
curl -X DELETE http://localhost:8000/api/dictionary/cache/hello
```

### 4. Clear All Cache
```bash
curl -X POST http://localhost:8000/api/dictionary/cache/clear
```

### 5. Get Statistics
```bash
curl http://localhost:8000/api/dictionary/cache/stats
```

---

## 📝 Section Names Reference

### Basic Section
- `basic` - Word structure and pronunciation

### Entry-Level Sections (require entry_index)
- `etymology` - Word origin
- `word_family` - Related words
- `usage_context` - Modern usage
- `cultural_notes` - Cultural information
- `frequency` - Usage frequency
- `bilibili_videos` - Educational videos

### Sense-Level Sections (require entry_index + sense_index)
- `detailed_sense` - Detailed definition
- `examples` - Usage examples
- `usage_notes` - Usage guidance

---

## 💡 Frontend Integration Examples

### JavaScript/Fetch
```javascript
// List cached words
const response = await fetch('/api/dictionary/cache/words');
const data = await response.json();
console.log(data.data.words);

// Delete specific section
await fetch('/api/dictionary/cache/hello/section?section=bilibili_videos', {
  method: 'DELETE'
});

// Delete entire word
await fetch('/api/dictionary/cache/hello', {
  method: 'DELETE'
});
```

### jQuery
```javascript
// List cached words
$.get('/api/dictionary/cache/words', function(data) {
  data.data.words.forEach(word => {
    console.log(word.word, word.sections);
  });
});

// Delete section
$.ajax({
  url: '/api/dictionary/cache/hello/section?section=bilibili_videos',
  method: 'DELETE',
  success: function(data) {
    alert(data.message);
  }
});
```

### React Hook
```jsx
function useCachedWords() {
  const [words, setWords] = useState([]);
  const [loading, setLoading] = useState(true);
  
  const loadWords = async () => {
    setLoading(true);
    const res = await fetch('/api/dictionary/cache/words');
    const data = await res.json();
    setWords(data.data.words);
    setLoading(false);
  };
  
  const deleteSection = async (word, section) => {
    await fetch(`/api/dictionary/cache/${word}/section?section=${section}`, {
      method: 'DELETE'
    });
    loadWords(); // Refresh list
  };
  
  const deleteWord = async (word) => {
    await fetch(`/api/dictionary/cache/${word}`, {
      method: 'DELETE'
    });
    loadWords(); // Refresh list
  };
  
  useEffect(() => { loadWords(); }, []);
  
  return { words, loading, deleteSection, deleteWord, refresh: loadWords };
}
```

---

## 🎯 Common Use Cases

### 1. Remove outdated video links
```bash
# Remove only bilibili_videos for a specific word
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=bilibili_videos"
```

### 2. Free up space by removing old words
```bash
# List all words, pick old ones, delete them
curl http://localhost:8000/api/dictionary/cache/words?sort_by=last_accessed

# Delete specific old word
curl -X DELETE http://localhost:8000/api/dictionary/cache/old-word
```

### 3. Refresh specific data without losing everything
```bash
# Delete just etymology section, keep everything else
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=etymology"

# Next lookup will fetch fresh etymology, keep other cached sections
```

### 4. Clean up before deploying new version
```bash
# Reset entire cache
python reset_cache.py --force

# Or via API
curl -X POST http://localhost:8000/api/dictionary/cache/clear
```

---

## 📊 Cache Manager UI Features

Access at: `http://localhost:8000/cache-manager`

### Features:
- ✅ **Live statistics** (total words, hit rate, cache hits)
- ✅ **Searchable word list** with all sections
- ✅ **Section badges** showing cache status (fresh/stale)
- ✅ **One-click section deletion** (× button on each section)
- ✅ **One-click word deletion** (Delete All button)
- ✅ **Pagination** for large caches
- ✅ **Sorting** (by last accessed, word name, created date)
- ✅ **Auto-refresh stats** every 30 seconds

### Screenshots:
- **Stats Cards**: Total words, hit rate, cache hits
- **Word Cards**: Each word shows all cached sections
- **Section Badges**: Click × to delete individual sections
- **Controls**: Sort, filter, pagination, clear all

---

## 🔒 Admin Endpoints (Require Authentication)

Set `ADMIN_TOKEN` in `.env` file:
```env
ADMIN_TOKEN=your_secure_token_here
```

### Admin-Only Features:
```bash
# Reset entire database
curl -X POST http://localhost:8000/api/admin/cache/reset \
  -H "X-Admin-Token: your_token"

# Vacuum database (reclaim space)
curl -X POST http://localhost:8000/api/admin/cache/vacuum \
  -H "X-Admin-Token: your_token"

# Detailed stats with top words
curl http://localhost:8000/api/admin/cache/stats \
  -H "X-Admin-Token: your_token"
```

---

## 📖 Full Documentation

- **Complete Guide**: `docs/CACHE_MANAGEMENT.md`
- **Cache Service Code**: `ai_svc/dictionary/cache_service.py`
- **API Endpoints**: See `app.py` for all routes

---

## 🎉 Summary

You now have **3 ways** to manage cache:

1. **Web UI** (`/cache-manager`) - Visual, user-friendly
2. **API Endpoints** - Programmatic access for frontend
3. **CLI Script** (`reset_cache.py`) - Manual/automation

All with **granular control**:
- Delete by word
- Delete by section
- Delete specific entry/sense
- Or clear everything

**Ready to use!** Just start your server and visit `/cache-manager` 🚀
