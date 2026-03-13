# PP-AI-Service

AI-powered Flask web service providing dictionary lookups, audio transcription, image analysis, and web services.

## Features

### 🎯 Dictionary Service (Hybrid API + AI)
- **75% faster perceived performance** with progressive loading (2.5s core vs 5s monolithic)
- **2+1+1 agent architecture** with separate endpoints for progressive loading
- **Dynamic prompt optimization**: 20-40% token reduction based on API data
- **Entry-aware architecture** with per-entry pronunciation
- **Two-dimensional indexing** `(entry_index, sense_index)` for precise sense addressing
- **Progressive loading**: Core sense (2-3s) → Examples (1.5-2s) → Usage notes (1-1.5s)
- **Hybrid approach**: Free Dictionary API + DeepSeek AI enhancement
- **Automatic fallback**: Pure AI mode if API fails
- **Section-based loading**: Load only what you need
- **Comprehensive data**: Etymology, word family, usage context, cultural notes, detailed sense analysis

### 🎬 AI Video Generation
- **Conversation-based video generation** with 2-stage architecture (NEW)
- Educational phrase videos with contextual scenarios
- 4 style options: kids_cartoon, business_professional, realistic, anime
- Parameterized: style, duration (4-12s), resolution, aspect ratio
- Automatic audio generation with lip-sync
- See [docs/CONVERSATION_VIDEO_GENERATION.md](docs/CONVERSATION_VIDEO_GENERATION.md) for details

### 🎙️ Audio Transcription
- OpenAI Whisper integration
- High-quality audio-to-text conversion

### 👁️ Image Analysis
- OpenAI Vision API integration
- Context-aware image understanding

### 🌐 Web Services
- Web search via Serper API
- Web scraping via Browserless

## Quick Start

### Installation

```bash
# Clone repository
git clone <repository-url>
cd PP-AI-Service

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create `.env` file:

```env
# Dictionary Service
DEEPSEEK_API_KEY=your_deepseek_api_key

# AI Video Generation (optional - for ai_generated_phrase_video section)
ARK_API_KEY=your_volcengine_api_key

# OpenAI Services
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_BASE=your_proxy_url  # Optional
X-PP-TOKEN=your_proxy_token     # Optional

# Bilibili API (optional - for subtitle access in video search)
# Get these from browser developer tools after logging into Bilibili
BILIBILI_SESSDATA=your_sessdata_cookie
BILIBILI_BILI_JCT=your_bili_jct_cookie
BILIBILI_BUVID3=your_buvid3_cookie

# Web Services
SERPER_API_KEY=your_serper_api_key
BROWSERLESS_API_KEY=your_browserless_api_key

# Flask
FLASK_ENV=development  # or production
```

### Running the Service

#### Development Mode

```bash
# Start Flask server
source venv/bin/activate
python app.py
```

#### Using Start Script (Background)

```bash
./start.sh  # Auto-detects venv, logs to ~/ppaiservice.log
./stop.sh   # Graceful shutdown
```

#### Docker

```bash
# Build and run
./docker_start.sh

# Or manually
docker build . -t ai
docker run --rm -p 8000:8000 -d ai

# Using Docker Compose
docker compose up

# Stop
./docker_stop.sh
```

## API Endpoints

### Dictionary API

```bash
# Basic info (fast, ~0.5s)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"basic"}'

# Core sense data (fast, ~2-3s with 2-agent parallel)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"detailed_sense","entry_index":0,"sense_index":0}'

# Examples (fast, ~1.5-2s) - NEW
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"examples","entry_index":0,"sense_index":0}'

# Bilibili Videos (educational content with timestamps)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"bilibili_videos"}'

# AI-Generated Phrase Video (NEW - requires ARK_API_KEY)
# Generates educational videos with audio (4-12 seconds)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"hello","section":"ai_generated_phrase_video","phrase":"pipe down"}'

# List AI Phrase Videos (NEW)
# Get all generated videos for a specific phrase
curl "http://localhost:8000/api/ai_phrase_videos?word=hello&phrase=pipe%20down"

# List with status filter
curl "http://localhost:8000/api/ai_phrase_videos?word=hello&phrase=pipe%20down&status=completed"
```

**Available sections**: `basic`, `etymology`, `word_family`, `usage_context`, `cultural_notes`, `frequency`, `detailed_sense`, `examples`, `usage_notes`, `bilibili_videos`, `ai_generated_phrase_video`

See [docs/API.md](docs/API.md) for complete API documentation.

### Other Endpoints

- `POST /api/transcribe` - Audio transcription
- `POST /api/image` - Image analysis
- `GET /api/search?q=query` - Web search
- `GET /api/scrape?url=url` - Web scraping
- `GET /api/ai_phrase_videos` - List AI-generated videos for a phrase

## Performance

### Dictionary Service

| Operation | Time | Architecture |
|-----------|------|--------------|
| Basic info | 0.5-1s | Free API (no AI) |
| Etymology/Word Family | 2-3s | Single AI agent |
| Detailed Sense (Core) | **2-3s** | **2 parallel AI agents** |
| Examples | **1.5-2s** | **1 AI agent** (NEW) |
| Usage Notes | **1-1.5s** | **1 AI agent** (NEW) |

**Evolution**: Sequential (10-13s) → 3 agents (6.5s) → 4 agents (5.25s) → **2+1+1 progressive (2.5s perceived)** ✨

### Progressive Loading Architecture

#### Core Sense (2 agents parallel, ~2-3s)
- **Agent 1**: Core metadata (definition, POS, register, domain, tone) - 300 tokens
- **Agent 2**: Related words (synonyms, antonyms, phrases) - 200 tokens

#### Separate Endpoints (load on-demand)
- **Examples endpoint**: Examples (2) + collocations (3) - 200 tokens, ~1.5-2s
- **Usage notes endpoint**: Usage guidance (2-3 sentences) - 150 tokens, ~1-1.5s

**Frontend Strategy**: Show core sense immediately (~2.5s), then load examples/notes progressively or on-demand for best UX.

## Project Structure

```
PP-AI-Service/
├── ai_svc/                    # Core AI services
│   ├── dictionary/           # Dictionary service (2+1+1 agents)
│   │   ├── service.py        # Main service logic
│   │   ├── schemas.py        # Pydantic models
│   │   ├── prompts.py        # AI prompts
│   │   └── enums.py          # Enumerations
│   ├── openai.py             # OpenAI integrations
│   └── tool.py               # Web search/scraping
├── docs/                     # Documentation
│   ├── ARCHITECTURE.md       # System architecture
│   ├── API.md                # API usage guide
│   ├── DEPLOYMENT.md         # Deployment guide
│   └── FRONTEND_MIGRATION_EXAMPLES_SPLIT.md  # Frontend migration guide
├── static/                   # Static files
├── templates/                # HTML templates
├── app.py                    # Flask application
├── requirements.txt          # Dependencies
├── Dockerfile               # Docker config
└── compose.yaml             # Docker Compose
```

## Documentation

### Core Features
- **[Architecture](docs/ARCHITECTURE.md)** - System design, 2+1+1 agent architecture, progressive loading
- **[API Reference](docs/API.md)** - Complete API documentation with examples
- **[Deployment](docs/DEPLOYMENT.md)** - Production deployment (Docker, GCP, HTTPS, Nginx)

### Dictionary Features
- **[Bilibili Search](docs/BILIBILI_SEARCH_ANALYSIS.md)** - Video search with subtitle timestamps
- **[Word Suggestions](docs/WORD_SUGGESTION_FEATURE.md)** - Smart word suggestions feature
- **[AI Video Generation](docs/AI_VIDEO_GENERATION.md)** - Generate educational videos for phrases

### Cache Management
- **[Cache Quick Start](docs/CACHE_QUICK_START.md)** - Quick guide to cache management
- **[Cache Management](docs/CACHE_MANAGEMENT.md)** - Detailed cache system documentation
- **[Cache Collision Fix](docs/CACHE_COLLISION_FIX_SUMMARY.md)** - Collision resolution details
- **[Cache Collision Visual](docs/CACHE_COLLISION_VISUAL.md)** - Visual guide to collision handling

### Development
- **[AGENTS.md](AGENTS.md)** - Guide for AI agents working on this codebase

## Technology Stack

- **Flask** - Web framework (Python 3.10.13)
- **DeepSeek** - Primary LLM (via Agno framework)
- **OpenAI** - Whisper (audio) + Vision (images)
- **Pydantic** - Data validation
- **Docker** - Containerization
- **Free Dictionary API** - Basic word data

## Key Features

✅ **Hybrid Architecture** - Free API + AI for best of both worlds  
✅ **Progressive Loading** - Show core data fast, load details on-demand  
✅ **2+1+1 Agent Split** - Core sense (2 agents) + Examples (1 agent) + Usage notes (1 agent)  
✅ **Dynamic Prompts** - 20-40% token reduction based on API data  
✅ **Automatic Fallback** - Graceful AI-only mode  
✅ **Logging** - Track API vs AI decisions  
✅ **Section Loading** - Progressive, on-demand data  
✅ **Cost Optimized** - Minimal AI calls, token limits  

## Development

```bash
# Activate virtual environment
source venv/bin/activate

# Run development server
python app.py

# Check logs (if using start.sh)
tail -f ~/ppaiservice.log
```

## Production Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for:
- Docker deployment
- GCP VM setup
- SSL/HTTPS configuration (Let's Encrypt)
- Nginx reverse proxy
- Auto-renewal setup

## Security

- ✅ API keys in `.env` (not committed)
- ✅ Docker runs as non-root user
- ✅ File uploads sanitized and cleaned up
- ✅ CORS configured
- ⚠️ Add rate limiting for production
- ⚠️ Use HTTPS in production

## Performance Tips

1. **Cache responses** - Frontend should cache section data
2. **Load progressively** - Show basic info first, then details
3. **Lazy load senses** - Only load visible senses
4. **Parallel requests** - Load independent sections in parallel
5. **Monitor logs** - Track API success rate vs AI fallback

## Contributing

See [AGENTS.md](AGENTS.md) for:
- Project overview
- Essential commands
- Code patterns
- Important gotchas
- Development workflow

## License

[Add your license here]

## Support

For issues:
- Check logs for errors
- Verify `.env` configuration
- Ensure API keys are valid
- Review [docs/API.md](docs/API.md) for usage

---

**Made with ❤️ using Flask + DeepSeek + OpenAI**
