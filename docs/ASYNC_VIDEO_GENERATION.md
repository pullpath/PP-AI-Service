# Async Video Generation - Implementation Guide

## Overview

The video generation feature now runs **asynchronously** with persistent task tracking, allowing users to:
- Start video generation without blocking the UI
- Monitor progress in real-time
- Navigate away and resume later
- Check status across sessions (survives server restarts)

## Architecture

### Components

```
┌─────────────────┐
│   Frontend      │
│  (React/Vue)    │
└────────┬────────┘
         │ 1. POST /api/video/generate
         │ 2. Poll GET /api/video/status/:task_id
         ▼
┌─────────────────┐
│  Flask API      │
│  (app.py)       │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│  VideoTaskService       │
│  (video_task_service.py)│
│  - SQLite DB            │
│  - Background threads   │
└────────┬────────────────┘
         │
         ▼
┌─────────────────┐
│  VideoService   │
│  (video.py)     │
│  - Volcengine   │
└─────────────────┘
```

### Database Schema

**File**: `data/video_tasks.db`

```sql
CREATE TABLE video_tasks (
    task_id TEXT PRIMARY KEY,
    phrase TEXT NOT NULL,
    style TEXT NOT NULL,
    duration INTEGER NOT NULL,
    resolution TEXT NOT NULL,
    ratio TEXT NOT NULL,
    status TEXT NOT NULL,           -- pending, processing, completed, failed
    video_url TEXT,
    error_message TEXT,
    progress INTEGER DEFAULT 0,     -- 0-100
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
)
```

## API Usage

### 1. Start Video Generation

**Endpoint**: `POST /api/video/generate`

**Request**:
```bash
curl -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "phrase": "pipe down",
    "style": "kids_cartoon",
    "duration": 4,
    "resolution": "480p",
    "ratio": "16:9"
  }'
```

**Response** (202 Accepted):
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Video generation task created",
  "poll_url": "/api/video/status/550e8400-e29b-41d4-a716-446655440000",
  "success": true
}
```

### 2. Poll for Progress

**Endpoint**: `GET /api/video/status/<task_id>`

**Request**:
```bash
curl http://localhost:8000/api/video/status/550e8400-e29b-41d4-a716-446655440000
```

**Response (Processing)**:
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

**Response (Completed)**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "phrase": "pipe down",
  "status": "completed",
  "progress": 100,
  "video_url": "https://example.com/video.mp4",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:01:00",
  "success": true
}
```

**Response (Failed)**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "phrase": "pipe down",
  "status": "failed",
  "progress": 0,
  "error_message": "API timeout",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:05:00",
  "success": true
}
```

### Task Status Values

| Status | Description | Progress | Next Step |
|--------|-------------|----------|-----------|
| `pending` | Task created, waiting to start | 0 | Keep polling |
| `processing` | Video generation in progress | 10-99 | Keep polling |
| `completed` | Video ready | 100 | Use `video_url` |
| `failed` | Generation failed | 0 | Show `error_message` |

## Frontend Integration

### React Example

```typescript
import { useState, useEffect } from 'react';

interface VideoTask {
  task_id: string;
  phrase: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
}

function VideoGenerator() {
  const [task, setTask] = useState<VideoTask | null>(null);
  const [polling, setPolling] = useState(false);

  // Start video generation
  const generateVideo = async (phrase: string) => {
    const response = await fetch('/api/video/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phrase })
    });
    
    const data = await response.json();
    setTask(data);
    setPolling(true);
  };

  // Poll for progress
  useEffect(() => {
    if (!polling || !task) return;
    
    const interval = setInterval(async () => {
      const response = await fetch(`/api/video/status/${task.task_id}`);
      const data = await response.json();
      
      setTask(data);
      
      // Stop polling when done
      if (data.status === 'completed' || data.status === 'failed') {
        setPolling(false);
        clearInterval(interval);
      }
    }, 2000); // Poll every 2 seconds
    
    return () => clearInterval(interval);
  }, [polling, task]);

  // Resume from saved task_id (e.g., user navigates back)
  const resumeTask = async (task_id: string) => {
    const response = await fetch(`/api/video/status/${task_id}`);
    const data = await response.json();
    
    setTask(data);
    
    if (data.status === 'pending' || data.status === 'processing') {
      setPolling(true);
    }
  };

  return (
    <div>
      {/* Generation button */}
      <button onClick={() => generateVideo('pipe down')}>
        Generate Video
      </button>

      {/* Progress display */}
      {task && (
        <div>
          <h3>{task.phrase}</h3>
          <p>Status: {task.status}</p>
          <progress value={task.progress} max={100} />
          
          {task.status === 'completed' && task.video_url && (
            <video src={task.video_url} controls />
          )}
          
          {task.status === 'failed' && (
            <p>Error: {task.error_message}</p>
          )}
        </div>
      )}
    </div>
  );
}
```

### Vue Example

```vue
<template>
  <div>
    <button @click="generateVideo('pipe down')">Generate Video</button>
    
    <div v-if="task">
      <h3>{{ task.phrase }}</h3>
      <p>Status: {{ task.status }}</p>
      <progress :value="task.progress" max="100"></progress>
      
      <video v-if="task.status === 'completed'" :src="task.video_url" controls></video>
      <p v-if="task.status === 'failed'">Error: {{ task.error_message }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

interface VideoTask {
  task_id: string;
  phrase: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
}

const task = ref<VideoTask | null>(null);
const polling = ref(false);
let pollInterval: number | null = null;

async function generateVideo(phrase: string) {
  const response = await fetch('/api/video/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phrase })
  });
  
  const data = await response.json();
  task.value = data;
  polling.value = true;
}

watch(polling, (isPolling) => {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
  
  if (isPolling && task.value) {
    pollInterval = window.setInterval(async () => {
      const response = await fetch(`/api/video/status/${task.value!.task_id}`);
      const data = await response.json();
      
      task.value = data;
      
      if (data.status === 'completed' || data.status === 'failed') {
        polling.value = false;
      }
    }, 2000);
  }
});
</script>
```

## Dictionary API Integration

The dictionary service now returns **task information** instead of video URL directly:

**Request**:
```bash
curl -X POST http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{
    "word": "quiet",
    "section": "ai_generated_phrase_video",
    "phrase": "pipe down"
  }'
```

**Response** (Immediate):
```json
{
  "phrase": "pipe down",
  "ai_generated_phrase_video": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "poll_url": "/api/video/status/550e8400-e29b-41d4-a716-446655440000",
    "message": "Video generation started. Use poll_url to check progress."
  },
  "data_source": "ai",
  "execution_time": 0.05,
  "success": true
}
```

**Frontend flow**:
1. Call dictionary API with `section=ai_generated_phrase_video`
2. Receive `task_id` and `poll_url`
3. Start polling `/api/video/status/<task_id>` every 2 seconds
4. Display progress bar
5. Show video when `status === 'completed'`

## Best Practices

### Polling Strategy

```typescript
// Adaptive polling interval
const getPollingInterval = (progress: number) => {
  if (progress < 20) return 1000;  // Fast polling at start (1s)
  if (progress < 80) return 2000;  // Normal polling (2s)
  return 3000;                     // Slower at end (3s)
};
```

### Error Handling

```typescript
const pollWithRetry = async (task_id: string, maxRetries = 3) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const response = await fetch(`/api/video/status/${task_id}`);
      return await response.json();
    } catch (error) {
      if (i === maxRetries - 1) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
};
```

### Local Storage Persistence

```typescript
// Save task_id to resume later
const saveTaskId = (task_id: string, phrase: string) => {
  const tasks = JSON.parse(localStorage.getItem('video_tasks') || '[]');
  tasks.push({ task_id, phrase, timestamp: Date.now() });
  localStorage.setItem('video_tasks', JSON.stringify(tasks));
};

// Resume on page load
const resumePendingTasks = async () => {
  const tasks = JSON.parse(localStorage.getItem('video_tasks') || '[]');
  
  for (const task of tasks) {
    const status = await fetch(`/api/video/status/${task.task_id}`);
    const data = await status.json();
    
    if (data.status === 'pending' || data.status === 'processing') {
      // Resume polling
      startPolling(data);
    }
  }
};
```

## Performance Considerations

### Polling Frequency
- **Recommended**: 2 seconds
- **Too fast**: < 1 second (unnecessary server load)
- **Too slow**: > 5 seconds (poor UX)

### Task Cleanup
Old tasks are automatically cleaned up after 7 days:

```python
# Run as cron job or scheduled task
video_task_service.cleanup_old_tasks(days=7)
```

### Database Size
- Average task record: ~200 bytes
- 1000 tasks ≈ 200KB
- Estimate: ~500KB per month with 2500 generations

## Monitoring

### Check Active Tasks

```python
import sqlite3

conn = sqlite3.connect('data/video_tasks.db')
cursor = conn.execute("""
    SELECT status, COUNT(*) 
    FROM video_tasks 
    GROUP BY status
""")

for row in cursor:
    print(f"{row[0]}: {row[1]}")
```

### Average Generation Time

```python
cursor = conn.execute("""
    SELECT AVG(
        JULIANDAY(completed_at) - JULIANDAY(created_at)
    ) * 86400 as avg_seconds
    FROM video_tasks
    WHERE status = 'completed'
""")

avg_time = cursor.fetchone()[0]
print(f"Average generation time: {avg_time:.1f} seconds")
```

## Troubleshooting

### Task Stuck in "processing"

```bash
# Check task status
sqlite3 data/video_tasks.db "SELECT * FROM video_tasks WHERE task_id='<task_id>'"

# Manually mark as failed
sqlite3 data/video_tasks.db "UPDATE video_tasks SET status='failed', error_message='Timeout' WHERE task_id='<task_id>'"
```

### Database Locked

If you see "database is locked" errors:
1. Ensure only one Flask process is running
2. Check for background workers holding connections
3. Restart Flask server

### Server Restart Behavior

- **Task state**: Preserved (SQLite persists data)
- **Background threads**: Stopped (won't auto-resume)
- **Frontend**: Continue polling (will detect status)

## Migration from Sync to Async

### Old Dictionary Response (Sync)
```json
{
  "ai_generated_phrase_video": {
    "task_id": "...",
    "video_url": "https://...",
    "status": "completed"
  }
}
```

### New Dictionary Response (Async)
```json
{
  "ai_generated_phrase_video": {
    "task_id": "...",
    "status": "pending",
    "poll_url": "/api/video/status/..."
  }
}
```

### Migration Checklist

- [ ] Update frontend to handle `status: 'pending'`
- [ ] Implement polling mechanism
- [ ] Add progress bar UI
- [ ] Test resume functionality
- [ ] Update error handling for async failures

## Testing

```bash
# Start generation
TASK_ID=$(curl -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{"phrase":"test phrase"}' | jq -r '.task_id')

# Poll status
while true; do
  STATUS=$(curl -s http://localhost:8000/api/video/status/$TASK_ID | jq -r '.status')
  echo "Status: $STATUS"
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  
  sleep 2
done

# Get final result
curl http://localhost:8000/api/video/status/$TASK_ID | jq
```

## Future Improvements

1. **WebSocket support** - Real-time push notifications instead of polling
2. **Task queuing** - Limit concurrent video generations
3. **Priority queue** - Premium users get faster processing
4. **Webhooks** - Notify external services on completion
5. **Task cancellation** - Allow users to cancel in-progress tasks
6. **Batch generation** - Generate multiple videos in one request
