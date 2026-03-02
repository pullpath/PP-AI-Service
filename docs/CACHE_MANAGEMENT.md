# Cache Management Guide

This guide covers how to manage the dictionary cache database using both CLI scripts and admin API endpoints.

## Table of Contents
- [CLI Script Usage](#cli-script-usage)
- [Admin API Endpoints](#admin-api-endpoints)
- [Authentication Setup](#authentication-setup)
- [Frontend Integration](#frontend-integration)

---

## CLI Script Usage

### Basic Usage

```bash
# Show cache statistics
python reset_cache.py --stats

# Reset entire cache (interactive)
python reset_cache.py

# Reset entire cache (skip confirmation)
python reset_cache.py --force

# Reset specific word only
python reset_cache.py --word hello

# Reset specific word (skip confirmation)
python reset_cache.py --word hello --force
```

### Examples

**Show current cache stats:**
```bash
$ python reset_cache.py --stats

📊 Cache Statistics:
   Total words: 15
   Total entries: 20
   Total senses: 45
   Database size: 0.12 MB
   Database: /path/to/cache.db
   
   Cache hit rate: 78.5%
   Total requests: 142
   Cache hits: 111
   Cache misses: 31
```

**Interactive reset (with confirmation):**
```bash
$ python reset_cache.py

⚠️  WARNING: This will delete ALL cached dictionary data!
   Database: /path/to/cache.db

   Continue? (yes/no): yes

✅ Cache reset successful!
   Deleted: 15 words, 20 entries, 45 senses
   Database: /path/to/cache.db
```

**Force reset (no confirmation):**
```bash
$ python reset_cache.py --force

✅ Cache reset successful!
   Deleted: 15 words, 20 entries, 45 senses
   Database: /path/to/cache.db
```

**Reset specific word:**
```bash
$ python reset_cache.py --word hello --force

✅ Cache invalidated for word: hello
```

---

## Public Cache Endpoints (No Authentication)

These endpoints are available to all users without authentication.

### 1. List Cached Words

**Get a list of all cached words with their section information**

```bash
# Basic usage
curl http://localhost:8000/api/dictionary/cache/words

# With pagination
curl "http://localhost:8000/api/dictionary/cache/words?limit=20&offset=0"

# Sort by word name
curl "http://localhost:8000/api/dictionary/cache/words?sort_by=word"

# Sort by creation time
curl "http://localhost:8000/api/dictionary/cache/words?sort_by=created_at"
```

**Query Parameters**:
- `limit`: Max words to return (default: 100, max: 500)
- `offset`: Pagination offset (default: 0)
- `sort_by`: Sort field - `last_accessed` (default), `word`, `created_at`

**Response**:
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
```

**Section Format**: `section_name[entry_index]` or `section_name[entry_index,sense_index]`

### 2. Delete Specific Section

**Delete only a specific section of a word's cache**

```bash
# Delete basic section
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=basic"

# Delete bilibili_videos (auto-defaults to entry_index=0)
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=bilibili_videos"

# Delete etymology for specific entry
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=etymology&entry_index=0"

# Delete detailed_sense for specific entry and sense
curl -X DELETE "http://localhost:8000/api/dictionary/cache/hello/section?section=detailed_sense&entry_index=0&sense_index=0"
```

**Query Parameters**:
- `section`: Section name (required) - see valid sections below
- `entry_index`: Entry index (optional, auto-defaults to 0 for entry-level sections)
- `sense_index`: Sense index (optional, required for sense-level sections)

**Valid Sections**:
- Basic: `basic`
- Entry-level: `etymology`, `word_family`, `usage_context`, `cultural_notes`, `frequency`, `bilibili_videos`
- Sense-level: `detailed_sense`, `examples`, `usage_notes`

**Response**:
```json
{
  "status": "ok",
  "message": "Section cache invalidated: hello - bilibili_videos (entry 0)"
}
```

### 3. Get Basic Statistics

**Get cache statistics and performance metrics**

```bash
curl http://localhost:8000/api/dictionary/cache/stats
```

**Response**:
```json
{
  "status": "ok",
  "metrics": {
    "database": {
      "total_words": 15,
      "total_entries": 20,
      "total_senses": 45
    },
    "in_memory_stats": {
      "cache_hit_rate": 0.785,
      "cache_hits": 111,
      "cache_misses": 31
    }
  }
}
```

### 4. Clear Entire Cache

**Delete all cache entries**

```bash
curl -X POST http://localhost:8000/api/dictionary/cache/clear
```

**Response**:
```json
{
  "status": "ok",
  "message": "Cache cleared successfully"
}
```

### 5. Delete Entire Word

**Delete all cached data for a specific word**

```bash
curl -X DELETE http://localhost:8000/api/dictionary/cache/hello
```

**Response**:
```json
{
  "status": "ok",
  "message": "Cache invalidated for word: hello"
}
```

---


## Admin API Endpoints

All admin endpoints require authentication via admin token.

### 1. Reset Entire Cache

**DELETE everything from cache database**

```bash
# Using header authentication (recommended)
curl -X POST http://localhost:8000/api/admin/cache/reset \
  -H "X-Admin-Token: your_admin_token_here"

# Using query parameter (for quick testing)
curl -X POST "http://localhost:8000/api/admin/cache/reset?admin_token=your_admin_token_here"
```

**Response:**
```json
{
  "status": "ok",
  "message": "Cache reset successful",
  "deleted": {
    "words": 15,
    "entries": 20,
    "senses": 45
  }
}
```

### 2. Vacuum Database

**Reclaim unused space and optimize performance** (run after large deletions)

```bash
curl -X POST http://localhost:8000/api/admin/cache/vacuum \
  -H "X-Admin-Token: your_admin_token_here"
```

**Response:**
```json
{
  "status": "ok",
  "message": "Database vacuumed successfully",
  "size_before_mb": 2.45,
  "size_after_mb": 1.83,
  "space_saved_mb": 0.62
}
```

### 3. Get Detailed Statistics

**Get comprehensive stats including top cached words**

```bash
curl -X GET http://localhost:8000/api/admin/cache/stats \
  -H "X-Admin-Token: your_admin_token_here"
```

**Response:**
```json
{
  "status": "ok",
  "stats": {
    "database": {
      "total_words": 15,
      "total_entries": 20,
      "total_senses": 45
    },
    "in_memory_stats": {
      "cache_hit_rate": 0.785,
      "cache_hits": 111,
      "cache_misses": 31
    }
  },
  "top_words": [
    {"word": "hello", "last_accessed": "2026-02-28 17:24:33"},
    {"word": "pipe", "last_accessed": "2026-02-28 17:23:53"}
  ],
  "db_size_mb": 0.12,
  "db_path": "/path/to/cache.db"
}
```

### 4. Existing Cache Endpoints (No Authentication Required)

These endpoints are already available and **do not require authentication**:

**Get basic statistics:**
```bash
curl http://localhost:8000/api/dictionary/cache/stats
```

**Clear entire cache:**
```bash
curl -X POST http://localhost:8000/api/dictionary/cache/clear
```

**Invalidate specific word:**
```bash
curl -X DELETE http://localhost:8000/api/dictionary/cache/hello
```

---

## Authentication Setup

### Step 1: Generate Admin Token

```bash
# Generate a secure random token
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Output example:
```
xK8p_ZqJ3mN7wH9vRt2YfL5nS6cA4dB1gE0jM
```

### Step 2: Add to .env File

```env
# Add this line to your .env file
ADMIN_TOKEN=xK8p_ZqJ3mN7wH9vRt2YfL5nS6cA4dB1gE0jM
```

### Step 3: Restart Server

```bash
# Stop existing server
./stop.sh

# Start with new token
./start.sh
```

### Development Mode (Auto-Generated Token)

If you **don't set** `ADMIN_TOKEN` in `.env`, the server will auto-generate a token on startup and print it to logs:

```
⚠️  No ADMIN_TOKEN set. Using auto-generated token: xK8p_ZqJ3mN7wH9vRt2YfL5nS6cA4dB1gE0jM
   Add this to your .env file: ADMIN_TOKEN=xK8p_ZqJ3mN7wH9vRt2YfL5nS6cA4dB1gE0jM
```

**⚠️ WARNING**: Auto-generated tokens change on every server restart. For production, always set a permanent token in `.env`.

---

## Frontend Integration

### Example: React Admin Panel

```jsx
import { useState } from 'react';

function AdminPanel() {
  const [adminToken, setAdminToken] = useState('');
  const [stats, setStats] = useState(null);

  const resetCache = async () => {
    const confirmed = window.confirm('Delete ALL cached data?');
    if (!confirmed) return;

    try {
      const response = await fetch('/api/admin/cache/reset', {
        method: 'POST',
        headers: {
          'X-Admin-Token': adminToken
        }
      });
      const data = await response.json();
      
      if (data.status === 'ok') {
        alert(`Cache reset! Deleted ${data.deleted.words} words`);
      } else {
        alert(`Error: ${data.message}`);
      }
    } catch (error) {
      alert(`Error: ${error.message}`);
    }
  };

  const vacuumDatabase = async () => {
    try {
      const response = await fetch('/api/admin/cache/vacuum', {
        method: 'POST',
        headers: {
          'X-Admin-Token': adminToken
        }
      });
      const data = await response.json();
      
      if (data.status === 'ok') {
        alert(`Database optimized! Saved ${data.space_saved_mb} MB`);
      } else {
        alert(`Error: ${data.message}`);
      }
    } catch (error) {
      alert(`Error: ${error.message}`);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch('/api/admin/cache/stats', {
        headers: {
          'X-Admin-Token': adminToken
        }
      });
      const data = await response.json();
      
      if (data.status === 'ok') {
        setStats(data);
      } else {
        alert(`Error: ${data.message}`);
      }
    } catch (error) {
      alert(`Error: ${error.message}`);
    }
  };

  return (
    <div className="admin-panel">
      <h2>Cache Admin Panel</h2>
      
      <div>
        <label>Admin Token:</label>
        <input 
          type="password" 
          value={adminToken} 
          onChange={(e) => setAdminToken(e.target.value)}
          placeholder="Enter admin token"
        />
      </div>
      
      <div className="actions">
        <button onClick={fetchStats}>Get Stats</button>
        <button onClick={resetCache} className="danger">Reset Cache</button>
        <button onClick={vacuumDatabase}>Vacuum DB</button>
      </div>
      
      {stats && (
        <div className="stats">
          <h3>Cache Statistics</h3>
          <p>Total words: {stats.stats.database.total_words}</p>
          <p>Database size: {stats.db_size_mb} MB</p>
          <p>Hit rate: {(stats.stats.in_memory_stats.cache_hit_rate * 100).toFixed(1)}%</p>
          
          <h4>Recently Accessed Words</h4>
          <ul>
            {stats.top_words.map(item => (
              <li key={item.word}>
                {item.word} - {item.last_accessed}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default AdminPanel;
```

### Example: Plain HTML/JavaScript

```html
<!DOCTYPE html>
<html>
<head>
    <title>Cache Admin</title>
    <style>
        .admin-panel { max-width: 800px; margin: 50px auto; padding: 20px; }
        button { margin: 5px; padding: 10px 20px; }
        .danger { background: #ff4444; color: white; }
        .stats { margin-top: 20px; padding: 15px; background: #f5f5f5; }
    </style>
</head>
<body>
    <div class="admin-panel">
        <h2>Cache Admin Panel</h2>
        
        <div>
            <label>Admin Token:</label>
            <input type="password" id="adminToken" placeholder="Enter admin token">
        </div>
        
        <div>
            <button onclick="fetchStats()">Get Stats</button>
            <button onclick="resetCache()" class="danger">Reset Cache</button>
            <button onclick="vacuumDB()">Vacuum DB</button>
        </div>
        
        <div id="stats" class="stats" style="display:none;"></div>
    </div>

    <script>
        const getToken = () => document.getElementById('adminToken').value;
        
        async function resetCache() {
            if (!confirm('Delete ALL cached data?')) return;
            
            const response = await fetch('/api/admin/cache/reset', {
                method: 'POST',
                headers: { 'X-Admin-Token': getToken() }
            });
            const data = await response.json();
            alert(data.message);
        }
        
        async function vacuumDB() {
            const response = await fetch('/api/admin/cache/vacuum', {
                method: 'POST',
                headers: { 'X-Admin-Token': getToken() }
            });
            const data = await response.json();
            if (data.status === 'ok') {
                alert(`Saved ${data.space_saved_mb} MB`);
            }
        }
        
        async function fetchStats() {
            const response = await fetch('/api/admin/cache/stats', {
                headers: { 'X-Admin-Token': getToken() }
            });
            const data = await response.json();
            
            if (data.status === 'ok') {
                const statsDiv = document.getElementById('stats');
                statsDiv.style.display = 'block';
                statsDiv.innerHTML = `
                    <h3>Cache Statistics</h3>
                    <p>Total words: ${data.stats.database.total_words}</p>
                    <p>Database size: ${data.db_size_mb} MB</p>
                    <p>Hit rate: ${(data.stats.in_memory_stats.cache_hit_rate * 100).toFixed(1)}%</p>
                    <h4>Top Words</h4>
                    <ul>
                        ${data.top_words.map(w => `<li>${w.word} - ${w.last_accessed}</li>`).join('')}
                    </ul>
                `;
            }
        }
    </script>
</body>
</html>
```

---

## Security Best Practices

### Production Deployment

1. **Use strong admin token** (32+ characters)
2. **Store token securely** in `.env` file (never commit to git)
3. **Use HTTPS only** in production (plain HTTP exposes token)
4. **Restrict admin endpoints** via firewall or reverse proxy:
   ```nginx
   # Nginx: Restrict admin endpoints to specific IPs
   location /api/admin/ {
       allow 192.168.1.0/24;  # Internal network
       deny all;
       proxy_pass http://localhost:8000;
   }
   ```

5. **Rotate tokens regularly** (every 90 days)
6. **Monitor admin actions** in logs

### Token Storage (Frontend)

**❌ Bad - Never do this:**
```javascript
// Hardcoded in source code
const ADMIN_TOKEN = 'xK8p_ZqJ3mN7wH9vRt2YfL5nS6cA4dB1gE0jM';  // INSECURE!
```

**✅ Good - Store securely:**
```javascript
// 1. User enters token (not stored)
// 2. Or use environment variables for admin-only apps
const adminToken = process.env.REACT_APP_ADMIN_TOKEN;  // Build-time only

// 3. Or use secure session storage (cleared on tab close)
sessionStorage.setItem('adminToken', token);
```

---

## Troubleshooting

### "Unauthorized" Error

**Problem**: Getting 401 Unauthorized response

**Solutions**:
1. Check if `ADMIN_TOKEN` is set in `.env`
2. Restart server after changing `.env`
3. Verify token matches exactly (no spaces)
4. Check logs for auto-generated token

```bash
# Check server logs
tail -f ~/ppaiservice.log | grep "ADMIN_TOKEN"
```

### Database Locked Error

**Problem**: `SQLITE_BUSY` or database locked errors

**Solutions**:
1. Stop all other connections to database
2. Run vacuum after stopping server:
   ```bash
   ./stop.sh
   sqlite3 ai_svc/dictionary/cache.db "VACUUM;"
   ./start.sh
   ```

### Large Database Size

**Problem**: Database file growing too large

**Solutions**:
1. Run vacuum to reclaim space:
   ```bash
   curl -X POST http://localhost:8000/api/admin/cache/vacuum \
     -H "X-Admin-Token: your_token"
   ```

2. Delete old unused entries (future feature)
3. Reset cache completely:
   ```bash
   python reset_cache.py --force
   ```

---

## API Endpoint Summary

| Endpoint | Method | Auth Required | Description |
|----------|--------|---------------|-------------|
| **Admin Endpoints** | | | |
| `/api/admin/cache/reset` | POST | ✅ Yes | Delete all cache data |
| `/api/admin/cache/vacuum` | POST | ✅ Yes | Optimize database |
| `/api/admin/cache/stats` | GET | ✅ Yes | Detailed statistics with top words |
| **Public Endpoints** | | | |
| `/api/dictionary/cache/words` | GET | ❌ No | List all cached words with sections |
| `/api/dictionary/cache/<word>/section` | DELETE | ❌ No | Delete specific section |
| `/api/dictionary/cache/stats` | GET | ❌ No | Basic statistics |
| `/api/dictionary/cache/clear` | POST | ❌ No | Clear all cache |
| `/api/dictionary/cache/<word>` | DELETE | ❌ No | Delete entire word |

**Authentication Methods**:
- Header: `X-Admin-Token: your_token_here` (recommended)
- Query: `?admin_token=your_token_here` (for testing)

---

## Additional Resources

- [Cache Service Documentation](../ai_svc/dictionary/cache_service.py)
- [API Documentation](docs/API.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
