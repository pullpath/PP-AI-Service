# Multi-Agent Dictionary Service Architecture

## Overview

This document describes the optimized multi-agent architecture implemented to improve LLM response times in the dictionary service. The solution uses tiered information retrieval with specialized agents, addressing the ~50-second response time issue with the original comprehensive `DictionaryEntry` schema.

## Problem Statement

**Original Issue**: Single agent with complex `DictionaryEntry` schema (nested `WordSense` objects) caused ~50-second response times.

**User Requirement**: Not a simple "fast mode" toggle, but intelligent tiered information retrieval that maintains comprehensive analysis while improving performance.

## Solution Architecture

### Tiered Information Categories

1. **Primary Information** (Essential, fast)
   - `headword`, `pronunciation`, `frequency`
   - Simplified senses (1-3 most common meanings)
   - **Response time**: ~6-8 seconds

2. **Secondary Information** (Detailed context)
   - `etymology`, `root_analysis`, `word_family`
   - `modern_relevance`, `common_confusions`, `regional_variations`
   - Can be fetched separately after primary info

3. **Sense-Level Information** (Per-meaning analysis)
   - Detailed analysis of each word sense
   - Includes usage guidance, examples, collocations, synonyms/antonyms
   - Each sense analyzed by a specialized agent

### Agent Specialization

Three specialized agents, each optimized for specific information:

1. **PrimaryInfoAgent**
   - Fast essential information extraction
   - Uses `PrimaryInfo` schema (minimal, focused)
   - Returns in ~6.58 seconds (tested)

2. **SecondaryInfoAgent**
   - Detailed linguistic and historical context
   - Uses `SecondaryInfo` schema
   - Runs in parallel with sense agents

3. **WordSenseAgent**
   - Comprehensive per-sense analysis
   - Uses `DetailedWordSense` schema
   - Multiple instances can run in parallel

### Parallel Execution

- **Primary agent**: Runs first (sequential, needed for sense structure)
- **Secondary agent**: Runs in parallel with sense agents
- **Sense agents**: Multiple instances run in parallel (one per sense)
- **ThreadPoolExecutor**: Manages concurrent agent execution

## API Endpoints

### Updated `/api/dictionary` endpoint
```json
POST /api/dictionary
{
  "word": "test",
  "mode": "primary" | "full" | "legacy"
}
```

**Modes**:
- `primary`: Fast essential info only (~6-8s)
- `full`: Comprehensive tiered analysis (~16-20s)
- `legacy`: Original single-agent call (~50s)

### New Endpoints
- `POST /api/dictionary/secondary`: Get secondary information only
- `POST /api/dictionary/sense`: Get detailed analysis for specific sense
- `GET /api/dictionary/test`: Test endpoint with documentation

## Performance Improvements

### Test Results (word: "optimization")

| Mode | Response Time | Improvement vs Legacy |
|------|---------------|----------------------|
| Primary | 6.76s | ~86% faster |
| Full | 16.70s | ~67% faster |
| Legacy | ~50s | Baseline |

### Caching Strategy
- In-memory cache with 1-hour TTL
- Separate cache keys for different modes and words
- Dramatic speedup for repeated requests

## Technical Implementation

### Key Files

1. **`ai_svc/dictionary_service.py`**
   - Multi-agent orchestration system
   - Parallel execution with `concurrent.futures`
   - Caching implementation

2. **`app.py`**
   - Updated Flask endpoints with tiered modes
   - New secondary and sense endpoints
   - Backward compatibility with legacy mode

### Schema Design

```python
# PrimaryInfo (fast, essential)
class PrimaryInfo(BaseModel):
    headword: str
    pronunciation: str
    frequency: FrequencyEnum
    simplified_senses: List[Dict[str, Any]]

# SecondaryInfo (detailed context)
class SecondaryInfo(BaseModel):
    etymology: str
    root_analysis: str
    word_family: List[str]
    modern_relevance: str
    # ... additional fields

# DetailedWordSense (per-sense analysis)
class DetailedWordSense(BaseModel):
    definition: str
    part_of_speech: str
    usage_register: List[str]
    examples: List[str]
    # ... comprehensive fields
```

## Usage Examples

### Fast Primary Information
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word": "test", "mode": "primary"}'
```

### Comprehensive Analysis
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word": "test", "mode": "full"}'
```

### Secondary Information Only
```bash
curl -X POST http://localhost:8000/api/dictionary/secondary \
  -H "Content-Type: application/json" \
  -d '{"word": "test"}'
```

### Specific Sense Analysis
```bash
curl -X POST http://localhost:8000/api/dictionary/sense \
  -H "Content-Type: application/json" \
  -d '{"word": "test", "sense_index": 0}'
```

## Benefits

1. **Performance**: 67-86% faster response times
2. **Flexibility**: Clients can choose between speed and completeness
3. **Scalability**: Parallel execution handles multiple senses efficiently
4. **Caching**: Repeated requests are dramatically faster
5. **Backward Compatibility**: Legacy mode maintained for existing clients
6. **Progressive Enhancement**: Users get primary info fast, can request details as needed

## Future Improvements

1. **Dynamic Worker Pool**: Adjust thread count based on sense count
2. **Request Batching**: Batch similar sense expansions
3. **Distributed Caching**: Redis/memcached for shared cache
4. **Response Streaming**: Stream partial results as they complete
5. **Quality Metrics**: Track accuracy and completeness of tiered responses

## Conclusion

The multi-agent architecture successfully addresses the performance issue while maintaining comprehensive linguistic analysis. By splitting the complex schema into logical tiers and using parallel execution, we achieve significant speed improvements without sacrificing information quality.