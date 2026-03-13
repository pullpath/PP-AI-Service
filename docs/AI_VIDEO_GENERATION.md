# AI-Generated Phrase Video Feature

Generate educational videos for English phrases using AI (Volcengine Ark - Doubao SeeDance).

## Overview

The AI video generation feature creates short educational videos (4-12 seconds) with automatic audio that demonstrate English phrases in natural conversational contexts. Videos are generated on-demand with customizable styles, perfect for language learning applications.

**Integration**: Accessed as a dictionary section (`ai_generated_phrase_video`) via the Dictionary API.

**Model**: `doubao-seedance-1-5-pro-251215` (audio-enabled)

## Quick Start

### 1. Setup

Add Volcengine API key to `.env`:
```env
ARK_API_KEY=your_volcengine_api_key
```

Get your API key from: https://console.volcengine.com/ark

Dependencies are already in `requirements.txt`:
```bash
pip install volcengine-python-sdk==5.0.16
```

### 2. Generate Your First Video

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "ai_generated_phrase_video",
    "phrase": "pipe down"
  }'
```

**Wait 30-120 seconds** (depending on video complexity), then you'll get:
```json
{
  "phrase": "pipe down",
  "ai_generated_phrase_video": {
    "task_id": "abc123",
    "video_url": "https://volcano-video.volccdn.com/...",
    "status": "completed",
    "style": "kids_cartoon",
    "duration": 5,
    "resolution": "480p",
    "ratio": "16:9"
  },
  "execution_time": 45.2,
  "success": true
}
```

## API Usage

### Request Format

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "any_word",
    "section": "ai_generated_phrase_video",
    "phrase": "the phrase to demonstrate"
  }'
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `word` | string | ✅ Yes | Any word (for dictionary API consistency) |
| `section` | string | ✅ Yes | Must be `"ai_generated_phrase_video"` |
| `phrase` | string | ✅ Yes | English phrase to generate video for |

### Response Format

**Success (200):**
```json
{
  "phrase": "pipe down",
  "ai_generated_phrase_video": {
    "task_id": "abc123xyz",
    "video_url": "https://...",
    "status": "completed",
    "style": "kids_cartoon",
    "duration": 5,
    "resolution": "480p",
    "ratio": "16:9"
  },
  "execution_time": 45.2,
  "success": true
}
```

**Error (400/500/504):**
```json
{
  "error": "Missing required parameter: phrase",
  "success": false,
  "execution_time": 0.01
}
```

## Video Styles

### Current: Kids Cartoon (Default)
**Best for:** Young English learners (ages 3-10)

**Characteristics:**
- Peppa Pig-style 2D animation
- Colorful, cheerful, simple outlines
- Bright, friendly settings
- Cute characters with expressive faces
- Educational and fun tone

### Future Styles (Planned)
- **Business Professional**: Modern corporate environment, workplace scenarios
- **Realistic**: Natural, everyday situations with authentic environments
- **Anime**: Japanese anime style with vibrant colors

**Note:** Currently all videos use the default `kids_cartoon` style. Custom style support via `entry_index` parameter encoding is planned for future releases.

## Examples

### Basic Usage
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "ai_generated_phrase_video",
    "phrase": "break a leg"
  }'
```

### Common Phrases

```bash
# Social interaction
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "social",
    "section": "ai_generated_phrase_video",
    "phrase": "break the ice"
  }'

# Asking for quiet
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "quiet",
    "section": "ai_generated_phrase_video",
    "phrase": "pipe down"
  }'

# Encouragement
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "support",
    "section": "ai_generated_phrase_video",
    "phrase": "hang in there"
  }'

# Business communication
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "business",
    "section": "ai_generated_phrase_video",
    "phrase": "touch base"
  }'
```

### Save Response to File

```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "ai_generated_phrase_video",
    "phrase": "pipe down"
  }' \
  -o response.json

# Check if successful
jq '.success' response.json

# Extract video URL
jq -r '.ai_generated_phrase_video.video_url' response.json
```

### Download Generated Video

```bash
# 1. Generate video and save response
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "ai_generated_phrase_video",
    "phrase": "pipe down"
  }' \
  -o response.json

# 2. Extract video URL
VIDEO_URL=$(jq -r '.ai_generated_phrase_video.video_url' response.json)

# 3. Download video
curl -o pipe_down_video.mp4 "$VIDEO_URL"
```

### Batch Processing

```bash
#!/bin/bash
# Generate videos for multiple phrases

PHRASES=("pipe down" "break the ice" "touch base" "hang in there")

for phrase in "${PHRASES[@]}"; do
  echo "Generating video for: $phrase"
  curl -X POST http://localhost:8000/api/dictionary \
    -H "Content-Type: application/json" \
    -d "{
      \"word\": \"hello\",
      \"section\": \"ai_generated_phrase_video\",
      \"phrase\": \"$phrase\"
    }" \
    -o "${phrase// /_}_response.json"
  echo "Done: ${phrase// /_}_response.json"
  echo ""
done
```

## Programming Examples

### Python

```python
import requests

response = requests.post(
    'http://localhost:8000/api/dictionary',
    headers={'Content-Type': 'application/json'},
    json={
        'word': 'hello',
        'section': 'ai_generated_phrase_video',
        'phrase': 'pipe down'
    }
)

data = response.json()

if data.get('success'):
    video_info = data['ai_generated_phrase_video']
    print(f"Video URL: {video_info['video_url']}")
    print(f"Task ID: {video_info['task_id']}")
    print(f"Execution time: {data['execution_time']}s")
else:
    print(f"Error: {data.get('error')}")
```

### JavaScript

```javascript
fetch('http://localhost:8000/api/dictionary', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    word: 'hello',
    section: 'ai_generated_phrase_video',
    phrase: 'pipe down'
  })
})
.then(res => res.json())
.then(data => {
  if (data.success) {
    console.log('Video URL:', data.ai_generated_phrase_video.video_url);
    console.log('Task ID:', data.ai_generated_phrase_video.task_id);
  } else {
    console.error('Error:', data.error);
  }
});
```

## Error Handling

### Missing Phrase Parameter
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "ai_generated_phrase_video"
  }'
# Returns 400: Missing required parameter: phrase
```

### Invalid Section
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "hello",
    "section": "invalid_section",
    "phrase": "test"
  }'
# Returns 400: Invalid section
```

### Timeout
```json
{
  "error": "Task did not complete within 300 seconds",
  "success": false,
  "execution_time": 300.1
}
```

**Solution:** Retry the request. If issue persists, check Volcengine API status.

## Performance

| Configuration | Typical Time |
|---------------|--------------|
| 480p, 5s (default) | 30-60 seconds |
| 720p, 5s | 60-90 seconds |
| 1080p, 5s | 90-150 seconds |
| 720p, 10s | 90-120 seconds |
| 1080p, 10s | 150-300 seconds |

**Current:** All videos use default 480p, 5s, 16:9, kids_cartoon settings (~30-60 seconds).

## Best Practices

### 1. Use Clear, Natural Phrases
```json
{
  "word": "hello",
  "section": "ai_generated_phrase_video",
  "phrase": "spill the beans"
}
```
Use conversational English phrases for best results.

### 2. Handle Long Generation Times
Video generation takes 30-120 seconds. Implement loading indicators in your frontend:

```javascript
// Show loading state
setLoading(true);

fetch('/api/dictionary', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    word: 'hello',
    section: 'ai_generated_phrase_video',
    phrase: 'pipe down'
  })
})
.then(res => res.json())
.then(data => {
  setLoading(false);
  if (data.success) {
    showVideo(data.ai_generated_phrase_video.video_url);
  }
});
```

### 3. Cache Video URLs
Video URLs are permanent - store them to avoid regenerating:
- Save to database for common phrases
- Use client-side caching
- Consider CDN caching for popular phrases

### 4. Provide User Feedback
```
⏳ Generating video... This usually takes 30-60 seconds.
✅ Video ready! [Play button]
❌ Generation failed. Please try again.
```

## Troubleshooting

### API Key Issues
```
Error: ARK_API_KEY environment variable is not set
```
**Solution:** Add `ARK_API_KEY=your_key` to `.env` file and restart server.

### Import Errors
```
ModuleNotFoundError: No module named 'volcenginesdkarkruntime'
```
**Solution:** `pip install volcengine-python-sdk==5.0.16`

### Generation Failures
Check logs for detailed error messages:
```bash
tail -f ~/ppaiservice.log
```

### Timeout Issues
If videos consistently timeout:
- Check Volcengine API status
- Verify API key is valid
- Check network connectivity

## Architecture

### Service Layer
**File:** `ai_svc/video.py`

```python
class VideoGenerationService:
    - __init__(): Initialize Ark client with API key
    - _build_prompt(): Generate style-specific prompts
    - _poll_task_status(): Poll until completion/timeout (1s intervals)
    - generate_phrase_video(): Main entry point
```

### Dictionary Integration
**File:** `ai_svc/dictionary/service.py`

```python
def _fetch_phrase_video_section(phrase, entry_index, start_time):
    # Validate phrase parameter
    # Call video_service.generate_phrase_video()
    # Return standardized dictionary response format
```

### Prompt Engineering
Each style includes:
1. **Visual prefix**: Style description (Peppa Pig-style, colorful, etc.)
2. **Scene context**: Environment setup
3. **Character style**: Character appearance details
4. **Dialogue**: Phrase usage in 3-5 sentences of natural conversation
5. **Tone**: Educational guidance
6. **Technical params**: Resolution, duration, ratio, watermark settings

## Limitations

- **Duration:** 4-12 seconds (configurable via code, default 4s for faster generation)
- **Resolution:** 480p/720p/1080p (hardcoded to 480p currently)
- **Style:** kids_cartoon only (fixed)
- **Aspect Ratio:** 16:9 (fixed)
- **Language:** English dialogue only
- **Audio:** Automatically generated (enabled by default)
- **Watermark:** Enabled (Volcengine requirement)
- **Concurrent Requests:** Limited by Volcengine API rate limits

## Audio Generation

Videos automatically include synchronized audio narration that matches the visual content. The audio is generated by the `doubao-seedance-1-5-pro-251215` model.

**Features:**
- ✅ Automatic lip-sync with character dialogue
- ✅ Natural voice narration
- ✅ Background ambient sounds
- ✅ Multi-language support (8 languages available)

**Current Configuration:**
- Audio generation: **Enabled by default**
- Cost: Included in video generation cost
- No explicit audio control parameter (yet)
- Language policy: **English-only dialogue/audio** (enforced via prompt constraints)
- Prompt flags: `--audio_language en`, `--camerafixed true`
- Default generation profile: 4 seconds, 480p, fixed camera (latency-optimized)

**Technical Details:**
- Model: `doubao-seedance-1-5-pro-251215` (audio-enabled)
- Previous model: `doubao-seedance-1-0-lite-t2v-250428` (text-only)
- Upgraded: March 2026

## Future Enhancements

Planned improvements:
- [ ] Parameter encoding via `entry_index` for custom style/duration/resolution/ratio
- [ ] Multiple style support (business, realistic, anime)
- [ ] Custom duration selection (UI/API parameter)
- [ ] Resolution options (UI/API parameter for 480p/720p/1080p)
- [ ] Aspect ratio options (16:9/9:16/1:1)
- [ ] Explicit audio control (enable/disable audio generation)
- [ ] First-frame image input (text+image content)
- [ ] Batch mode for cost savings (-batch suffix)
- [ ] Caching for common phrases
- [ ] Batch generation endpoint
- [ ] Progress tracking endpoint
- [ ] Subtitle generation (if API subtitle quality improves)

## Response Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `phrase` | string | Input phrase |
| `ai_generated_phrase_video` | object | Video generation results |
| `ai_generated_phrase_video.task_id` | string | Volcengine task ID |
| `ai_generated_phrase_video.video_url` | string | Permanent video URL |
| `ai_generated_phrase_video.status` | string | Status (`completed`) |
| `ai_generated_phrase_video.style` | string | Video style (`kids_cartoon`) |
| `ai_generated_phrase_video.duration` | integer | Duration in seconds (5) |
| `ai_generated_phrase_video.resolution` | string | Resolution (`480p`) |
| `ai_generated_phrase_video.ratio` | string | Aspect ratio (`16:9`) |
| `execution_time` | float | Total time in seconds |
| `success` | boolean | Success status |
| `error` | string | Error message (if failed) |

## Recommended Phrases for Testing

Educational phrases suitable for video generation:
- "break the ice" - social interaction
- "pipe down" - asking for quiet
- "time for bed" - daily routine
- "touch base" - business communication
- "hang in there" - encouragement
- "spill the beans" - revealing secrets
- "think outside the box" - creativity
- "catch you later" - goodbye
- "break a leg" - good luck
- "hit the books" - studying

## Support

For issues:
- Check logs: `tail -f ~/ppaiservice.log`
- Review [AGENTS.md](../AGENTS.md) for development guidelines
- Test with simple phrases first
- Verify API key is valid
- Check Volcengine API console for quota/status

---

**Powered by Volcengine Ark (Doubao SeeDance)** | **Integration: Dictionary API Section**
