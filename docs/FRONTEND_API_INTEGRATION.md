# Frontend API Integration Guide - Conversation-Based Video Generation

## What Changed

The `/api/dictionary` endpoint now supports **2-stage video generation** with conversation scripts. The API parameters expanded to allow video customization.

---

## API Request Changes

### Before (Old API)
```javascript
POST /api/dictionary
{
  "word": "quiet",
  "section": "ai_generated_phrase_video",
  "phrase": "pipe down"
}
```

### After (New API)
```javascript
POST /api/dictionary
{
  "word": "quiet",
  "section": "ai_generated_phrase_video",
  "phrase": "pipe down",
  
  // NEW: Optional video customization parameters
  "style": "kids_cartoon",        // default: "kids_cartoon"
  "duration": 5,                  // default: 5 (range: 4-12 seconds)
  "resolution": "480p",           // default: "480p"
  "ratio": "16:9"                 // default: "16:9"
}
```

### Available Parameter Values

```javascript
// Video styles
style: "kids_cartoon" | "business_professional" | "realistic" | "anime"

// Duration (seconds)
duration: 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12

// Resolution
resolution: "480p" | "720p" | "1080p"

// Aspect ratio
ratio: "16:9" | "9:16" | "1:1"
```

---

## API Response Changes

### Initial Response (Immediate - 2-5 seconds)

**NEW**: Now includes `conversation_script` object with scenario and dialogue.

```javascript
{
  "phrase": "pipe down",
  "ai_generated_phrase_video": {
    "task_id": "20240315abc123",
    "status": "pending",  // or "processing"
    
    // NEW: Conversation script (available immediately)
    "conversation_script": {
      "scenario": "At the library, two students are studying when one starts talking loudly on the phone.",
      "dialogue": [
        {
          "character": "Librarian",
          "text": "Excuse me, you need to pipe down. Other people are trying to study."
        },
        {
          "character": "Student",
          "text": "Oh, sorry! I didn't realize I was being so loud."
        }
      ],
      "phrase_explanation": "The librarian uses 'pipe down' to politely tell the student to be quieter in the library."
    },
    
    // Video properties
    "style": "kids_cartoon",
    "duration": 5,
    "resolution": "480p",
    "ratio": "16:9"
  },
  "execution_time": 3.2,
  "success": true
}
```

### Polling Response (After video completes - 30-60 seconds)

```javascript
GET /api/dictionary/video/status/{task_id}

{
  "task_id": "20240315abc123",
  "status": "completed",
  "video_url": "https://example.com/video.mp4",
  
  // Conversation script (same as initial response)
  "conversation_script": {
    "scenario": "At the library...",
    "dialogue": [...],
    "phrase_explanation": "..."
  },
  
  "style": "kids_cartoon",
  "duration": 5,
  "resolution": "480p",
  "ratio": "16:9",
  "created_at": "2024-03-15T10:30:00",
  "completed_at": "2024-03-15T10:30:45"
}
```

---

## Frontend Integration Pattern

### Step 1: Send Request with Optional Parameters

```javascript
async function generatePhraseVideo(phrase, options = {}) {
  const response = await fetch('http://localhost:8000/api/dictionary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      word: phrase.split(' ')[0],  // first word of phrase
      section: 'ai_generated_phrase_video',
      phrase: phrase,
      
      // Optional: customize video properties (uses defaults if omitted)
      style: options.style || 'kids_cartoon',
      duration: options.duration || 5,
      resolution: options.resolution || '480p',
      ratio: options.ratio || '16:9'
    })
  });
  
  return response.json();
}
```

### Step 2: Display Conversation Script Immediately

**NEW**: Show the conversation script to users right away (don't wait for video).

```javascript
const data = await generatePhraseVideo('pipe down');

// Extract conversation script (available immediately)
const { conversation_script, task_id } = data.ai_generated_phrase_video;

// Display conversation UI immediately
displayConversation({
  scenario: conversation_script.scenario,
  dialogue: conversation_script.dialogue,
  explanation: conversation_script.phrase_explanation
});

// Show loading state for video
showVideoLoading(task_id);
```

### Step 3: Poll for Video (Unchanged)

```javascript
async function pollVideoStatus(taskId) {
  const response = await fetch(
    `http://localhost:8000/api/dictionary/video/status/${taskId}`
  );
  const data = await response.json();
  
  if (data.status === 'completed') {
    displayVideo(data.video_url);
    return data;
  } else if (data.status === 'failed') {
    showError(data.error_message);
    return null;
  } else {
    // Still processing, poll again in 5 seconds
    setTimeout(() => pollVideoStatus(taskId), 5000);
  }
}
```

---

## Complete React/Vue Example

### React Component

```jsx
import React, { useState, useEffect } from 'react';

function PhraseVideoGenerator({ phrase }) {
  const [conversation, setConversation] = useState(null);
  const [videoUrl, setVideoUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [videoStyle, setVideoStyle] = useState('kids_cartoon');

  const generateVideo = async () => {
    setLoading(true);
    
    try {
      // Step 1: Generate video with custom style
      const response = await fetch('http://localhost:8000/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: phrase.split(' ')[0],
          section: 'ai_generated_phrase_video',
          phrase: phrase,
          style: videoStyle  // User-selected style
        })
      });
      
      const data = await response.json();
      const { conversation_script, task_id } = data.ai_generated_phrase_video;
      
      // Step 2: Display conversation immediately
      setConversation(conversation_script);
      
      // Step 3: Poll for video
      pollVideo(task_id);
      
    } catch (error) {
      console.error('Failed to generate video:', error);
      setLoading(false);
    }
  };
  
  const pollVideo = async (taskId) => {
    const checkStatus = async () => {
      const response = await fetch(
        `http://localhost:8000/api/dictionary/video/status/${taskId}`
      );
      const data = await response.json();
      
      if (data.status === 'completed') {
        setVideoUrl(data.video_url);
        setLoading(false);
      } else if (data.status === 'failed') {
        alert('Video generation failed');
        setLoading(false);
      } else {
        setTimeout(checkStatus, 5000);
      }
    };
    
    checkStatus();
  };
  
  return (
    <div>
      {/* Style selector */}
      <select value={videoStyle} onChange={(e) => setVideoStyle(e.target.value)}>
        <option value="kids_cartoon">Kids Cartoon</option>
        <option value="business_professional">Business Professional</option>
        <option value="realistic">Realistic</option>
        <option value="anime">Anime</option>
      </select>
      
      <button onClick={generateVideo} disabled={loading}>
        Generate Video
      </button>
      
      {/* NEW: Display conversation immediately */}
      {conversation && (
        <div className="conversation">
          <h3>Scenario</h3>
          <p>{conversation.scenario}</p>
          
          <h3>Dialogue</h3>
          {conversation.dialogue.map((line, i) => (
            <div key={i} className="dialogue-line">
              <strong>{line.character}:</strong> {line.text}
            </div>
          ))}
          
          <h3>Explanation</h3>
          <p>{conversation.phrase_explanation}</p>
        </div>
      )}
      
      {/* Video (shows after completion) */}
      {loading && <p>Generating video...</p>}
      {videoUrl && <video src={videoUrl} controls autoPlay />}
    </div>
  );
}
```

---

## Migration Checklist

### ✅ Backward Compatible
- Old requests without new parameters still work (uses defaults)
- Existing polling logic unchanged
- Response structure extended (not breaking)

### 🔄 Frontend Changes Needed

1. **Optional**: Add UI for video customization (style/duration/resolution/ratio dropdowns)
2. **Required**: Display `conversation_script` immediately after initial response
3. **Optional**: Show conversation before video completes (better UX - users see something immediately)
4. **Optional**: Update loading states (2 stages: "Generating conversation..." → "Creating video...")

### 🎯 Recommended UX Flow

```
User clicks "Generate Video"
  ↓
[2-5 seconds] Show spinner: "Generating conversation..."
  ↓
Display conversation script immediately ✨
  ↓
[30-60 seconds] Show spinner: "Creating animated video..."
  ↓
Display video player with conversation as subtitles
```

---

## Error Handling

```javascript
// Check for errors in initial response
if (!data.success) {
  console.error('Generation failed:', data.error);
  // Handle missing phrase parameter, API key issues, etc.
}

// Check for video generation failures during polling
if (data.status === 'failed') {
  console.error('Video failed:', data.error_message);
  // Still have conversation_script to display
}
```

---

## Key Takeaways

1. **New parameters are optional** - defaults work fine for initial integration
2. **Conversation script available immediately** - don't wait for video to show content
3. **Polling logic unchanged** - same status endpoint, same flow
4. **Better UX** - users see conversation in 2-5s instead of waiting 30-60s for video
5. **Backward compatible** - old frontend code still works, just missing new features
