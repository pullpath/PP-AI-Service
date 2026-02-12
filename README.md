# PP-AI-Service

AI-powered Flask web service providing dictionary lookups, audio transcription, image analysis, and web services.

## Features

### 🎯 Dictionary Service (Hybrid API + AI)
- **60-70% faster** than pure AI (5-6s vs 15-18s)
- **4-agent parallel architecture** for optimal performance
- **Entry-aware architecture** with per-entry pronunciation
- **Two-dimensional indexing** `(entry_index, sense_index)` for precise sense addressing
- **Hybrid approach**: Free Dictionary API + DeepSeek AI enhancement
- **Automatic fallback**: Pure AI mode if API fails
- **Section-based loading**: Load only what you need
- **Comprehensive data**: Etymology, word family, usage context, cultural notes, detailed sense analysis

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

# OpenAI Services
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_BASE=your_proxy_url  # Optional
X-PP-TOKEN=your_proxy_token     # Optional

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

# Detailed sense (~5.25s with 4-agent parallel)
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"word":"run","section":"detailed_sense","index":0}'
```

**Available sections**: `basic`, `etymology`, `word_family`, `usage_context`, `cultural_notes`, `frequency`, `detailed_sense`

See [docs/API.md](docs/API.md) for complete API documentation.

### Other Endpoints

- `POST /api/transcribe` - Audio transcription
- `POST /api/image` - Image analysis
- `GET /api/search?q=query` - Web search
- `GET /api/scrape?url=url` - Web scraping

## Performance

### Dictionary Service

| Operation | Time | Architecture |
|-----------|------|--------------|
| Basic info | 0.5-1s | Free API (no AI) |
| Etymology/Word Family | 2-3s | Single AI agent |
| Detailed Sense | **5.25s** | **4 parallel AI agents** |

**Evolution**: Sequential (10-13s) → 3 agents (6.5s) → **4 agents (5.25s)** ✨

### 4-Agent Breakdown

- **Agent 1**: Core metadata (definition, POS, register) - 300 tokens
- **Agent 2**: Examples & collocations (3 each) - 200 tokens  
- **Agent 3**: Related words (synonyms, antonyms, phrases) - 200 tokens
- **Agent 4**: Usage notes (2-3 sentences) - 150 tokens

All agents run in parallel using `ThreadPoolExecutor` with optimized token limits.

## Project Structure

```
PP-AI-Service/
├── ai_svc/                    # Core AI services
│   ├── dictionary/           # Dictionary service (4-agent)
│   │   ├── service.py        # Main service logic
│   │   ├── schemas.py        # Pydantic models
│   │   ├── prompts.py        # AI prompts
│   │   └── enums.py          # Enumerations
│   ├── openai.py             # OpenAI integrations
│   └── tool.py               # Web search/scraping
├── docs/                     # Documentation
│   ├── ARCHITECTURE.md       # System architecture
│   ├── API.md                # API usage guide
│   └── DEPLOYMENT.md         # Deployment guide
├── static/                   # Static files
├── templates/                # HTML templates
├── app.py                    # Flask application
├── requirements.txt          # Dependencies
├── Dockerfile               # Docker config
└── compose.yaml             # Docker Compose
```

## Documentation

- **[Architecture](docs/ARCHITECTURE.md)** - System design, 4-agent architecture, data flow
- **[API Guide](docs/API.md)** - Complete API reference with examples
- **[Deployment](docs/DEPLOYMENT.md)** - Production deployment (Docker, GCP, HTTPS)
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
✅ **Parallel Execution** - 4 agents run concurrently  
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
