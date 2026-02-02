# AGENTS.md - PP-AI-Service Codebase Guide

This document provides essential information for AI agents working in the PP-AI-Service codebase.

## Project Overview

PP-AI-Service is a **Flask-based web service** that provides AI-powered functionality including:
- Audio transcription (OpenAI Whisper)
- Image analysis (OpenAI Vision API)
- Web search (Serper API)
- Web scraping (Browserless)
- Data analysis with AutoGen agents

The application is designed to run in both development and production environments, with Docker support for containerized deployment.

## Essential Commands

### Development
```bash
# Start the Flask application (development mode)
python app.py

# Start with production settings
FLASK_ENV=production python app.py
```

### Docker Operations
```bash
# Build Docker image
docker build . -t ai

# Run Docker container
docker run --rm -p 8000:8000 -d ai

# Using Docker Compose
docker compose up

# Stop Docker container (using provided script)
./docker_stop.sh
```

### Scripts
- `./start.sh` - Starts the Flask app in background with logging
- `./stop.sh` - Stops the background process
- `./docker_start.sh` - Builds and runs Docker container
- `./docker_stop.sh` - Stops Docker container

## Project Structure

```
PP-AI-Service/
├── ai_svc/                    # Core AI service modules
│   ├── __init__.py
│   ├── openai.py             # OpenAI API integrations
│   └── tool.py               # Utility functions (search, image detection)
├── static/                   # Static assets
│   ├── logo.png
│   └── uploads/              # Temporary file uploads
├── templates/                # HTML templates
│   ├── index.html
│   └── page_not_found.html
├── app.py                    # Main Flask application
├── data_analyze.py           # AutoGen data analysis agent
├── web_research.py           # Web research agent
├── requirements.txt          # Python dependencies
├── Dockerfile               # Docker configuration
├── compose.yaml             # Docker Compose configuration
└── .env.example             # Environment variables template
```

## Code Patterns and Conventions

### Flask Application Structure
- Main application entry point: `app.py`
- Uses Flask-CORS for cross-origin support
- Environment-based configuration (development/production)
- Runs on port 8000 by default
- Error handling for 404 pages redirects to index

### API Endpoints
- `/api/transcribe` (POST) - Audio transcription
- `/api/image` (POST) - Image analysis with prompts
- `/api/search` (GET) - Web search
- `/api/scrape` (GET) - Web scraping

### Environment Variables
Required environment variables (copy from `.env.example`):
- `OPENAI_API_KEY` - OpenAI API key
- `OPENAI_API_BASE` - OpenAI API base URL (for proxy)
- `X-PP-TOKEN` - Proxy authentication token
- `SERPER_API_KEY` - Serper API key for search
- `BROWSERLESS_API_KEY` - Browserless API key for scraping
- `FLASK_ENV` - Environment (development/production)

### Import Patterns
- Use absolute imports: `from ai_svc import tool, openai`
- Load environment variables with `dotenv.load_dotenv()`
- Configure logging at application startup

### Error Handling
- API endpoints return JSON responses with appropriate HTTP status codes
- File operations include cleanup (delete temporary files)
- Input validation for required parameters

## Testing and Quality

**Note**: No test suite or linting configuration was found in the codebase.

## Deployment

### Docker Configuration
- Uses Python 3.10.13 slim base image
- Non-privileged user `appuser` for security
- Chinese PyPI mirror configured for faster installs in China
- Uploads directory created with appropriate permissions

### Production Considerations
- Set `FLASK_ENV=production` for production deployment
- Use reverse proxy (Nginx/Apache) with HTTPS in production
- Configure SSL certificates (see README.md for GCP deployment guide)
- Monitor logs at `~/ppaiservice.log` when using start.sh

## AutoGen Integration

The project includes two AutoGen-based agents:

1. **Data Analysis Agent** (`data_analyze.py`):
   - Uses AutoGen's group chat with user proxy and programmer agents
   - Configurable via `OAI_CONFIG_LIST` file

2. **Web Research Agent** (`web_research.py`):
   - Uses GPT Assistant Agent with function calling
   - Integrates with web scraping and search tools

## Important Gotchas

1. **File Uploads**: Audio files are temporarily saved to `static/uploads/` and deleted after processing
2. **Image Processing**: Images are converted to base64 for OpenAI Vision API
3. **API Configuration**: Requires `OAI_CONFIG_LIST` file for AutoGen agents (see `OAI_CONFIG_LIST.example`)
4. **Chinese Network**: Dockerfile uses Aliyun PyPI mirror for faster installs in China
5. **Port Configuration**: Application runs on port 8000 (configurable via environment)

## Development Workflow

1. Copy `.env.example` to `.env` and fill in API keys
2. Install dependencies: `pip install -r requirements.txt`
3. Run development server: `python app.py`
4. Test API endpoints with appropriate tools (curl, Postman, etc.)
5. For Docker testing: `./docker_start.sh`

## File Naming Conventions

- Python files use snake_case: `data_analyze.py`, `web_research.py`
- Shell scripts use .sh extension with descriptive names
- Configuration files use descriptive names with appropriate extensions

## Security Notes

- Never commit `.env` file with API keys
- Docker runs as non-root user for security
- File uploads are validated and sanitized
- API keys are loaded from environment variables only