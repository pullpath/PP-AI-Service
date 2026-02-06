# PP-AI-Service Architecture

## Overview

PP-AI-Service is a **Flask-based web service** that provides AI-powered functionality with a focus on dictionary lookups using a hybrid API + AI architecture.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Flask Application (app.py)                 │
│                         Port: 8000                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Dictionary Service (Hybrid Architecture)      │  │
│  │                                                        │  │
│  │  Step 1: Free Dictionary API (0.5-1s)                │  │
│  │  └─► Basic data: pronunciation, definitions           │  │
│  │                                                        │  │
│  │  Step 2: DeepSeek AI Enhancement (5-6s)              │  │
│  │  └─► 4 Parallel Agents:                              │  │
│  │      ├─ Agent 1: Core metadata (300 tokens)          │  │
│  │      ├─ Agent 2: Examples & collocations (200)       │  │
│  │      ├─ Agent 3: Related words (200)                 │  │
│  │      └─ Agent 4: Usage notes (150)                   │  │
│  │                                                        │  │
│  │  Fallback: Pure AI mode if API fails                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         OpenAI Services                               │  │
│  │  - Audio Transcription (Whisper)                     │  │
│  │  - Image Analysis (Vision API)                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Additional Services                           │  │
│  │  - Web Search (Serper API)                           │  │
│  │  - Web Scraping (Browserless)                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Dictionary Service - 4-Agent Parallel Architecture

### Performance Evolution

| Version | Architecture | Performance | Improvement |
|---------|-------------|-------------|-------------|
| v1 | Sequential (single agent) | 10-13s | Baseline |
| v2 | 3 agents parallel | 8-9s | 20-30% faster |
| v3 | 3 agents + limited output | 6.5s | 40-50% faster |
| v4 | **4 agents parallel (current)** | **5.25s** | **50-60% faster** |

### Agent Breakdown

Each agent runs in parallel with optimized token limits:

#### Agent 1: Core Metadata (300 tokens, ~2.0-2.5s)
- Definition
- Part of speech
- Usage register (formal, informal, etc.)
- Domain (technical field)
- Tone (positive, negative, neutral, etc.)

#### Agent 2: Examples & Collocations (200 tokens, ~1.5-2.0s)
- 3 example sentences
- 3 word collocations (common word partners)

#### Agent 3: Related Words (200 tokens, ~1.5-2.0s)
- 3 synonyms
- 3 antonyms
- 3 word-specific phrases/idioms

#### Agent 4: Usage Notes (150 tokens, ~1.0-1.5s)
- 2-3 sentences of usage guidance
- When/how to use the word appropriately

### Data Flow

```
User Request: "run", sense #0
    ↓
Check Free Dictionary API (0.5s)
    ↓
API Success? ─YES─► Use API data + AI enhancement (hybrid_api_ai)
    │                     ↓
    │               ThreadPoolExecutor (4 workers)
    │                     ├─► Agent 1: Core metadata
    │                     ├─► Agent 2: Examples
    │                     ├─► Agent 3: Related words
    │                     └─► Agent 4: Usage notes
    │                     ↓
    │               Merge results (5.25s total)
    │
    NO ──► Pure AI mode (ai_only)
              ↓
        AI word sense discovery
              ↓
        ThreadPoolExecutor (4 workers)
              ├─► Agent 1: Core metadata
              ├─► Agent 2: Examples
              ├─► Agent 3: Related words
              └─► Agent 4: Usage notes
              ↓
        Merge results (~6-7s total)
```

### Logging

The service logs data source decisions for monitoring:

```
# API Success (Common words)
[hello] Basic data: Using FREE API (hybrid_api_ai)
[run] Detailed sense #0: Using API basic data + AI enhancement (hybrid)
[run] Detailed sense #0: Using _fetch_enhanced_sense (API data + 4 AI agents)

# API Failure (Rare/Non-existent words)
[xyzqwerty123] Basic data: Using AI (ai_only) - API failed: API returned status 404
[xyzqwerty123] Detailed sense #0: Using AI only - API failed: API returned status 404
[xyzqwerty123] Detailed sense #0: Using _fetch_detailed_sense (Pure AI with 4 agents)
```

## API Endpoints

### Dictionary Endpoints
- `POST /api/dictionary` - Dictionary lookup with section-based loading
  - `section=basic` - Basic info (pronunciation, total senses) ~0.5-1s
  - `section=etymology` - Etymology and root analysis ~2-3s
  - `section=word_family` - Related words and forms ~2-3s
  - `section=usage_context` - Modern usage context ~3-4s
  - `section=cultural_notes` - Cultural significance ~3-4s
  - `section=frequency` - Usage frequency ~2-3s
  - `section=detailed_sense&index=0` - Full sense analysis ~5.25s

- `GET /api/dictionary/test` - Test endpoint

### OpenAI Endpoints
- `POST /api/transcribe` - Audio transcription (Whisper)
- `POST /api/image` - Image analysis with prompts (Vision API)

### Web Services
- `GET /api/search` - Web search (Serper API)
- `GET /api/scrape` - Web scraping (Browserless)

## Technology Stack

### Core Framework
- **Flask** - Web framework (Python 3.10.13)
- **Flask-CORS** - Cross-origin support

### AI/LLM
- **DeepSeek** - Primary LLM for dictionary service (via Agno framework)
- **OpenAI** - Audio transcription (Whisper) and vision analysis
- **Agno Framework** - Agent orchestration

### APIs
- **Free Dictionary API** - Basic word data (https://dictionaryapi.dev)
- **Serper API** - Web search
- **Browserless API** - Web scraping

### Python Libraries
- **Pydantic** - Data validation and schemas
- **python-dotenv** - Environment variables
- **requests** - HTTP client
- **concurrent.futures** - Parallel execution

## Performance Characteristics

### Dictionary Service

| Operation | Time | Notes |
|-----------|------|-------|
| Basic data (API success) | 0.5-1s | No AI required |
| Basic data (API fail) | 6-7s | AI word sense discovery |
| Etymology/Word Family | 2-3s | Single AI agent |
| Usage Context/Cultural Notes | 3-4s | Single AI agent |
| Detailed Sense (hybrid) | 5.25s | 4 parallel AI agents |
| Detailed Sense (pure AI) | 6-7s | 4 parallel AI agents |

### Benefits of Hybrid Architecture

- **60-70% faster** than pure AI approach (5-6s vs 15-18s)
- **30-50% fewer AI calls** (cost savings)
- **Better audio quality** - Real pronunciation from Wikimedia Commons
- **Comprehensive data** - Combines free API with AI enhancements
- **Automatic fallback** - Gracefully handles API failures

## Configuration

### Required Environment Variables

```env
# Dictionary Service
DEEPSEEK_API_KEY=your_deepseek_api_key

# OpenAI Services
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_BASE=your_proxy_base_url  # Optional, for proxy
X-PP-TOKEN=your_proxy_token          # Optional, for proxy

# Web Services
SERPER_API_KEY=your_serper_api_key
BROWSERLESS_API_KEY=your_browserless_api_key

# Flask
FLASK_ENV=development  # or production
```

### Logging Configuration

Set logging level in your application:

```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## Project Structure

```
PP-AI-Service/
├── ai_svc/                    # Core AI service modules
│   ├── __init__.py
│   ├── openai.py             # OpenAI API integrations
│   ├── tool.py               # Utility functions
│   └── dictionary/           # Dictionary service
│       ├── __init__.py
│       ├── service.py        # Main service (4-agent architecture)
│       ├── schemas.py        # Pydantic models
│       ├── prompts.py        # AI prompts
│       └── enums.py          # Enumerations
├── static/                   # Static assets
├── templates/                # HTML templates
├── docs/                     # Documentation
├── app.py                    # Main Flask application
├── requirements.txt          # Python dependencies
├── Dockerfile               # Docker configuration
├── compose.yaml             # Docker Compose
└── .env                     # Environment variables (not in git)
```

## Key Design Principles

1. **Hybrid First**: Always try free API before using AI
2. **Parallel Execution**: Use ThreadPoolExecutor for concurrent AI calls
3. **Graceful Degradation**: Automatic fallback to pure AI mode
4. **Logging**: Track API vs AI decisions for monitoring
5. **Modular Design**: Separate schemas, prompts, and service logic
6. **Type Safety**: Pydantic models for validation
7. **Cost Optimization**: Minimize AI calls, use token limits

## Performance Optimization Techniques

1. **Token Limits**: Reduced per-agent tokens (300/200/200/150)
2. **Parallel Execution**: 4 agents run concurrently
3. **API First**: Free API for basic data (0 cost)
4. **Timeout Management**: 30-45s timeouts prevent hanging
5. **No Retries**: max_retries=0 for faster failure detection
6. **Model Selection**: DeepSeek for cost-effective performance

## Future Improvements

### Potential Optimizations
- **Streaming**: Stream partial results as agents complete
- **Caching**: Redis/in-memory cache for frequent words
- **Model Switching**: Try faster models (Groq, Cerebras) for specific tasks
- **Batch Processing**: Process multiple words in parallel
- **CDN**: Cache pronunciation audio URLs

### Potential Features
- **Grammar Analysis**: Grammar correction agent
- **Translation**: Multi-language support
- **Sentiment Analysis**: Tone and sentiment detection
- **AutoGen Integration**: Data analysis and web research agents

## Monitoring and Debugging

### Log Analysis

Monitor these patterns:
- API success rate: `grep "Using FREE API" logs`
- AI fallback rate: `grep "Using AI (ai_only)" logs`
- Performance: `grep "execution_time" logs`
- Errors: `grep "ERROR" logs`

### Performance Testing

```bash
# Test basic lookup
python test_logging.py

# Test detailed sense
python test_parallel_detailed_sense.py

# Test all features
python test_all_features.py
```

### Health Checks

- `/` - Homepage (should return 200)
- `/api/dictionary/test` - Dictionary test endpoint
- Check logs for API failures and slow responses

## Security Considerations

1. **API Keys**: Never commit `.env` file
2. **Docker**: Runs as non-root user `appuser`
3. **File Uploads**: Validated and cleaned up after processing
4. **CORS**: Configure allowed origins in production
5. **Rate Limiting**: Implement for production (not included)
6. **HTTPS**: Use reverse proxy (Nginx/Apache) in production

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions including:
- Docker setup
- GCP deployment
- SSL/HTTPS configuration
- Production best practices

## See Also

- [API Usage Guide](API.md) - Detailed API documentation
- [Deployment Guide](DEPLOYMENT.md) - Production deployment
- [Contributing Guide](../AGENTS.md) - For AI agents working on this codebase
