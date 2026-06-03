# Dictionary API Usage Guide

This guide describes the current section-based dictionary API used by PP-AI-Service.

## Endpoint

```http
POST /api/dictionary
Content-Type: application/json
```

Every request requires:

- `word`: word being looked up.
- `section`: section to fetch.

Some sections require additional parameters:

- `entry_index`: zero-based dictionary entry index.
- `sense_index`: zero-based sense index within an entry.
- `phrase`: phrase for Bilibili or generated video sections.
- `confused_word`: comparison word for confusion sections.
- `task_id`: video task ID for `video_status`.

The old flat `index` parameter is deprecated. Use `entry_index` and `sense_index` for sense-level sections.

## Quick Start

Fetch the entry structure first:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"basic"}'
```

Then load an entry section:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"etymology","entry_index":0}'
```

Then load sense details progressively:

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"detailed_sense","entry_index":0,"sense_index":0}'
```

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"examples","entry_index":0,"sense_index":0}'
```

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"usage_notes","entry_index":0,"sense_index":0}'
```

## Available Sections

| Section | Required parameters | Description |
|---------|---------------------|-------------|
| `basic` | `word` | Entry structure, pronunciation, IPA, meanings, definitions, total senses |
| `common_phrases` | `word` | AI-generated phrases and collocations |
| `etymology` | `word`, optional `entry_index` | Word origin and root analysis |
| `word_family` | `word`, optional `entry_index` | Related word forms |
| `usage_context` | `word`, optional `entry_index` | Modern relevance, common confusions, regional variations |
| `cultural_notes` | `word`, optional `entry_index` | Historical context, associations, social perceptions |
| `frequency` | `word`, optional `entry_index` | Usage frequency enum |
| `detailed_sense` | `word`, `entry_index`, `sense_index` | Core sense detail, excluding examples and notes |
| `examples` | `word`, `entry_index`, `sense_index` | Examples and collocations for one sense |
| `usage_notes` | `word`, `entry_index`, `sense_index` | Learner guidance for one sense |
| `bilibili_videos` | `word`, `phrase` | Educational Bilibili video for a phrase |
| `ai_generated_phrase_video` | `word`, `phrase` | Start async AI phrase video generation |
| `video_status` | `task_id` | Poll async video task status |
| `confusion_meta` | `word`, `confused_word` | Confusion type and quick rule |
| `confusion_profiles` | `word`, `confused_word` | Side-by-side word profiles |
| `confusion_examples` | `word`, `confused_word` | Examples and notes for both words |
| `confusion_all` | `word`, `confused_word` | Fetch all confusion sections in parallel |

For entry-level sections, `app.py` defaults `entry_index` to `0` when omitted.

## Response Examples

### `basic`

Request:

```json
{
  "word": "run",
  "section": "basic"
}
```

Response shape:

```json
{
  "headword": "run",
  "total_entries": 1,
  "entries": [
    {
      "entry_index": 0,
      "pronunciation": "https://api.dictionaryapi.dev/media/pronunciations/en/run-us.mp3",
      "ipa": "/ɹʌn/",
      "meanings_summary": [
        {
          "part_of_speech": "verb",
          "definition_count": 10,
          "senses": [
            {
              "definition": "To move forward quickly upon two feet...",
              "example": "Run, Sarah, run!",
              "synonyms": [],
              "antonyms": []
            }
          ]
        }
      ],
      "total_senses": 10
    }
  ],
  "total_senses": 10,
  "data_source": "api",
  "execution_time": 0.52,
  "success": true
}
```

### `detailed_sense`

Request:

```json
{
  "word": "run",
  "section": "detailed_sense",
  "entry_index": 0,
  "sense_index": 0
}
```

Response shape:

```json
{
  "headword": "run",
  "entry_index": 0,
  "sense_index": 0,
  "detailed_sense": {
    "definition": "To move forward quickly upon two feet...",
    "part_of_speech": "verb",
    "usage_register": ["neutral"],
    "domain": ["general"],
    "tone": "neutral",
    "synonyms": ["sprint", "dash", "jog"],
    "antonyms": ["walk", "stand", "stop"],
    "word_specific_phrases": ["run for your life", "run late", "run around"]
  },
  "execution_time": 2.4,
  "success": true
}
```

`detailed_sense` intentionally does not include examples or usage notes. Fetch those separately.

### `examples`

```json
{
  "word": "run",
  "section": "examples",
  "entry_index": 0,
  "sense_index": 0
}
```

```json
{
  "headword": "run",
  "entry_index": 0,
  "sense_index": 0,
  "examples": [
    "Run, Sarah, run!",
    "He runs every morning before work."
  ],
  "collocations": ["run fast", "run daily", "run home"],
  "data_source": "hybrid",
  "execution_time": 1.8,
  "success": true
}
```

### `usage_notes`

```json
{
  "word": "run",
  "section": "usage_notes",
  "entry_index": 0,
  "sense_index": 0
}
```

```json
{
  "headword": "run",
  "entry_index": 0,
  "sense_index": 0,
  "usage_notes": "Use this for fast movement on foot. For slower exercise, jog is often more precise.",
  "data_source": "ai",
  "execution_time": 1.2,
  "success": true
}
```

### `usage_context`

```json
{
  "word": "run",
  "section": "usage_context",
  "entry_index": 0
}
```

```json
{
  "headword": "run",
  "entry_index": 0,
  "usage_context": {
    "modern_relevance": "Very common in physical, business, technical, and idiomatic contexts.",
    "common_confusions": ["ran", "jog", "sprint"],
    "regional_variations": {
      "US": "Run errands is very common.",
      "UK": "Go for a run is common in fitness contexts."
    }
  },
  "data_source": "ai",
  "execution_time": 3.2,
  "success": true
}
```

### `cultural_notes`

```json
{
  "word": "run",
  "section": "cultural_notes",
  "entry_index": 0
}
```

```json
{
  "headword": "run",
  "entry_index": 0,
  "cultural_notes": {
    "historical_context": "The word has long been used for physical motion and later extended into business, machines, and software.",
    "cultural_associations": ["fitness culture", "politics", "software"],
    "social_perceptions": ["energetic", "practical", "action-oriented"]
  },
  "data_source": "ai",
  "execution_time": 2.9,
  "success": true
}
```

### `frequency`

```json
{
  "word": "run",
  "section": "frequency",
  "entry_index": 0
}
```

```json
{
  "headword": "run",
  "entry_index": 0,
  "frequency": "very_common",
  "data_source": "ai",
  "execution_time": 2.1,
  "success": true
}
```

Possible frequency values:

- `very_common`
- `common`
- `uncommon`
- `rare`
- `very_rare`

### `bilibili_videos`

```json
{
  "word": "run",
  "section": "bilibili_videos",
  "phrase": "run into"
}
```

```json
{
  "headword": "run",
  "phrase": "run into",
  "bilibili_videos": {
    "bvid": "BV...",
    "title": "English phrase explanation...",
    "start_time": 42.5,
    "matched_phrase": "run into",
    "video_url": "https://www.bilibili.com/video/BV...?t=42"
  },
  "data_source": "api",
  "execution_time": 4.7,
  "success": true
}
```

### `ai_generated_phrase_video`

This section returns quickly after creating a background task. The actual video is generated asynchronously.

```json
{
  "word": "quiet",
  "section": "ai_generated_phrase_video",
  "phrase": "pipe down"
}
```

```json
{
  "phrase": "pipe down",
  "conversation_script": {
    "scenario": "A short classroom scene...",
    "dialogue": [
      {"character": "Teacher", "text": "Please pipe down so everyone can hear."}
    ]
  },
  "ai_generated_phrase_video": {
    "task_id": "9b0f...",
    "status": "pending",
    "poll_url": "/api/dictionary",
    "poll_params": {
      "section": "video_status",
      "task_id": "9b0f..."
    },
    "message": "Video generation started. Poll using /api/dictionary with section=video_status and task_id parameter."
  },
  "data_source": "ai",
  "execution_time": 3.4,
  "success": true
}
```

Poll status:

```json
{
  "word": "quiet",
  "section": "video_status",
  "task_id": "9b0f..."
}
```

Completed response:

```json
{
  "task_id": "9b0f...",
  "phrase": "pipe down",
  "status": "completed",
  "progress": 100,
  "video_url": "https://...",
  "style": "kids_cartoon",
  "duration": 5,
  "success": true
}
```

### `confusion_all`

```json
{
  "word": "affect",
  "section": "confusion_all",
  "confused_word": "effect"
}
```

Response shape:

```json
{
  "headword": "affect",
  "confused_word": "effect",
  "confusion_meta": {
    "confusion_type": "semantic_overlap",
    "quick_rule": "Affect is usually a verb; effect is usually a noun.",
    "key_differentiator": "Affect means to influence, while effect means a result.",
    "difficulty": "medium"
  },
  "confusion_profiles": {
    "searched_word": {
      "core_meaning": "To influence or change something.",
      "part_of_speech": "verb",
      "typical_domains": ["academic", "general"],
      "collocations": ["deeply affect", "directly affect"],
      "grammar_note": "Usually transitive."
    },
    "confused_word": {
      "core_meaning": "A result or consequence.",
      "part_of_speech": "noun",
      "typical_domains": ["academic", "general"],
      "collocations": ["side effect", "lasting effect"],
      "grammar_note": "Often follows an article or adjective."
    }
  },
  "confusion_examples": {
    "searched_word": {
      "example_sentences": ["The weather can affect your mood."],
      "usage_note": "Use affect when something influences something else."
    },
    "confused_word": {
      "example_sentences": ["The medicine had a calming effect."],
      "usage_note": "Use effect for the result."
    }
  },
  "errors": null,
  "data_source": "ai",
  "execution_time": 3.6,
  "success": true
}
```

## Recommended Loading Strategy

```javascript
async function postDictionary(body) {
  const response = await fetch('/api/dictionary', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return response.json();
}

async function loadWord(word) {
  const basic = await postDictionary({word, section: 'basic'});
  renderBasic(basic);

  const entryIndex = 0;
  const entrySections = [
    'etymology',
    'word_family',
    'usage_context',
    'cultural_notes',
    'frequency'
  ];

  Promise.allSettled(
    entrySections.map(section => postDictionary({word, section, entry_index: entryIndex}))
  ).then(renderEntrySections);

  const firstSense = await postDictionary({
    word,
    section: 'detailed_sense',
    entry_index: entryIndex,
    sense_index: 0
  });
  renderCoreSense(firstSense);

  Promise.allSettled([
    postDictionary({word, section: 'examples', entry_index: entryIndex, sense_index: 0}),
    postDictionary({word, section: 'usage_notes', entry_index: entryIndex, sense_index: 0})
  ]).then(renderSenseExtras);
}
```

For words with multiple entries, use the `entries` array from `basic` to let the user select the right `entry_index`.

## Cache Metadata

Cached responses may include internal cache fields:

```json
{
  "_cache_status": "fresh"
}
```

or:

```json
{
  "_cache_status": "stale",
  "_cache_age_seconds": 90123
}
```

The client can safely ignore these fields unless it wants to show cache/debug state.

## Error Handling

Common error responses:

```json
{
  "error": "detailed_sense requires both 'entry_index' and 'sense_index'",
  "success": false
}
```

```json
{
  "error": "bilibili_videos section requires 'phrase' parameter",
  "success": false
}
```

```json
{
  "error": "Invalid entry_index 2. Word has 1 entries (0-0)",
  "success": false
}
```

Recommended client helper:

```javascript
async function fetchDictionarySection(body) {
  const response = await fetch('/api/dictionary', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });

  const data = await response.json();
  if (!data.success) {
    throw new Error(data.error || 'Dictionary request failed');
  }
  return data;
}
```

## Expected Latencies

Approximate uncached timings:

| Section | Time | Notes |
|---------|------|-------|
| `basic` | 0.5-1s | Free Dictionary API |
| `common_phrases` | 1-3s | Single AI agent |
| `etymology` | 2-5s | Single AI agent |
| `word_family` | 2-5s | Single AI agent |
| `usage_context` | 2-5s | Single AI agent |
| `cultural_notes` | 2-5s | Single AI agent |
| `frequency` | 2-5s | Single AI agent |
| `detailed_sense` | 2-3s | Free API + 2 parallel AI tasks |
| `examples` | 1.5-2s | Free API example + AI generation |
| `usage_notes` | 1-1.5s | Single AI agent |
| `confusion_all` | 2-5s | 3 parallel AI tasks |
| `bilibili_videos` | variable | Bilibili network/subtitle dependent |
| `ai_generated_phrase_video` | 30-300s | Async task; initial request returns a task ID |

Cache hits should be much faster than the uncached timings above.

## Best Practices

1. Fetch `basic` first.
2. Treat `entries[*].entry_index` and each entry's sense list as the source of truth for indexes.
3. Use `entry_index` and `sense_index`; do not use deprecated flat `index`.
4. Render `detailed_sense` first, then lazy-load `examples` and `usage_notes`.
5. Fetch entry-level sections in parallel.
6. Require `phrase` before calling Bilibili or generated-video sections.
7. Poll `video_status` for generated videos instead of waiting on the creation request.
8. Gracefully handle section-level failures; one section can fail while others succeed.
