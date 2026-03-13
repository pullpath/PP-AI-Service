# Frontend Integration: AI Video Generation

Quick guide for integrating async video generation into your frontend.

## Overview

Video generation takes **30-60 seconds**. Use async pattern with polling:
1. Start generation → get `task_id`
2. Poll status every 2 seconds
3. Show progress bar
4. Display video when complete

**Important**: Video generation is part of the dictionary API. All requests use the unified `/api/dictionary` endpoint.

---

## API Endpoints

### Start Generation

```http
POST /api/dictionary
Content-Type: application/json

{
  "word": "hello",
  "section": "ai_generated_phrase_video",
  "phrase": "pipe down"
}
```

**Response (200 OK)**:
```json
{
  "phrase": "pipe down",
  "ai_generated_phrase_video": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "poll_url": "/api/dictionary",
    "poll_params": {
      "section": "video_status",
      "task_id": "550e8400-e29b-41d4-a716-446655440000"
    },
    "message": "Video generation started. Poll using /api/dictionary with section=video_status and task_id parameter."
  },
  "data_source": "ai",
  "execution_time": 0.05,
  "success": true
}
```

### Check Status

```http
POST /api/dictionary
Content-Type: application/json

{
  "section": "video_status",
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response (processing)**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "phrase": "pipe down",
  "status": "processing",
  "progress": 30,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:30",
  "success": true
}
```

**Response (completed)**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "phrase": "pipe down",
  "status": "completed",
  "progress": 100,
  "video_url": "https://example.com/video.mp4",
  "style": "kids_cartoon",
  "duration": 5,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:01:00",
  "success": true
}
```

**Response (failed)**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "phrase": "pipe down",
  "status": "failed",
  "progress": 0,
  "error_message": "API timeout after 300 seconds",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:05:00",
  "success": false
}
```

---

## Implementation Examples

### React Hook

```typescript
import { useState, useEffect } from 'react';

interface VideoTask {
  task_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
}

export function useVideoGeneration() {
  const [task, setTask] = useState<VideoTask | null>(null);
  const [loading, setLoading] = useState(false);

  const generate = async (phrase: string) => {
    setLoading(true);
    const res = await fetch('/api/dictionary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        word: 'video',
        section: 'ai_generated_phrase_video',
        phrase 
      })
    });
    const data = await res.json();
    const taskInfo = {
      task_id: data.ai_generated_phrase_video.task_id,
      status: data.ai_generated_phrase_video.status,
      progress: 0
    };
    setTask(taskInfo);
    
    localStorage.setItem('video_task_id', taskInfo.task_id);
  };

  useEffect(() => {
    if (!task?.task_id || task.status === 'completed' || task.status === 'failed') {
      setLoading(false);
      return;
    }

    const interval = setInterval(async () => {
      const res = await fetch('/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: 'video',
          section: 'video_status',
          task_id: task.task_id
        })
      });
      const data = await res.json();
      setTask(data);

      if (data.status === 'completed' || data.status === 'failed') {
        setLoading(false);
        clearInterval(interval);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [task?.task_id, task?.status]);

  const resume = async () => {
    const taskId = localStorage.getItem('video_task_id');
    if (taskId) {
      const res = await fetch('/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: 'video',
          section: 'video_status',
          task_id: taskId
        })
      });
      const data = await res.json();
      setTask(data);
      if (data.status !== 'completed' && data.status !== 'failed') {
        setLoading(true);
      }
    }
  };

  return { task, loading, generate, resume };
}

// Component usage
function VideoGenerator({ phrase }: { phrase: string }) {
  const { task, loading, generate, resume } = useVideoGeneration();

  useEffect(() => {
    resume(); // Resume on mount
  }, []);

  return (
    <div>
      <button onClick={() => generate(phrase)} disabled={loading}>
        Generate Video
      </button>

      {loading && (
        <div>
          <progress value={task?.progress} max={100} />
          <p>Progress: {task?.progress}%</p>
        </div>
      )}

      {task?.status === 'completed' && (
        <video src={task.video_url} controls />
      )}

      {task?.status === 'failed' && (
        <p className="error">{task.error_message}</p>
      )}
    </div>
  );
}
```

### Vue Composable

```typescript
import { ref, watch, onMounted } from 'vue';

interface VideoTask {
  task_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
}

export function useVideoGeneration() {
  const task = ref<VideoTask | null>(null);
  const loading = ref(false);
  let pollInterval: number | null = null;

  const generate = async (phrase: string) => {
    loading.value = true;
    const res = await fetch('/api/dictionary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        word: 'video',
        section: 'ai_generated_phrase_video',
        phrase 
      })
    });
    const data = await res.json();
    const taskInfo = {
      task_id: data.ai_generated_phrase_video.task_id,
      status: data.ai_generated_phrase_video.status,
      progress: 0
    };
    task.value = taskInfo;
    localStorage.setItem('video_task_id', taskInfo.task_id);
  };

  const poll = async () => {
    if (!task.value?.task_id) return;

    const res = await fetch('/api/dictionary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        word: 'video',
        section: 'video_status',
        task_id: task.value.task_id
      })
    });
    const data = await res.json();
    task.value = data;

    if (data.status === 'completed' || data.status === 'failed') {
      loading.value = false;
      if (pollInterval) clearInterval(pollInterval);
    }
  };

  const resume = async () => {
    const taskId = localStorage.getItem('video_task_id');
    if (taskId) {
      const res = await fetch('/api/dictionary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          word: 'video',
          section: 'video_status',
          task_id: taskId
        })
      });
      const data = await res.json();
      task.value = data;
      if (data.status !== 'completed' && data.status !== 'failed') {
        loading.value = true;
      }
    }
  };

  watch(() => task.value?.task_id, (taskId) => {
    if (pollInterval) clearInterval(pollInterval);
    if (taskId && task.value?.status !== 'completed' && task.value?.status !== 'failed') {
      pollInterval = setInterval(poll, 2000);
    }
  });

  onMounted(resume);

  return { task, loading, generate, resume };
}
```

### Vanilla JavaScript

```javascript
class VideoGenerator {
  constructor() {
    this.taskId = null;
    this.pollInterval = null;
  }

  async generate(phrase) {
    const res = await fetch('/api/dictionary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        word: 'video',
        section: 'ai_generated_phrase_video',
        phrase 
      })
    });
    const data = await res.json();
    this.taskId = data.ai_generated_phrase_video.task_id;
    localStorage.setItem('video_task_id', this.taskId);
    this.startPolling();
    return data;
  }

  async checkStatus() {
    const res = await fetch('/api/dictionary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        word: 'video',
        section: 'video_status',
        task_id: this.taskId
      })
    });
    return await res.json();
  }

  startPolling() {
    this.pollInterval = setInterval(async () => {
      const data = await this.checkStatus();
      
      this.updateProgress(data.progress);

      if (data.status === 'completed') {
        this.stopPolling();
        this.displayVideo(data.video_url);
      } else if (data.status === 'failed') {
        this.stopPolling();
        this.displayError(data.error_message);
      }
    }, 2000);
  }

  stopPolling() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  resume() {
    const taskId = localStorage.getItem('video_task_id');
    if (taskId) {
      this.taskId = taskId;
      this.checkStatus().then(data => {
        if (data.status !== 'completed' && data.status !== 'failed') {
          this.startPolling();
        } else if (data.status === 'completed') {
          this.displayVideo(data.video_url);
        }
      });
    }
  }

  updateProgress(progress) {
    document.getElementById('progress-bar').value = progress;
    document.getElementById('progress-text').textContent = `${progress}%`;
  }

  displayVideo(url) {
    document.getElementById('video-player').src = url;
    document.getElementById('video-container').style.display = 'block';
  }

  displayError(message) {
    document.getElementById('error-message').textContent = message;
    document.getElementById('error-container').style.display = 'block';
  }
}

// Usage
const generator = new VideoGenerator();
generator.resume(); // Resume on page load

document.getElementById('generate-btn').addEventListener('click', () => {
  const phrase = document.getElementById('phrase-input').value;
  generator.generate(phrase);
});
```

---

## Key Points

### Polling Strategy
- **Interval**: 2 seconds (recommended)
- **Stop conditions**: `status === 'completed'` or `status === 'failed'`
- **Clean up**: Always clear interval when done

### Resume Capability
- Save `task_id` to `localStorage` on generation
- Check `localStorage` on page load
- Fetch status and resume polling if still in progress

### Progress Stages
- `0%` - Task created (pending)
- `10%` - Task started (processing)
- `30%` - Video generation in progress
- `100%` - Video ready (completed)

### Error Handling
- **Network errors**: Retry polling (don't clear interval)
- **Task failed**: Show `error_message` to user
- **Task not found**: Clear localStorage, show "Task expired" message

### Timeouts
- Backend timeout: 5 minutes (300 seconds)
- If no response after 5 minutes, task will fail with timeout error

---

## UI/UX Guidelines

### Loading State
```html
<div class="video-generator">
  <!-- Show during generation -->
  <div class="loading">
    <progress value="30" max="100"></progress>
    <p>Generating video... 30%</p>
    <p class="tip">This may take 30-60 seconds</p>
  </div>
</div>
```

### Completed State
```html
<div class="video-generator">
  <!-- Show when complete -->
  <video src="https://example.com/video.mp4" controls>
    Your browser does not support the video tag.
  </video>
  <button onclick="regenerate()">Generate Another</button>
</div>
```

### Error State
```html
<div class="video-generator">
  <!-- Show on failure -->
  <div class="error">
    <p>Video generation failed</p>
    <p class="error-message">API timeout after 300 seconds</p>
    <button onclick="retry()">Try Again</button>
  </div>
</div>
```

---

## Testing Checklist

- [ ] Start generation with phrase, verify task_id returned in nested structure
- [ ] Progress bar updates every 2 seconds via dictionary endpoint
- [ ] Video displays when complete
- [ ] Error message shows on failure
- [ ] Navigate away during generation
- [ ] Return and see progress resume
- [ ] Refresh page and progress resumes
- [ ] Multiple generations don't interfere
- [ ] Network errors don't break polling

---

## Common Issues

### Polling doesn't stop
- **Check**: Are you clearing the interval on completion?
- **Fix**: Always `clearInterval()` when status is `completed` or `failed`

### Lost progress after refresh
- **Check**: Are you saving task_id to localStorage?
- **Fix**: Save on generation, check on page load

### Multiple videos generating
- **Check**: Are you clearing old intervals?
- **Fix**: Clear previous interval before starting new one

### Progress stuck at 0%
- **Check**: Is the backend running?
- **Fix**: Check network tab for 500 errors, verify backend logs

### Wrong endpoint used
- **Check**: Are you using `/api/dictionary` for both generation and polling?
- **Fix**: All video operations use the dictionary endpoint with different sections

---

## Production Considerations

1. **Rate limiting**: Add debouncing to prevent spam clicks
2. **Cleanup**: Clear localStorage after task completes (optional)
3. **Analytics**: Track generation success/failure rates
4. **Caching**: Consider caching completed videos by phrase
5. **Retries**: Add retry logic for network failures (not task failures)

---

## Support

For backend details, see:
- `docs/ASYNC_VIDEO_GENERATION.md` - Technical implementation
- `docs/AI_VIDEO_GENERATION.md` - Video generation features
- `app.py` lines 166-182 - Dictionary endpoint video_status handling
- `ai_svc/dictionary/service.py` - DictionaryService.get_video_status() method
