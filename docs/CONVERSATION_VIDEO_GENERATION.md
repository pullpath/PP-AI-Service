# Conversation-Based Video Generation

## Overview

Enhanced AI video generation system with **2-stage architecture** that creates contextual educational videos for English phrases.

**Before**: Video API generated generic dialogue with no specific scenario
**After**: Conversation generation agent creates meaningful scenarios, then video generation uses the conversation script

## Architecture

### Stage 1: Conversation Generation (~2-5s)
- **Agent**: DeepSeek-powered conversation script generator
- **Input**: Phrase + Style (kids_cartoon, business_professional, realistic, anime)
- **Output**: Structured conversation script with:
  - `scenario`: 1-2 sentence setting description
  - `dialogue`: 2-6 dialogue lines with character names
  - `phrase_explanation`: Brief explanation of phrase usage

### Stage 2: Video Generation (~30-60s)
- **API**: Volcengine Ark (Doubao SeeDance model)
- **Input**: Conversation script + Video parameters
- **Output**: Generated video URL with animated conversation

## Key Features

### ✅ Scenario-Based Conversations
- Natural, contextual dialogue that demonstrates phrase meaning
- Appropriate settings for each style (playground for kids, office for business, etc.)
- Multiple characters with distinct personalities

### ✅ Style-Specific Prompts
Each style has tailored conversation generation:
- **kids_cartoon**: Simple vocabulary, cheerful tone, Peppa Pig style
- **business_professional**: Professional vocabulary, workplace scenarios
- **realistic**: Everyday situations, natural speech patterns
- **anime**: Expressive dialogue, dynamic personalities

### ✅ Parameterized Video Settings
All video properties are configurable via API:
- `style`: kids_cartoon, business_professional, realistic, anime
- `duration`: 4-12 seconds
- `resolution`: 480p, 720p, 1080p
- `ratio`: 16:9, 9:16, 1:1

### ✅ Database & Cache Integration
- Conversation scripts stored in SQLite (video_tasks.db + cache.db)
- Automatic migration for existing databases
- Conversation script included in all API responses

## API Usage

### Endpoint
```
POST /api/dictionary
```

### Request Body
```json
{
  "word": "speak",
  "section": "ai_generated_phrase_video",
  "phrase": "pipe up",
  "style": "kids_cartoon",
  "duration": 5,
  "resolution": "480p",
  "ratio": "16:9"
}
```

### Response (Immediate)
```json
{
  "phrase": "pipe up",
  "conversation_script": {
    "scenario": "At Peppa's playroom. George is being too loud while Daddy Pig is working.",
    "dialogue": [
      {
        "character": "Daddy Pig",
        "text": "George, could you pipe down a bit? I'm trying to concentrate."
      },
      {
        "character": "George",
        "text": "Okay, Daddy. I'll play quietly."
      },
      {
        "character": "Peppa",
        "text": "Come on George, let's do a puzzle instead!"
      }
    ],
    "phrase_explanation": "Pipe down means to be quiet or make less noise, used when someone is being too loud."
  },
  "ai_generated_phrase_video": {
    "task_id": "abc123...",
    "status": "pending",
    "poll_url": "/api/dictionary",
    "poll_params": {
      "section": "video_status",
      "task_id": "abc123..."
    }
  },
  "execution_time": 3.2,
  "success": true
}
```

### Polling for Status
```json
{
  "word": "speak",
  "section": "video_status",
  "task_id": "abc123..."
}
```

### Response (Completed)
```json
{
  "task_id": "abc123...",
  "phrase": "pipe up",
  "conversation_script": { ... },
  "status": "completed",
  "progress": 100,
  "video_url": "https://example.com/video.mp4",
  "style": "kids_cartoon",
  "duration": 5,
  "created_at": "2025-03-13T10:30:00",
  "updated_at": "2025-03-13T10:31:23",
  "success": true
}
```

## Implementation Details

### Modified Files

#### 1. `ai_svc/dictionary/schemas.py`
- Added `DialogueLine` model
- Added `ConversationScript` model with scenario, dialogue, explanation

#### 2. `ai_svc/dictionary/prompts.py`
- Added `get_conversation_script_prompt()` with style-specific templates
- Includes examples for kids_cartoon and business_professional styles

#### 3. `ai_svc/dictionary/service.py`
- Added conversation generation agent (DeepSeek with temperature=0.7)
- Modified `_fetch_phrase_video_section()` to generate conversation first
- Added `_generate_conversation_script()` method
- Updated `lookup_section()` to accept style/duration/resolution/ratio parameters
- Updated `get_video_status()` to include conversation_script in response

#### 4. `ai_svc/dictionary/video.py`
- Updated `_build_prompt()` to accept `conversation_script` parameter
- Modified prompt generation to use conversation script when available
- Fallback to phrase-only mode if no conversation script provided

#### 5. `ai_svc/dictionary/video_task_service.py`
- Added `conversation_script` field to database schema
- Updated `create_task()` to store conversation_script as JSON
- Updated `get_task_status()` to parse and return conversation_script
- Updated `_generate_video_background()` to pass conversation_script to video service

#### 6. `ai_svc/dictionary/cache_service.py`
- Added `conversation_script` field to `ai_phrase_video_cache` table
- Updated `set_ai_phrase_video()` to store conversation_script as JSON
- Automatic migration for existing databases

### Database Schema Changes

#### video_tasks.db
```sql
ALTER TABLE video_tasks ADD COLUMN conversation_script TEXT;
```

#### cache.db
```sql
ALTER TABLE ai_phrase_video_cache ADD COLUMN conversation_script TEXT;
```

Both changes include automatic migration logic that checks for column existence before adding.

## Testing

### Test Script
```bash
python test_conversation_video.py "pipe up" "speak" "kids_cartoon"
```

### Test Coverage
- ✅ Conversation generation
- ✅ Video generation with conversation script
- ✅ Database storage and retrieval
- ✅ API response includes conversation_script
- ✅ Status polling returns conversation_script
- ✅ Parameter customization (style, duration, etc.)

## Benefits

### 🎯 Better Learning Context
Videos now have meaningful scenarios that help learners understand:
- **When** to use the phrase (situation)
- **How** to use it naturally (dialogue flow)
- **Why** it's appropriate (explanation)

### 🚀 Improved Video Quality
- No more generic "pipe up? OK I'll pipe up" conversations
- Each video tells a mini-story
- Visual context matches dialogue context

### 🔧 Frontend Flexibility
- Conversation script available immediately (no waiting for video)
- Can display conversation while video generates
- Can show conversation as subtitles/transcript
- Users can understand phrase before video completes

### 📊 Better Data Structure
- Conversation scripts stored for analytics
- Can improve prompts based on successful conversations
- Easy to add new styles without changing video generation

## Future Enhancements

### Potential Improvements
1. **Multiple Conversations per Phrase**: Generate 2-3 variations, pick best
2. **Conversation Rating**: Let users rate conversation quality
3. **Custom Characters**: Allow users to specify character names/types
4. **Difficulty Levels**: Beginner/Intermediate/Advanced conversation complexity
5. **Cultural Context**: Add cultural notes to conversation explanations
6. **Voice Consistency**: Map character names to consistent voice types

### Performance Optimizations
1. **Cache Common Phrases**: Pre-generate conversations for top 100 phrases
2. **Parallel Generation**: Generate video while conversation is being created
3. **Conversation Templates**: Template-based generation for faster response

## Backward Compatibility

✅ **Fully backward compatible**:
- Old video tasks without conversation_script still work
- Video generation falls back to phrase-only mode if no conversation
- Database migration handles existing data gracefully
- API still accepts requests without style/duration parameters (uses defaults)

## Migration Guide

### For Existing Deployments
1. Pull latest code
2. Restart service (automatic database migration on startup)
3. Test with: `python test_conversation_video.py`
4. Update frontend to display conversation_script (optional)

### For Frontend Integration
```javascript
// Send request with new parameters
const response = await fetch('/api/dictionary', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    word: 'speak',
    section: 'ai_generated_phrase_video',
    phrase: 'pipe up',
    style: 'kids_cartoon',
    duration: 5
  })
});

const data = await response.json();

// Display conversation immediately
if (data.conversation_script) {
  displayConversation(data.conversation_script);
}

// Poll for video
pollVideoStatus(data.ai_generated_phrase_video.task_id);
```

## Troubleshooting

### Common Issues

**Conversation generation fails**
- Check DEEPSEEK_API_KEY is set
- Verify phrase is not empty
- Check logs for AI agent errors

**Video generation fails with conversation script**
- Verify ARK_API_KEY is valid
- Check conversation script JSON is valid
- Ensure dialogue lines are in English

**Database migration errors**
- Backup database first: `cp ai_svc/dictionary/*.db backups/`
- Delete and restart: removes all cached data but fixes schema issues

### Debug Logging
```python
import logging
logging.basicConfig(level=logging.INFO)
```

Look for log messages:
- `[ai_generated_phrase_video] Stage 1: Generating conversation script...`
- `[ConversationScript] Generated for 'phrase': X lines...`
- `[ai_generated_phrase_video] Stage 2: Creating async video task...`

## Performance Metrics

### Timing
- Conversation generation: **2-5 seconds** (DeepSeek API)
- Video generation: **30-60 seconds** (Volcengine API)
- Total user-facing response: **2-5 seconds** (conversation + task creation)

### Resource Usage
- Conversation agent: ~512 tokens max
- Database: ~1-2 KB per conversation script
- Cache hit rate: Expected 60-80% for common phrases

## Conclusion

The conversation-based video generation system significantly improves video quality by providing meaningful, contextual scenarios for English phrase learning. The 2-stage architecture ensures fast initial response times while maintaining flexibility for future enhancements.
