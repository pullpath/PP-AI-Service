# Frontend Integration Guide: AI-Generated Phrase Videos

Complete guide for displaying AI-generated videos for phrases, with automatic generation when not available.

---

## Overview

The AI phrase video feature allows users to:
1. **View existing videos** - Display cached AI-generated videos instantly
2. **Generate new videos** - Create videos for phrases that don't have them yet
3. **Resume polling** - Continue tracking video generation after page reload
4. **Handle multiple parameter variations** - Different styles/durations for same phrase

**Key Distinction:**
- **AI-generated videos**: Created by Volcengine AI (4-12 seconds, customizable style)
- **Bilibili videos**: User-uploaded educational content from Bilibili platform

---

## API Endpoints

### 1. List All AI Videos for a Phrase

**Endpoint:** `GET /api/ai_phrase_videos`

**Use Case:** Display all existing videos (completed + in-progress) when user opens phrase page

**Parameters:**
- `word` (required): The word being looked up
- `phrase` (required): The phrase to filter by
- `status` (optional): Filter by status (`completed`, `processing`, `pending`, `failed`)

**Example Request:**
```bash
curl "http://localhost:8000/api/ai_phrase_videos?word=pipe&phrase=pipe%20down"
```

**Example Response:**
```json
{
  "word": "pipe",
  "phrase": "pipe down",
  "videos": [
    {
      "task_id": "abc-123-def",
      "video_url": "https://example.com/video1.mp4",
      "status": "completed",
      "style": "kids_cartoon",
      "duration": 4,
      "resolution": "480p",
      "ratio": "16:9",
      "created_at": 1710345678,
      "completed_at": 1710345720,
      "last_accessed_at": 1710345800
    },
    {
      "task_id": "xyz-456-ghi",
      "video_url": null,
      "status": "processing",
      "style": "business_professional",
      "duration": 6,
      "resolution": "720p",
      "ratio": "16:9",
      "created_at": 1710345600,
      "completed_at": null,
      "last_accessed_at": 1710345650
    }
  ],
  "count": 2
}
```

### 2. Generate New AI Video

**Endpoint:** `POST /api/dictionary`

**Use Case:** Create a new video when no suitable video exists

**Request Body:**
```json
{
  "word": "pipe",
  "section": "ai_generated_phrase_video",
  "phrase": "pipe down"
}
```

**Response:**
```json
{
  "phrase": "pipe down",
  "ai_generated_phrase_video": {
    "task_id": "new-task-789",
    "status": "pending",
    "poll_url": "/api/dictionary",
    "poll_params": {
      "section": "video_status",
      "task_id": "new-task-789"
    },
    "message": "Video generation started..."
  },
  "success": true
}
```

### 3. Poll Video Generation Status

**Endpoint:** `POST /api/dictionary` with `section=video_status`

**Use Case:** Check if video generation is complete

**Request Body:**
```json
{
  "section": "video_status",
  "task_id": "new-task-789"
}
```

**Response (Processing):**
```json
{
  "task_id": "new-task-789",
  "status": "processing",
  "progress": 45,
  "phrase": "pipe down",
  "style": "kids_cartoon"
}
```

**Response (Completed):**
```json
{
  "task_id": "new-task-789",
  "status": "completed",
  "progress": 100,
  "video_url": "https://example.com/generated-video.mp4",
  "phrase": "pipe down",
  "style": "kids_cartoon"
}
```

---

## Frontend Implementation

### React/TypeScript Example

```typescript
import { useState, useEffect } from 'react';

interface AIVideo {
  task_id: string;
  video_url: string | null;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  style: string;
  duration: number;
  resolution: string;
  ratio: string;
  created_at: number;
  completed_at: number | null;
}

interface AIVideosResponse {
  word: string;
  phrase: string;
  videos: AIVideo[];
  count: number;
}

function AIPhrasedVideos({ word, phrase }: { word: string; phrase: string }) {
  const [videos, setVideos] = useState<AIVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  // Load existing videos on mount
  useEffect(() => {
    fetchExistingVideos();
  }, [word, phrase]);

  // Poll in-progress videos
  useEffect(() => {
    const processingVideos = videos.filter(v => 
      v.status === 'processing' || v.status === 'pending'
    );
    
    if (processingVideos.length > 0) {
      const interval = setInterval(() => {
        processingVideos.forEach(video => pollVideoStatus(video.task_id));
      }, 2000);
      
      return () => clearInterval(interval);
    }
  }, [videos]);

  const fetchExistingVideos = async () => {
    try {
      const response = await fetch(
        `/api/ai_phrase_videos?word=${encodeURIComponent(word)}&phrase=${encodeURIComponent(phrase)}`
      );
      const data: AIVideosResponse = await response.json();
      setVideos(data.videos);
    } catch (error) {
      console.error('Error fetching videos:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateNewVideo = async () => {
    setGenerating(true);
    
    try {
      const response = await fetch('/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word,
          section: 'ai_generated_phrase_video',
          phrase
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        // Add new pending video to list
        const newVideo: AIVideo = {
          task_id: data.ai_generated_phrase_video.task_id,
          video_url: null,
          status: 'pending',
          style: 'kids_cartoon',
          duration: 4,
          resolution: '480p',
          ratio: '16:9',
          created_at: Date.now() / 1000,
          completed_at: null
        };
        setVideos(prev => [newVideo, ...prev]);
      }
    } catch (error) {
      console.error('Error generating video:', error);
    } finally {
      setGenerating(false);
    }
  };

  const pollVideoStatus = async (taskId: string) => {
    try {
      const response = await fetch('/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: 'video',
          section: 'video_status',
          task_id: taskId
        })
      });
      
      const data = await response.json();
      
      // Update video status
      setVideos(prev => prev.map(v => 
        v.task_id === taskId 
          ? { ...v, status: data.status, video_url: data.video_url }
          : v
      ));
    } catch (error) {
      console.error('Error polling video status:', error);
    }
  };

  const hasCompletedVideo = videos.some(v => v.status === 'completed');

  return (
    <div className="ai-phrase-videos">
      <h3>AI-Generated Videos for "{phrase}"</h3>
      
      {loading ? (
        <p>Loading videos...</p>
      ) : (
        <>
          {/* Completed Videos */}
          <div className="completed-videos">
            {videos
              .filter(v => v.status === 'completed')
              .map(video => (
                <div key={video.task_id} className="video-card">
                  <video 
                    src={video.video_url!} 
                    controls 
                    className="video-player"
                  />
                  <div className="video-info">
                    <span>Style: {video.style}</span>
                    <span>Duration: {video.duration}s</span>
                  </div>
                </div>
              ))}
          </div>

          {/* Processing Videos */}
          {videos.filter(v => v.status === 'processing' || v.status === 'pending').length > 0 && (
            <div className="processing-videos">
              <h4>Generating...</h4>
              {videos
                .filter(v => v.status === 'processing' || v.status === 'pending')
                .map(video => (
                  <div key={video.task_id} className="video-card generating">
                    <div className="spinner" />
                    <p>Creating {video.style} video ({video.duration}s)...</p>
                  </div>
                ))}
            </div>
          )}

          {/* Generate Button */}
          {!hasCompletedVideo && videos.length === 0 && (
            <button 
              onClick={generateNewVideo}
              disabled={generating}
              className="generate-btn"
            >
              {generating ? 'Generating...' : 'Generate AI Video'}
            </button>
          )}
          
          {hasCompletedVideo && (
            <button 
              onClick={generateNewVideo}
              disabled={generating}
              className="generate-more-btn"
            >
              Generate Another Style
            </button>
          )}
        </>
      )}
    </div>
  );
}

export default AIPhrasedVideos;
```

---

## Vanilla JavaScript Example

```javascript
class AIVideosManager {
  constructor(word, phrase) {
    this.word = word;
    this.phrase = phrase;
    this.videos = [];
    this.pollingInterval = null;
  }

  async init() {
    await this.fetchExistingVideos();
    this.render();
    this.startPolling();
  }

  async fetchExistingVideos() {
    try {
      const response = await fetch(
        `/api/ai_phrase_videos?word=${encodeURIComponent(this.word)}&phrase=${encodeURIComponent(this.phrase)}`
      );
      const data = await response.json();
      this.videos = data.videos;
    } catch (error) {
      console.error('Error fetching videos:', error);
    }
  }

  async generateVideo() {
    try {
      const response = await fetch('/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: this.word,
          section: 'ai_generated_phrase_video',
          phrase: this.phrase
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        this.videos.unshift({
          task_id: data.ai_generated_phrase_video.task_id,
          video_url: null,
          status: 'pending',
          style: 'kids_cartoon',
          duration: 4,
          resolution: '480p',
          ratio: '16:9',
          created_at: Date.now() / 1000,
          completed_at: null
        });
        this.render();
      }
    } catch (error) {
      console.error('Error generating video:', error);
    }
  }

  async pollVideoStatus(taskId) {
    try {
      const response = await fetch('/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: 'video',
          section: 'video_status',
          task_id: taskId
        })
      });
      
      const data = await response.json();
      
      const video = this.videos.find(v => v.task_id === taskId);
      if (video) {
        video.status = data.status;
        video.video_url = data.video_url;
        this.render();
      }
    } catch (error) {
      console.error('Error polling status:', error);
    }
  }

  startPolling() {
    this.pollingInterval = setInterval(() => {
      const processingVideos = this.videos.filter(v => 
        v.status === 'processing' || v.status === 'pending'
      );
      
      processingVideos.forEach(video => this.pollVideoStatus(video.task_id));
      
      if (processingVideos.length === 0) {
        clearInterval(this.pollingInterval);
      }
    }, 2000);
  }

  render() {
    const container = document.getElementById('ai-videos-container');
    
    const completedVideos = this.videos.filter(v => v.status === 'completed');
    const processingVideos = this.videos.filter(v => 
      v.status === 'processing' || v.status === 'pending'
    );
    
    let html = `<h3>AI Videos for "${this.phrase}"</h3>`;
    
    // Completed videos
    if (completedVideos.length > 0) {
      html += '<div class="completed-videos">';
      completedVideos.forEach(video => {
        html += `
          <div class="video-card">
            <video src="${video.video_url}" controls></video>
            <p>${video.style} - ${video.duration}s</p>
          </div>
        `;
      });
      html += '</div>';
    }
    
    // Processing videos
    if (processingVideos.length > 0) {
      html += '<div class="processing-videos"><h4>Generating...</h4>';
      processingVideos.forEach(video => {
        html += `
          <div class="video-card generating">
            <div class="spinner"></div>
            <p>Creating ${video.style} video...</p>
          </div>
        `;
      });
      html += '</div>';
    }
    
    // Generate button
    if (completedVideos.length === 0 && processingVideos.length === 0) {
      html += '<button onclick="videosManager.generateVideo()">Generate AI Video</button>';
    }
    
    container.innerHTML = html;
  }
}

// Usage
const videosManager = new AIVideosManager('pipe', 'pipe down');
videosManager.init();
```

---

## Decision Flow

```
┌─────────────────────────────────────┐
│ User Opens Phrase Video Page        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Call: GET /api/ai_phrase_videos     │
│ (word, phrase)                      │
└──────────────┬──────────────────────┘
               │
               ▼
       ┌───────┴────────┐
       │ Videos Exist?  │
       └───────┬────────┘
         Yes   │   No
      ┌────────┴───────┐
      │                │
      ▼                ▼
┌──────────┐    ┌──────────────┐
│ Display  │    │ Show "Generate│
│ Videos   │    │ Video" Button│
└────┬─────┘    └──────┬────────┘
     │                  │
     ▼                  ▼
┌──────────┐    ┌──────────────┐
│ Any In-  │    │ User Clicks  │
│ Progress?│    │ Button       │
└────┬─────┘    └──────┬────────┘
 Yes │   No            │
     │                 │
     ▼                 ▼
┌──────────┐    ┌──────────────┐
│ Start    │    │ Call: POST   │
│ Polling  │    │ /dictionary  │
│ (2s)     │    │ (section=ai  │
└────┬─────┘    │ _phrase_vid) │
     │          └──────┬────────┘
     │                 │
     │                 ▼
     │          ┌──────────────┐
     │          │ Add to List  │
     │          │ (pending)    │
     │          └──────┬────────┘
     │                 │
     └─────────────────┘
                │
                ▼
        ┌──────────────┐
        │ Poll Status  │
        │ Every 2s     │
        └──────┬───────┘
               │
         ┌─────┴─────┐
         │ Complete? │
         └─────┬─────┘
          Yes  │  No
               │
               ▼
        ┌──────────────┐
        │ Show Video   │
        │ Player       │
        └──────────────┘
```

---

## Best Practices

### 1. **Always Check Existing Videos First**
```typescript
// ✅ Good: Check cache before generating
const videos = await fetchExistingVideos();
if (videos.length === 0) {
  generateNewVideo();
}

// ❌ Bad: Generate immediately without checking
generateNewVideo();
```

### 2. **Efficient Polling**
```typescript
// ✅ Good: Poll only in-progress videos
const processingVideos = videos.filter(v => 
  v.status === 'processing' || v.status === 'pending'
);

if (processingVideos.length > 0) {
  startPolling();
}

// ❌ Bad: Poll all videos constantly
setInterval(() => pollAllVideos(), 2000);
```

### 3. **Handle Failed Videos**
```typescript
// ✅ Good: Show error and retry option
if (video.status === 'failed') {
  return (
    <div className="video-error">
      <p>Video generation failed</p>
      <button onClick={() => retryGeneration(video)}>Retry</button>
    </div>
  );
}
```

### 4. **Cleanup on Unmount**
```typescript
// ✅ Good: Clear polling interval
useEffect(() => {
  const interval = setInterval(pollStatus, 2000);
  return () => clearInterval(interval);
}, []);
```

---

## Testing Scenarios

### Scenario 1: First Time User
1. User searches "pipe down"
2. No videos exist → Show "Generate Video" button
3. User clicks button → Video starts generating (status: pending)
4. Frontend polls every 2s
5. Video completes → Display player

### Scenario 2: Returning User
1. User searches "pipe down" (again)
2. Completed video exists → Display immediately
3. Show "Generate Another Style" button
4. User can create variations (business style, 6s duration, etc.)

### Scenario 3: User Exits During Generation
1. User starts video generation
2. User closes tab/refreshes page
3. On return: `GET /api/ai_phrase_videos` returns in-progress video
4. Frontend resumes polling with saved task_id

---

## Error Handling

```typescript
try {
  const response = await fetch('/api/ai_phrase_videos?...');
  
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  
  const data = await response.json();
  setVideos(data.videos);
  
} catch (error) {
  console.error('Error:', error);
  setError('Failed to load videos. Please try again.');
}
```

---

## Cache Behavior

### When Videos Are Cached

**Cached on Creation:**
- Task created → Immediately cached with `status='pending'`
- Database: `ai_phrase_video_cache` table
- Includes: word, phrase, style, duration, resolution, ratio, task_id

**Updated on Completion:**
- Video completes → Cache updated with `status='completed'` + `video_url`
- Video fails → Cache updated with `status='failed'`

### Cache Key (Unique Constraint)
```sql
UNIQUE(word, phrase, style, duration, resolution, ratio)
```

**Example:**
- ("pipe", "pipe down", "kids_cartoon", 4, "480p", "16:9") → Cached
- ("pipe", "pipe down", "business_professional", 6, "720p", "16:9") → Different cache entry

---

## Performance Tips

1. **Lazy Load Videos**: Only fetch when user scrolls to phrase section
2. **Cache Response**: Store video list in local state/Redux to avoid refetching
3. **Debounce Polling**: Don't poll if user navigates away
4. **Preload Thumbnails**: Generate video thumbnails for faster preview

---

## Complete Flow Diagram

```
User Opens Page → Fetch Videos → Display Results
                                        │
                        ┌───────────────┼───────────────┐
                        │               │               │
                  Completed          Processing        None
                  (Show Video)    (Show Spinner)  (Show Button)
                        │               │               │
                        │               └───► Poll ──►  │
                        │                  (2s)         │
                        └───────────────────┬───────────┘
                                           │
                                    User Clicks
                                    "Generate"
                                           │
                                           ▼
                                  POST /dictionary
                                  (create task)
                                           │
                                           ▼
                                  Cache + Start Poll
                                           │
                                           ▼
                                    Video Completes
                                           │
                                           ▼
                                  Update Cache + UI
```

---

## Summary

**Key Points:**
1. ✅ Always check existing videos first via `GET /api/ai_phrase_videos`
2. ✅ Generate new video only when needed via `POST /api/dictionary`
3. ✅ Poll in-progress videos every 2 seconds
4. ✅ Cache handles resume on page reload automatically
5. ✅ Each parameter combination (style, duration, etc.) creates unique video

**Backend Status:**
- ✅ List endpoint implemented: `GET /api/ai_phrase_videos` (app.py:277-310)
- ✅ Cache system integrated: Tracks video generation tasks
- ✅ Test script available: `test_list_videos_endpoint.py`

**Frontend Implementation Steps:**
1. Use the React/TypeScript or vanilla JS examples above
2. Implement the decision flow (check existing → generate if needed → poll)
3. Test with real video generation (requires ARK_API_KEY in `.env`)
4. Test with multiple phrases and parameter variations
5. Add error handling and retry logic

**Testing:**
```bash
# Start Flask server
python app.py

# Run backend tests
python test_list_videos_endpoint.py

# Test frontend integration manually
# (Open browser, trigger video generation, verify polling)
```

---

**End of Guide**
