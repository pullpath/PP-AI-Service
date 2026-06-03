# PP-AI-Service Architecture

## Overview

PP-AI-Service is a Flask-based web service for AI-assisted language learning and media workflows. The dictionary service is the main domain module and uses a section-based, cache-first architecture:

1. Fetch stable/basic dictionary structure from the free Dictionary API.
2. Generate richer learner-facing sections with DeepSeek agents through Agno.
3. Load expensive sense details progressively.
4. Cache each section at the smallest useful granularity.
5. Run phrase video generation asynchronously and expose polling through the dictionary API.

## System View

```text
Client
  |
  v
Flask app.py
  |
  +-- POST /api/dictionary
  |     |
  |     +-- request validation
  |     +-- cache_service.lookup_with_cache(...)
  |           |
  |           +-- fresh cache hit: return immediately
  |           +-- stale cache hit: return stale data + background refresh
  |           +-- cache miss: DictionaryService.lookup_section(...)
  |                 |
  |                 +-- Free Dictionary API
  |                 +-- DeepSeek / Agno agents
  |                 +-- Bilibili search
  |                 +-- async video task service
  |
  +-- POST /api/transcribe
  +-- POST /api/image
  +-- GET  /api/search
  +-- GET  /api/scrape
```

## Dictionary Request Flow

The public dictionary route lives in `app.py` and accepts a single section-driven endpoint:

```http
POST /api/dictionary
Content-Type: application/json
```

Common request shape:

```json
{
  "word": "run",
  "section": "detailed_sense",
  "entry_index": 0,
  "sense_index": 0,
  "phrase": "run into",
  "confused_word": "ran",
  "task_id": "..."
}
```

Only `word` and `section` are always required. Other fields are section-specific.

The route delegates normal lookups to `cache_service.lookup_with_cache(...)`. The cache layer chooses the right cache table and key, then calls `DictionaryService.lookup_section(...)` only on misses or refreshes.

## Section Model

The dictionary API is intentionally section-based instead of returning a full word in one request. This keeps the first response fast and lets the frontend load expensive sections only when needed.

| Section | Scope | Inputs | Backing source |
|---------|-------|--------|----------------|
| `basic` | Word | `word` | Free Dictionary API |
| `common_phrases` | Word | `word` | DeepSeek agent |
| `etymology` | Entry | `word`, `entry_index` | DeepSeek agent |
| `word_family` | Entry | `word`, `entry_index` | DeepSeek agent |
| `usage_context` | Entry | `word`, `entry_index` | DeepSeek agent |
| `cultural_notes` | Entry | `word`, `entry_index` | DeepSeek agent |
| `frequency` | Entry | `word`, `entry_index` | DeepSeek agent |
| `detailed_sense` | Sense | `word`, `entry_index`, `sense_index` | Free API + 2 parallel DeepSeek tasks |
| `examples` | Sense | `word`, `entry_index`, `sense_index` | Free API + DeepSeek agent |
| `usage_notes` | Sense | `word`, `entry_index`, `sense_index` | DeepSeek agent |
| `bilibili_videos` | Phrase | `word`, `phrase` | Bilibili API/subtitles |
| `ai_generated_phrase_video` | Phrase | `word`, `phrase` | DeepSeek script + Volcengine Ark async task |
| `video_status` | Task | `task_id` | Video task SQLite DB |
| `confusion_meta` | Word pair | `word`, `confused_word` | DeepSeek agent |
| `confusion_profiles` | Word pair | `word`, `confused_word` | DeepSeek agent |
| `confusion_examples` | Word pair | `word`, `confused_word` | DeepSeek agent |
| `confusion_all` | Word pair | `word`, `confused_word` | 3 parallel DeepSeek agents |

Entry-level sections default `entry_index` to `0` in `app.py` for backward compatibility.

## Progressive Sense Architecture

The older architecture generated a full detailed sense with four parallel agents. The current implementation uses a progressive `2 + 1 + 1` model:

```text
detailed_sense
  |
  +-- Free Dictionary API supplies definition, part of speech, examples, synonyms, antonyms
  |
  +-- ThreadPoolExecutor(max_workers=2)
        |
        +-- SenseCoreMetadataAgent
        |     register, domain, tone
        |
        +-- SenseRelatedWordsAgent
              missing synonyms, missing antonyms, word-specific phrases

examples
  |
  +-- SenseUsageExamplesAgent
        AI examples + collocations, merged with API example when available

usage_notes
  |
  +-- SenseUsageNotesAgent
        learner guidance and pitfalls
```

This makes the core sense render faster. The frontend can show the definition, POS, register, tone, synonyms, antonyms, and phrases first, then fetch examples and usage notes on demand.

Important behavior:

- `detailed_sense` requires `entry_index` and `sense_index`.
- Flat `index` is deprecated and should not be used in new clients.
- The service returns an error if the Free Dictionary API cannot resolve the word for `basic`, `detailed_sense`, `examples`, or `usage_notes`.
- AI-only fallback is not currently implemented for the sense-level API path.

## Cache Architecture

`ai_svc/dictionary/cache_service.py` implements SQLite caching with field-level granularity.

| Table | Purpose |
|-------|---------|
| `word_cache` | Word-level sections such as `basic` and `common_phrases` |
| `entry_cache` | Entry-level sections such as `etymology`, `usage_context`, and `frequency` |
| `sense_cache` | Sense-level sections: `detailed_sense`, `examples`, `usage_notes` |
| `phrase_cache` | Phrase-specific Bilibili video results |
| `word_confusion_cache` | Section-granular confused-word data |
| `ai_phrase_video_cache` | AI phrase video task metadata and final URLs |
| `cache_metrics` | Hit/miss/stale/refresh metrics |

Cache behavior:

1. Read the exact section key first.
2. Return fresh cached data immediately.
3. Return stale cached data immediately and schedule a background refresh.
4. Suppress duplicate concurrent misses with an in-flight request registry.
5. Write successful service responses back to the matching cache table.

SQLite is configured with WAL mode, a Python write lock, `BEGIN IMMEDIATE` write transactions, and per-section TTLs.

## Bilibili Video Search

`bilibili_videos` is phrase-specific:

```json
{
  "word": "run",
  "section": "bilibili_videos",
  "phrase": "run into"
}
```

The search module:

1. Builds enhanced Bilibili search queries, currently phrase plus English-learning tags.
2. Searches Bilibili knowledge zones.
3. Filters results that contain the phrase.
4. Checks subtitles when credentials are configured.
5. Returns the best video with a `start_time` and playback URL when a subtitle match is found.

Credentials are loaded from environment variables:

- `BILIBILI_SESSDATA`
- `BILIBILI_BILI_JCT`
- `BILIBILI_BUVID3`
- `BILIBILI_AC_TIME_VALUE`

When refreshable credentials are present, the service attempts to refresh them on startup and update `.env`.

## AI Phrase Video Generation

`ai_generated_phrase_video` creates phrase-learning videos asynchronously:

```text
POST /api/dictionary
  section=ai_generated_phrase_video
  phrase="pipe down"
        |
        v
ConversationScriptAgent generates a short educational script
        |
        v
video_task_service.create_task(...)
        |
        v
background thread calls Volcengine Ark SeeDance
        |
        v
generated video is uploaded to object storage
        |
        v
frontend polls section=video_status with task_id
```

The video task service stores state in `ai_svc/dictionary/video_tasks.db` with statuses:

- `pending`
- `processing`
- `completed`
- `failed`

The cache service also stores phrase-video metadata so repeated requests can reuse task information or completed video URLs.

## Confusion Architecture

Confused-word support is section-granular:

- `confusion_meta`: confusion type, quick rule, differentiator, difficulty.
- `confusion_profiles`: side-by-side profiles for the searched and confused words.
- `confusion_examples`: example sentences and usage notes for both words.
- `confusion_all`: runs the three sections in parallel and caches each component separately.

## Technology Stack

### Core

- Flask
- Flask-CORS
- Pydantic
- SQLite
- `requests`
- `concurrent.futures`

### AI and media

- DeepSeek via Agno agents
- OpenAI Whisper and Vision for non-dictionary endpoints
- Bilibili API for educational video discovery
- Volcengine Ark SeeDance for generated phrase videos
- Object storage integration for generated video hosting

## Environment Variables

Required for dictionary AI:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
```

Required for AI phrase video generation:

```env
ARK_API_KEY=your_volcengine_api_key
BUCKET_NAME_PREFIX=optional_prefix
```

Optional for Bilibili subtitle access:

```env
BILIBILI_SESSDATA=your_sessdata
BILIBILI_BILI_JCT=your_bili_jct
BILIBILI_BUVID3=your_buvid3
BILIBILI_AC_TIME_VALUE=your_ac_time_value
```

Other service variables:

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_BASE=your_proxy_base_url
X-PP-TOKEN=your_proxy_token
SERPER_API_KEY=your_serper_api_key
BROWSERLESS_API_KEY=your_browserless_api_key
FLASK_ENV=development
```

## Expected Performance

These are approximate uncached latencies; cache hits are much faster.

| Operation | Expected time | Notes |
|-----------|---------------|-------|
| `basic` | 0.5-1s | Free Dictionary API only |
| `common_phrases` | 1-3s | Single AI agent |
| Entry-level AI sections | 2-5s | Single AI agent |
| `detailed_sense` | 2-3s | API + 2 parallel AI tasks |
| `examples` | 1.5-2s | API example + AI examples/collocations |
| `usage_notes` | 1-1.5s | Single AI agent |
| `confusion_all` | 2-5s | 3 parallel AI tasks |
| `bilibili_videos` | variable | Network and subtitle dependent |
| `ai_generated_phrase_video` | 30-300s | Async background task |

## Design Principles

1. **Section-first API**: keep initial responses small and let clients prioritize.
2. **Cache-first execution**: avoid repeated AI/API work and serve stale data when useful.
3. **API data as ground truth**: use Free Dictionary API definitions and pronunciation where possible.
4. **Progressive enrichment**: defer examples and notes until the frontend asks for them.
5. **Structured AI output**: validate agent responses with Pydantic schemas.
6. **Async long-running work**: return task IDs for generated videos instead of blocking the request.

## Testing and Debugging

Basic lookup:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"basic"}'
```

Core sense:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"detailed_sense","entry_index":0,"sense_index":0}'
```

Examples:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"examples","entry_index":0,"sense_index":0}'
```

Bilibili videos:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"bilibili_videos","phrase":"run into"}'
```

AI phrase video:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"quiet","section":"ai_generated_phrase_video","phrase":"pipe down"}'
```

Poll video status:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"quiet","section":"video_status","task_id":"TASK_ID"}'
```

## See Also

- [API Usage Guide](API.md)
- [Cache Management](CACHE_MANAGEMENT.md)
- [AI Video Generation](AI_VIDEO_GENERATION.md)
- [Async Video Generation](ASYNC_VIDEO_GENERATION.md)
- [Deployment Guide](DEPLOYMENT.md)
