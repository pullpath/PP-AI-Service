# Dictionary API Usage Guide

Complete guide for using the PP-AI-Service Dictionary API to retrieve full word information.

## Table of Contents
- [Quick Start](#quick-start)
- [API Endpoint](#api-endpoint)
- [Available Sections](#available-sections)
- [Loading Strategy](#loading-strategy)
- [Response Formats](#response-formats)
- [Error Handling](#error-handling)
- [Performance Optimization](#performance-optimization)

---

## Quick Start

### Single Request (Basic Info)
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"basic"}'
```

### Full Word Information (Multiple Requests)
```javascript
// Step 1: Get basic info (fast, ~0.5s)
const basic = await fetch('/api/dictionary', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({word: 'hello', section: 'basic'})
}).then(r => r.json());

// Step 2: Load other sections in parallel (~2-5s each)
const [etymology, wordFamily, frequency] = await Promise.all([
  fetch('/api/dictionary', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({word: 'hello', section: 'etymology'})
  }).then(r => r.json()),
  
  fetch('/api/dictionary', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({word: 'hello', section: 'word_family'})
  }).then(r => r.json()),
  
  fetch('/api/dictionary', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({word: 'hello', section: 'frequency'})
  }).then(r => r.json())
]);

// Step 3: Load individual senses on-demand (~5.25s each with 4-agent parallel)
const sense0 = await fetch('/api/dictionary', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({word: 'hello', section: 'detailed_sense', index: 0})
}).then(r => r.json());
```

---

## API Endpoint

**URL**: `POST /api/dictionary`

**Required Parameters**:
- `word` (string): The word to look up
- `section` (string): Which section of data to retrieve

**Optional Parameters**:
- `index` (integer): Required only for `detailed_sense` section to specify which sense (0-based)

---

## Available Sections

### 1. `basic` - Basic Information
**Speed**: Fast (~0.5s) - No AI required

**Request**:
```json
{
  "word": "run",
  "section": "basic"
}
```

**Response**:
```json
{
  "headword": "run",
  "pronunciation": "https://api.dictionaryapi.dev/media/pronunciations/en/run-us.mp3",
  "total_senses": 63,
  "data_source": "hybrid_api_ai",
  "execution_time": 0.52,
  "success": true
}
```

**Use Case**: Always fetch this first to know how many senses exist

---

### 2. `etymology` - Word Origin & History
**Speed**: Medium (~2-5s) - AI required

**Request**:
```json
{
  "word": "run",
  "section": "etymology"
}
```

**Response**:
```json
{
  "headword": "run",
  "etymology": {
    "etymology": "From Old English 'rinnan' (to flow, run), from Proto-Germanic *rinnaną. The word has maintained its core meaning of rapid movement throughout its history.",
    "root_analysis": "Old English: rinnan (to flow) → Proto-Germanic: *rinnaną → Proto-Indo-European: *h₃reyH- (to flow, move)"
  },
  "execution_time": 3.21,
  "success": true
}
```

---

### 3. `word_family` - Related Words
**Speed**: Medium (~2-5s) - AI required

**Request**:
```json
{
  "word": "run",
  "section": "word_family"
}
```

**Response**:
```json
{
  "headword": "run",
  "word_family": {
    "word_family": [
      "runner", "running", "ran", "runs",
      "runnable", "runaway", "run-down", "overrun",
      "outrun", "rerun", "underrun", "runoff"
    ]
  },
  "execution_time": 2.45,
  "success": true
}
```

---

### 4. `usage_context` - Modern Usage Trends
**Speed**: Medium (~2-5s) - AI required

**Request**:
```json
{
  "word": "run",
  "section": "usage_context"
}
```

**Response**:
```json
{
  "headword": "run",
  "usage_context": {
    "modern_relevance": "Extremely common in both literal (physical running) and figurative contexts (running a business, running software). Tech usage is rising.",
    "common_confusions": [
      "run vs jog: 'run' is general movement, 'jog' is slower pace",
      "run vs sprint: 'sprint' implies maximum speed for short distance"
    ],
    "regional_variations": [
      "UK: 'go for a run' more common than US 'go running'",
      "US: 'run errands' is standard, UK may say 'do errands'"
    ]
  },
  "execution_time": 3.78,
  "success": true
}
```

---

### 5. `cultural_notes` - Cultural Context
**Speed**: Medium (~2-5s) - AI required

**Request**:
```json
{
  "word": "run",
  "section": "cultural_notes"
}
```

**Response**:
```json
{
  "headword": "run",
  "cultural_notes": {
    "notes": "Running has significant cultural associations with health, fitness, and personal achievement. Marathon running is culturally prestigious. The word appears in many idioms reflecting urgency and continuous action."
  },
  "execution_time": 2.91,
  "success": true
}
```

---

### 6. `frequency` - Usage Frequency
**Speed**: Medium (~2-5s) - AI required

**Request**:
```json
{
  "word": "run",
  "section": "frequency"
}
```

**Response**:
```json
{
  "headword": "run",
  "frequency": "very_common",
  "execution_time": 2.15,
  "success": true
}
```

**Possible Values**: `very_common`, `common`, `uncommon`, `rare`, `very_rare`

---

### 7. `detailed_sense` - Individual Sense Detail
**Speed**: Medium (~5.25s) - 4 parallel AI agents (optimized)

**Request**:
```json
{
  "word": "run",
  "section": "detailed_sense",
  "index": 0
}
```

**Response**:
```json
{
  "headword": "run",
  "detailed_sense": {
    "definition": "To move swiftly on foot so that both feet leave the ground during each stride",
    "part_of_speech": "verb",
    "usage_register": "neutral",
    "domain": "physical_activity",
    "tone": "neutral",
    "usage_notes": "Most common meaning. Can be used literally or figuratively. Common learner error: confusing 'run' with 'ran' (past tense).",
    "examples": [
      "She runs 5 miles every morning",
      "The children are running in the park",
      "I need to run to catch the bus"
    ],
    "collocations": [
      "run fast", "run quickly", "run away",
      "run towards", "run after", "start running"
    ],
    "word_specific_phrases": [
      "run for your life",
      "run like the wind",
      "run circles around someone"
    ],
    "synonyms": ["sprint", "jog", "dash", "race"],
    "antonyms": ["walk", "stand", "stop", "rest"]
  },
  "execution_time": 5.25,
  "success": true
}
```

**Note**: The `index` parameter is 0-based. Use `total_senses` from `basic` section to know the range.

---

## Loading Strategy

### Recommended Approach: Progressive Loading

```javascript
class DictionaryLoader {
  async loadWord(word) {
    // Step 1: Load basic info immediately (fast)
    const basic = await this.fetchSection(word, 'basic');
    this.updateUI({basic});
    
    // Step 2: Load metadata sections in parallel (medium speed)
    const metadataPromises = [
      this.fetchSection(word, 'etymology'),
      this.fetchSection(word, 'word_family'),
      this.fetchSection(word, 'usage_context'),
      this.fetchSection(word, 'cultural_notes'),
      this.fetchSection(word, 'frequency')
    ];
    
    // Update UI as each section completes
    const metadata = await Promise.allSettled(metadataPromises);
    metadata.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        this.updateUI({[this.sectionNames[index]]: result.value});
      }
    });
    
    // Step 3: Load senses on-demand (slow)
    // Only load when user scrolls or clicks
    this.setupLazySenseLoading(word, basic.total_senses);
  }
  
  async fetchSection(word, section, index = null) {
    const body = {word, section};
    if (index !== null) body.index = index;
    
    const response = await fetch('/api/dictionary', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    
    return response.json();
  }
  
  setupLazySenseLoading(word, totalSenses) {
    // Implement lazy loading or load first 3 senses
    const loadSense = async (index) => {
      const sense = await this.fetchSection(word, 'detailed_sense', index);
      this.updateUI({[`sense_${index}`]: sense});
    };
    
    // Load first sense immediately, others on scroll
    loadSense(0);
  }
}
```

---

## Response Formats

### Success Response
All successful responses include:
- `headword`: The word that was looked up
- `success`: true
- `execution_time`: Time taken in seconds
- Section-specific data

### Error Response
```json
{
  "error": "Error message describing what went wrong",
  "success": false
}
```

Common errors:
- `"Missing 'section' parameter in request body"`
- `"Invalid section 'xyz'. Valid sections: ..."`
- `"index is required when requesting 'detailed_sense'"`
- `"Invalid index 999. Word has 63 senses (0-62)"`

---

## Error Handling

```javascript
async function fetchDictionarySection(word, section, index = null) {
  try {
    const body = {word, section};
    if (index !== null) body.index = index;
    
    const response = await fetch('/api/dictionary', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    
    const data = await response.json();
    
    if (!data.success) {
      console.error(`Dictionary API error: ${data.error}`);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error('Network error:', error);
    return null;
  }
}
```

---

## Performance Optimization

### 1. Loading Indicators
Show appropriate loading states for different sections:

```javascript
// Fast section (basic)
showQuickLoader(); // Spinner for 0.5s

// Medium sections (etymology, word_family, etc.)
showMediumLoader(); // Progress bar for 2-5s

// Medium sections (detailed_sense)
showMediumLoader(); // "Analyzing with 4 parallel agents..." for ~5.25s
```

### 2. Request Throttling
Prevent overwhelming the API:

```javascript
// Limit concurrent detailed_sense requests
const senseQueue = new PQueue({concurrency: 2});

for (let i = 0; i < totalSenses; i++) {
  senseQueue.add(() => fetchSection(word, 'detailed_sense', i));
}
```

### 3. Caching on Frontend
Cache responses to avoid repeated requests:

```javascript
const cache = new Map();

async function fetchWithCache(word, section, index = null) {
  const key = `${word}_${section}_${index}`;
  
  if (cache.has(key)) {
    return cache.get(key);
  }
  
  const data = await fetchSection(word, section, index);
  cache.set(key, data);
  return data;
}
```

### 4. Lazy Loading Senses
Only load senses that are visible:

```javascript
// Using Intersection Observer
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const index = entry.target.dataset.senseIndex;
      loadSense(word, index);
      observer.unobserve(entry.target);
    }
  });
});

// Observe each sense placeholder
document.querySelectorAll('.sense-placeholder').forEach(el => {
  observer.observe(el);
});
```

---

## Complete Example

```javascript
async function loadFullWordInfo(word) {
  console.log(`Loading full information for: ${word}`);
  
  // 1. Get basic info (required first)
  const basic = await fetchSection(word, 'basic');
  if (!basic || !basic.success) {
    console.error('Failed to load basic info');
    return;
  }
  
  console.log(`Word has ${basic.total_senses} senses`);
  console.log(`Pronunciation: ${basic.pronunciation}`);
  
  // 2. Load all metadata sections in parallel
  const sections = [
    'etymology',
    'word_family',
    'usage_context',
    'cultural_notes',
    'frequency'
  ];
  
  console.log('Loading metadata sections...');
  const metadataResults = await Promise.allSettled(
    sections.map(section => fetchSection(word, section))
  );
  
  const fullData = {
    ...basic,
    metadata: {}
  };
  
  metadataResults.forEach((result, index) => {
    if (result.status === 'fulfilled' && result.value.success) {
      const sectionName = sections[index];
      fullData.metadata[sectionName] = result.value[sectionName];
    }
  });
  
  // 3. Load first 3 senses (or all if fewer than 3)
  const sensesToLoad = Math.min(3, basic.total_senses);
  console.log(`Loading first ${sensesToLoad} senses...`);
  
  fullData.senses = [];
  
  for (let i = 0; i < sensesToLoad; i++) {
    const sense = await fetchSection(word, 'detailed_sense', i);
    if (sense && sense.success) {
      fullData.senses.push(sense.detailed_sense);
      console.log(`Loaded sense ${i + 1}/${sensesToLoad}`);
    }
  }
  
  console.log('Full word data loaded:', fullData);
  return fullData;
}

// Helper function
async function fetchSection(word, section, index = null) {
  const body = {word, section};
  if (index !== null) body.index = index;
  
  const response = await fetch('http://localhost:8000/api/dictionary', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  
  return response.json();
}

// Usage
loadFullWordInfo('run');
```

---

## Expected Latencies

| Section | Speed | Time | Notes |
|---------|-------|------|-------|
| `basic` | Fast | ~0.5s | No AI, just API/parsing |
| `etymology` | Medium | ~2-5s | AI generation |
| `word_family` | Medium | ~2-5s | AI generation |
| `usage_context` | Medium | ~2-5s | AI generation |
| `cultural_notes` | Medium | ~2-5s | AI generation |
| `frequency` | Medium | ~2-5s | AI generation |
| `detailed_sense` | Medium | ~5.25s | 4 parallel AI agents (optimized) |

**Total for full word info**:
- Basic + 5 metadata sections (parallel): ~5-7s
- + First 3 senses (sequential): ~15.75s (3 × 5.25s)
- **Total: ~20-23s** for comprehensive word data (with 4-agent optimization)

**Recommendation**: Load progressively and show content as it arrives, not all at once.

---

## Best Practices

1. **Always fetch `basic` first** - It's fast and tells you how many senses exist
2. **Load metadata sections in parallel** - They're independent and take similar time
3. **Lazy load senses** - Don't load all 63 senses upfront for a word like "run"
4. **Show loading indicators** - Set user expectations for AI generation time
5. **Cache on frontend** - Avoid repeated requests for the same word
6. **Handle errors gracefully** - API calls can fail, show fallback UI
7. **Implement retry logic** - Network issues happen, retry with exponential backoff

---

## API Design Philosophy

This API uses a **section-based architecture** instead of full word lookup:

**Why?**
- ✅ Faster initial response (basic info in 0.5s vs 35-47s for everything)
- ✅ Progressive loading (show content as it arrives)
- ✅ Flexible (fetch only what you need)
- ✅ Scalable (frontend controls priority and timing)
- ✅ Cost-effective (don't generate unused AI content)

**Trade-off**: Requires multiple API calls instead of one, but results in better UX.

---

## Support

For issues or questions:
- Check error messages in responses
- Verify section names are correct
- Ensure `index` is provided for `detailed_sense` requests
- Check that `index` is within range (0 to total_senses-1)

Happy word looking! 📖
