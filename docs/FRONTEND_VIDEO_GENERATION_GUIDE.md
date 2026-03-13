# Frontend Integration Guide: AI-Generated Phrase Videos

## Overview

This guide covers the complete frontend integration for AI-generated educational phrase videos. The feature generates short animated videos (4-12 seconds) with audio to help users learn English phrases in context.

**Key Characteristics:**
- **Async generation**: 30-60 seconds processing time
- **Progress tracking**: Real-time status updates
- **Resume capability**: Users can navigate away and return
- **Persistent tasks**: Survives page refreshes

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [API Reference](#api-reference)
3. [React Integration](#react-integration)
4. [Vue Integration](#vue-integration)
5. [Vanilla JavaScript](#vanilla-javascript)
6. [UI/UX Patterns](#uiux-patterns)
7. [Error Handling](#error-handling)
8. [State Management](#state-management)
9. [Testing](#testing)

---

## Quick Start

### Basic Flow

```
┌──────────────────────────────────────────────────────────┐
│ 1. User Action: Click "Generate Video" for phrase       │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ 2. POST /api/video/generate                              │
│    Request: { phrase: "pipe down" }                      │
│    Response: { task_id: "abc-123", status: "pending" }  │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ 3. Start Polling: GET /api/video/status/:task_id        │
│    Every 2 seconds                                       │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ 4. Show Progress: 0% → 30% → 60% → 100%                 │
│    Display progress bar and status text                 │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ 5. Video Ready: status === "completed"                   │
│    Display video player with video_url                  │
└──────────────────────────────────────────────────────────┘
```

### 30-Second Implementation

```typescript
// Start generation
const startVideo = async (phrase: string) => {
  const res = await fetch('/api/video/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phrase })
  });
  const { task_id } = await res.json();
  return task_id;
};

// Poll for result
const pollVideo = async (task_id: string) => {
  const res = await fetch(`/api/video/status/${task_id}`);
  return await res.json();
};

// Usage
const task_id = await startVideo('pipe down');
const interval = setInterval(async () => {
  const data = await pollVideo(task_id);
  console.log(`Progress: ${data.progress}%`);
  
  if (data.status === 'completed') {
    clearInterval(interval);
    playVideo(data.video_url);
  }
}, 2000);
```

---

## API Reference

### 1. Start Video Generation

**Endpoint**: `POST /api/video/generate`

**Request Body**:
```typescript
interface VideoGenerationRequest {
  phrase: string;           // Required: The English phrase to demonstrate
  style?: string;           // Optional: "kids_cartoon" (default) | "business_professional" | "realistic" | "anime"
  duration?: number;        // Optional: 4-12 seconds (default: 4)
  resolution?: string;      // Optional: "480p" (default) | "720p" | "1080p"
  ratio?: string;          // Optional: "16:9" (default) | "9:16" | "1:1"
}
```

**Response** (202 Accepted):
```typescript
interface VideoGenerationResponse {
  task_id: string;          // Unique task identifier (UUID)
  status: "pending";        // Initial status
  message: string;          // "Video generation task created"
  poll_url: string;         // "/api/video/status/:task_id"
  success: true;
}
```

**Error Response** (400/500):
```typescript
interface ErrorResponse {
  error: string;            // Error message
  success: false;
}
```

**Example Request**:
```bash
curl -X POST http://localhost:8000/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "phrase": "break the ice",
    "style": "kids_cartoon",
    "duration": 5
  }'
```

---

### 2. Check Video Status

**Endpoint**: `GET /api/video/status/:task_id`

**Path Parameter**:
- `task_id` (string): Task identifier from generation response

**Response**:
```typescript
interface VideoStatusResponse {
  task_id: string;
  phrase: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;         // 0-100
  video_url?: string;       // Only present when status === "completed"
  error_message?: string;   // Only present when status === "failed"
  created_at: string;       // ISO 8601 timestamp
  updated_at: string;       // ISO 8601 timestamp
  success: true;
}
```

**Status Lifecycle**:
| Status | Progress | Description | Action |
|--------|----------|-------------|--------|
| `pending` | 0 | Task queued, not started | Keep polling |
| `processing` | 10-99 | Video generation in progress | Keep polling |
| `completed` | 100 | Video ready to display | Stop polling, show video |
| `failed` | 0 | Generation failed | Stop polling, show error |

**Example Request**:
```bash
curl http://localhost:8000/api/video/status/550e8400-e29b-41d4-a716-446655440000
```

---

## React Integration

### Complete Component Example

```typescript
import React, { useState, useEffect, useCallback } from 'react';

// Types
interface VideoTask {
  task_id: string;
  phrase: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

interface PhraseVideoGeneratorProps {
  phrase: string;           // The phrase to generate video for
  onComplete?: (videoUrl: string) => void;
  onError?: (error: string) => void;
}

const PhraseVideoGenerator: React.FC<PhraseVideoGeneratorProps> = ({
  phrase,
  onComplete,
  onError
}) => {
  const [task, setTask] = useState<VideoTask | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Start video generation
  const generateVideo = useCallback(async () => {
    try {
      setError(null);
      
      const response = await fetch('/api/video/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phrase })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      if (!data.success) {
        throw new Error(data.error || 'Failed to start video generation');
      }

      // Start polling immediately
      setIsPolling(true);
      pollStatus(data.task_id);
      
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      onError?.(errorMsg);
    }
  }, [phrase, onError]);

  // Poll for status
  const pollStatus = useCallback(async (task_id: string) => {
    try {
      const response = await fetch(`/api/video/status/${task_id}`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data: VideoTask = await response.json();
      setTask(data);

      // Handle completion
      if (data.status === 'completed') {
        setIsPolling(false);
        if (data.video_url) {
          onComplete?.(data.video_url);
        }
      }

      // Handle failure
      if (data.status === 'failed') {
        setIsPolling(false);
        const errorMsg = data.error_message || 'Video generation failed';
        setError(errorMsg);
        onError?.(errorMsg);
      }

    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      setIsPolling(false);
      onError?.(errorMsg);
    }
  }, [onComplete, onError]);

  // Polling effect
  useEffect(() => {
    if (!isPolling || !task?.task_id) return;

    const interval = setInterval(() => {
      pollStatus(task.task_id);
    }, 2000); // Poll every 2 seconds

    return () => clearInterval(interval);
  }, [isPolling, task?.task_id, pollStatus]);

  // Resume existing task on mount (from localStorage)
  useEffect(() => {
    const savedTaskId = localStorage.getItem(`video_task_${phrase}`);
    if (savedTaskId) {
      pollStatus(savedTaskId);
      setIsPolling(true);
    }
  }, [phrase, pollStatus]);

  // Save task_id to localStorage
  useEffect(() => {
    if (task?.task_id) {
      localStorage.setItem(`video_task_${phrase}`, task.task_id);
    }
  }, [task?.task_id, phrase]);

  // Clean up localStorage on completion
  useEffect(() => {
    if (task?.status === 'completed' || task?.status === 'failed') {
      localStorage.removeItem(`video_task_${phrase}`);
    }
  }, [task?.status, phrase]);

  return (
    <div className="phrase-video-generator">
      {/* Generation Button */}
      {!task && (
        <button 
          onClick={generateVideo}
          className="generate-btn"
          disabled={isPolling}
        >
          Generate Video for "{phrase}"
        </button>
      )}

      {/* Error Display */}
      {error && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          <p>{error}</p>
          <button onClick={generateVideo}>Retry</button>
        </div>
      )}

      {/* Progress Display */}
      {task && (task.status === 'pending' || task.status === 'processing') && (
        <div className="progress-container">
          <h3>Generating video for "{task.phrase}"</h3>
          
          <div className="progress-bar">
            <div 
              className="progress-fill"
              style={{ width: `${task.progress}%` }}
            />
          </div>
          
          <p className="progress-text">
            {task.status === 'pending' ? 'Starting...' : `${task.progress}%`}
          </p>
          
          <p className="status-hint">
            This may take 30-60 seconds. Feel free to navigate away.
          </p>
        </div>
      )}

      {/* Video Player */}
      {task?.status === 'completed' && task.video_url && (
        <div className="video-container">
          <h3>Video for "{task.phrase}"</h3>
          <video 
            src={task.video_url}
            controls
            className="phrase-video"
            autoPlay={false}
          >
            Your browser does not support video playback.
          </video>
          
          <button onClick={generateVideo} className="regenerate-btn">
            Generate New Video
          </button>
        </div>
      )}
    </div>
  );
};

export default PhraseVideoGenerator;
```

### React Hook (Reusable)

```typescript
// hooks/useVideoGeneration.ts
import { useState, useEffect, useCallback, useRef } from 'react';

interface UseVideoGenerationOptions {
  phrase: string;
  autoStart?: boolean;
  pollInterval?: number;  // milliseconds (default: 2000)
  persistToStorage?: boolean;
}

interface VideoGenerationState {
  task_id: string | null;
  status: 'idle' | 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url: string | null;
  error: string | null;
  isPolling: boolean;
}

export const useVideoGeneration = ({
  phrase,
  autoStart = false,
  pollInterval = 2000,
  persistToStorage = true
}: UseVideoGenerationOptions) => {
  const [state, setState] = useState<VideoGenerationState>({
    task_id: null,
    status: 'idle',
    progress: 0,
    video_url: null,
    error: null,
    isPolling: false
  });

  const pollIntervalRef = useRef<number | null>(null);

  // Start generation
  const generate = useCallback(async () => {
    setState(prev => ({ ...prev, error: null, status: 'pending' }));

    try {
      const response = await fetch('/api/video/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phrase })
      });

      const data = await response.json();

      if (!data.success) {
        throw new Error(data.error);
      }

      setState(prev => ({
        ...prev,
        task_id: data.task_id,
        isPolling: true
      }));

      if (persistToStorage) {
        localStorage.setItem(`video_task_${phrase}`, data.task_id);
      }

    } catch (err) {
      setState(prev => ({
        ...prev,
        status: 'failed',
        error: err instanceof Error ? err.message : 'Failed to start generation'
      }));
    }
  }, [phrase, persistToStorage]);

  // Poll status
  const poll = useCallback(async (task_id: string) => {
    try {
      const response = await fetch(`/api/video/status/${task_id}`);
      const data = await response.json();

      setState(prev => ({
        ...prev,
        status: data.status,
        progress: data.progress,
        video_url: data.video_url || null,
        error: data.error_message || null,
        isPolling: data.status === 'pending' || data.status === 'processing'
      }));

      if (data.status === 'completed' || data.status === 'failed') {
        if (persistToStorage) {
          localStorage.removeItem(`video_task_${phrase}`);
        }
      }

    } catch (err) {
      setState(prev => ({
        ...prev,
        status: 'failed',
        error: 'Failed to check video status',
        isPolling: false
      }));
    }
  }, [phrase, persistToStorage]);

  // Polling effect
  useEffect(() => {
    if (state.isPolling && state.task_id) {
      pollIntervalRef.current = window.setInterval(() => {
        poll(state.task_id!);
      }, pollInterval);
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [state.isPolling, state.task_id, poll, pollInterval]);

  // Auto-start on mount
  useEffect(() => {
    if (autoStart) {
      generate();
    }
  }, [autoStart, generate]);

  // Resume from storage
  useEffect(() => {
    if (persistToStorage) {
      const savedTaskId = localStorage.getItem(`video_task_${phrase}`);
      if (savedTaskId) {
        setState(prev => ({ ...prev, task_id: savedTaskId, isPolling: true }));
      }
    }
  }, [phrase, persistToStorage]);

  return {
    ...state,
    generate,
    reset: () => setState({
      task_id: null,
      status: 'idle',
      progress: 0,
      video_url: null,
      error: null,
      isPolling: false
    })
  };
};

// Usage
const MyComponent = () => {
  const { status, progress, video_url, error, generate } = useVideoGeneration({
    phrase: 'break the ice',
    autoStart: false,
    persistToStorage: true
  });

  return (
    <div>
      <button onClick={generate}>Generate</button>
      {status === 'processing' && <p>Progress: {progress}%</p>}
      {video_url && <video src={video_url} controls />}
      {error && <p>{error}</p>}
    </div>
  );
};
```

---

## Vue Integration

### Complete Component (Composition API)

```vue
<!-- PhraseVideoGenerator.vue -->
<template>
  <div class="phrase-video-generator">
    <!-- Generation Button -->
    <button 
      v-if="!task"
      @click="generateVideo"
      :disabled="isPolling"
      class="generate-btn"
    >
      Generate Video for "{{ phrase }}"
    </button>

    <!-- Error Display -->
    <div v-if="error" class="error-message">
      <span class="error-icon">⚠️</span>
      <p>{{ error }}</p>
      <button @click="generateVideo">Retry</button>
    </div>

    <!-- Progress Display -->
    <div 
      v-if="task && (task.status === 'pending' || task.status === 'processing')"
      class="progress-container"
    >
      <h3>Generating video for "{{ task.phrase }}"</h3>
      
      <div class="progress-bar">
        <div 
          class="progress-fill"
          :style="{ width: `${task.progress}%` }"
        />
      </div>
      
      <p class="progress-text">
        {{ task.status === 'pending' ? 'Starting...' : `${task.progress}%` }}
      </p>
      
      <p class="status-hint">
        This may take 30-60 seconds. Feel free to navigate away.
      </p>
    </div>

    <!-- Video Player -->
    <div 
      v-if="task?.status === 'completed' && task.video_url"
      class="video-container"
    >
      <h3>Video for "{{ task.phrase }}"</h3>
      <video 
        :src="task.video_url"
        controls
        class="phrase-video"
      >
        Your browser does not support video playback.
      </video>
      
      <button @click="generateVideo" class="regenerate-btn">
        Generate New Video
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue';

interface Props {
  phrase: string;
}

interface VideoTask {
  task_id: string;
  phrase: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  complete: [videoUrl: string];
  error: [error: string];
}>();

const task = ref<VideoTask | null>(null);
const isPolling = ref(false);
const error = ref<string | null>(null);
let pollInterval: number | null = null;

// Generate video
const generateVideo = async () => {
  error.value = null;
  
  try {
    const response = await fetch('/api/video/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phrase: props.phrase })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    
    if (!data.success) {
      throw new Error(data.error || 'Failed to start generation');
    }

    isPolling.value = true;
    await pollStatus(data.task_id);
    
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : 'Unknown error';
    error.value = errorMsg;
    emit('error', errorMsg);
  }
};

// Poll for status
const pollStatus = async (task_id: string) => {
  try {
    const response = await fetch(`/api/video/status/${task_id}`);
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data: VideoTask = await response.json();
    task.value = data;

    // Save to localStorage
    localStorage.setItem(`video_task_${props.phrase}`, task_id);

    // Handle completion
    if (data.status === 'completed') {
      isPolling.value = false;
      localStorage.removeItem(`video_task_${props.phrase}`);
      if (data.video_url) {
        emit('complete', data.video_url);
      }
    }

    // Handle failure
    if (data.status === 'failed') {
      isPolling.value = false;
      localStorage.removeItem(`video_task_${props.phrase}`);
      const errorMsg = data.error_message || 'Generation failed';
      error.value = errorMsg;
      emit('error', errorMsg);
    }

  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : 'Unknown error';
    error.value = errorMsg;
    isPolling.value = false;
    emit('error', errorMsg);
  }
};

// Watch polling state
watch(isPolling, (newValue) => {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }

  if (newValue && task.value?.task_id) {
    pollInterval = window.setInterval(() => {
      if (task.value?.task_id) {
        pollStatus(task.value.task_id);
      }
    }, 2000);
  }
});

// Resume on mount
onMounted(() => {
  const savedTaskId = localStorage.getItem(`video_task_${props.phrase}`);
  if (savedTaskId) {
    isPolling.value = true;
    pollStatus(savedTaskId);
  }
});

// Cleanup
onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval);
  }
});
</script>

<style scoped>
.phrase-video-generator {
  padding: 20px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
}

.generate-btn {
  padding: 12px 24px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
}

.generate-btn:hover {
  background: #0056b3;
}

.generate-btn:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.error-message {
  padding: 12px;
  background: #fee;
  border: 1px solid #fcc;
  border-radius: 4px;
  color: #c33;
}

.progress-container {
  text-align: center;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: #e0e0e0;
  border-radius: 4px;
  overflow: hidden;
  margin: 12px 0;
}

.progress-fill {
  height: 100%;
  background: #007bff;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 14px;
  color: #666;
  margin: 8px 0;
}

.status-hint {
  font-size: 12px;
  color: #999;
}

.video-container {
  text-align: center;
}

.phrase-video {
  width: 100%;
  max-width: 640px;
  border-radius: 8px;
  margin: 12px 0;
}

.regenerate-btn {
  padding: 8px 16px;
  background: #6c757d;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.regenerate-btn:hover {
  background: #5a6268;
}
</style>
```

### Vue Composable (Reusable)

```typescript
// composables/useVideoGeneration.ts
import { ref, watch, onUnmounted } from 'vue';

interface VideoTask {
  task_id: string;
  phrase: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  video_url?: string;
  error_message?: string;
}

export const useVideoGeneration = (phrase: string) => {
  const task = ref<VideoTask | null>(null);
  const isPolling = ref(false);
  const error = ref<string | null>(null);
  let pollInterval: number | null = null;

  const generate = async () => {
    error.value = null;
    
    try {
      const response = await fetch('/api/video/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phrase })
      });

      const data = await response.json();
      
      if (!data.success) throw new Error(data.error);

      isPolling.value = true;
      localStorage.setItem(`video_task_${phrase}`, data.task_id);
      await poll(data.task_id);
      
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed';
    }
  };

  const poll = async (task_id: string) => {
    try {
      const response = await fetch(`/api/video/status/${task_id}`);
      const data: VideoTask = await response.json();
      
      task.value = data;

      if (data.status === 'completed' || data.status === 'failed') {
        isPolling.value = false;
        localStorage.removeItem(`video_task_${phrase}`);
        
        if (data.status === 'failed') {
          error.value = data.error_message || 'Failed';
        }
      }

    } catch (err) {
      error.value = 'Polling failed';
      isPolling.value = false;
    }
  };

  watch(isPolling, (newValue) => {
    if (pollInterval) clearInterval(pollInterval);

    if (newValue && task.value?.task_id) {
      pollInterval = window.setInterval(() => {
        if (task.value?.task_id) poll(task.value.task_id);
      }, 2000);
    }
  });

  onUnmounted(() => {
    if (pollInterval) clearInterval(pollInterval);
  });

  return { task, isPolling, error, generate };
};

// Usage in component
import { useVideoGeneration } from '@/composables/useVideoGeneration';

const { task, isPolling, error, generate } = useVideoGeneration('break the ice');
```

---

## Vanilla JavaScript

### Complete Implementation

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Phrase Video Generator</title>
  <style>
    .video-generator {
      max-width: 600px;
      margin: 50px auto;
      padding: 20px;
      border: 1px solid #ddd;
      border-radius: 8px;
      font-family: Arial, sans-serif;
    }

    .generate-btn {
      padding: 12px 24px;
      background: #007bff;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 16px;
    }

    .generate-btn:hover {
      background: #0056b3;
    }

    .generate-btn:disabled {
      background: #ccc;
      cursor: not-allowed;
    }

    .progress-container {
      margin: 20px 0;
    }

    .progress-bar {
      width: 100%;
      height: 24px;
      background: #e0e0e0;
      border-radius: 4px;
      overflow: hidden;
      position: relative;
    }

    .progress-fill {
      height: 100%;
      background: #007bff;
      transition: width 0.3s ease;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-weight: bold;
    }

    .error {
      padding: 12px;
      background: #fee;
      border: 1px solid #fcc;
      border-radius: 4px;
      color: #c33;
      margin: 12px 0;
    }

    video {
      width: 100%;
      border-radius: 8px;
      margin: 12px 0;
    }

    .hidden {
      display: none;
    }
  </style>
</head>
<body>
  <div class="video-generator">
    <h2>AI Phrase Video Generator</h2>
    
    <div id="input-section">
      <input 
        type="text" 
        id="phrase-input" 
        placeholder="Enter phrase (e.g., 'break the ice')"
        style="width: 100%; padding: 12px; margin-bottom: 12px; border: 1px solid #ddd; border-radius: 4px;"
      />
      <button id="generate-btn" class="generate-btn">
        Generate Video
      </button>
    </div>

    <div id="error-section" class="error hidden">
      <span id="error-text"></span>
      <button onclick="retry()" style="margin-left: 12px;">Retry</button>
    </div>

    <div id="progress-section" class="progress-container hidden">
      <h3>Generating video for "<span id="current-phrase"></span>"</h3>
      <div class="progress-bar">
        <div id="progress-fill" class="progress-fill">0%</div>
      </div>
      <p id="status-text" style="text-align: center; color: #666; margin-top: 8px;"></p>
      <p style="text-align: center; color: #999; font-size: 12px;">
        This may take 30-60 seconds. Feel free to navigate away.
      </p>
    </div>

    <div id="video-section" class="hidden">
      <h3>Video for "<span id="video-phrase"></span>"</h3>
      <video id="video-player" controls></video>
      <button onclick="generateNewVideo()" class="generate-btn">
        Generate New Video
      </button>
    </div>
  </div>

  <script>
    let currentTaskId = null;
    let currentPhrase = null;
    let pollInterval = null;

    // Initialize
    document.getElementById('generate-btn').addEventListener('click', startGeneration);
    
    // Check for existing task on load
    window.addEventListener('load', resumeExistingTask);

    async function startGeneration() {
      const phraseInput = document.getElementById('phrase-input');
      const phrase = phraseInput.value.trim();

      if (!phrase) {
        showError('Please enter a phrase');
        return;
      }

      currentPhrase = phrase;
      hideAllSections();
      showProgressSection();

      try {
        const response = await fetch('/api/video/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phrase })
        });

        const data = await response.json();

        if (!data.success) {
          throw new Error(data.error || 'Failed to start generation');
        }

        currentTaskId = data.task_id;
        localStorage.setItem('current_video_task', currentTaskId);
        localStorage.setItem('current_phrase', phrase);

        startPolling();

      } catch (error) {
        showError(error.message);
      }
    }

    async function pollStatus() {
      if (!currentTaskId) return;

      try {
        const response = await fetch(`/api/video/status/${currentTaskId}`);
        const data = await response.json();

        updateProgress(data);

        if (data.status === 'completed') {
          stopPolling();
          showVideo(data.video_url, data.phrase);
          clearStorage();
        } else if (data.status === 'failed') {
          stopPolling();
          showError(data.error_message || 'Video generation failed');
          clearStorage();
        }

      } catch (error) {
        stopPolling();
        showError('Failed to check video status');
      }
    }

    function startPolling() {
      if (pollInterval) clearInterval(pollInterval);
      
      // Poll immediately
      pollStatus();
      
      // Then poll every 2 seconds
      pollInterval = setInterval(pollStatus, 2000);
    }

    function stopPolling() {
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    }

    function updateProgress(data) {
      const progressFill = document.getElementById('progress-fill');
      const statusText = document.getElementById('status-text');
      const phraseSpan = document.getElementById('current-phrase');

      phraseSpan.textContent = data.phrase;
      progressFill.style.width = `${data.progress}%`;
      progressFill.textContent = `${data.progress}%`;

      if (data.status === 'pending') {
        statusText.textContent = 'Starting...';
      } else if (data.status === 'processing') {
        statusText.textContent = 'Generating video...';
      }
    }

    function showVideo(videoUrl, phrase) {
      hideAllSections();
      
      const videoSection = document.getElementById('video-section');
      const videoPlayer = document.getElementById('video-player');
      const videoPhrase = document.getElementById('video-phrase');

      videoPlayer.src = videoUrl;
      videoPhrase.textContent = phrase;
      videoSection.classList.remove('hidden');
    }

    function showError(message) {
      hideAllSections();
      
      const errorSection = document.getElementById('error-section');
      const errorText = document.getElementById('error-text');

      errorText.textContent = message;
      errorSection.classList.remove('hidden');
      
      document.getElementById('input-section').classList.remove('hidden');
    }

    function showProgressSection() {
      document.getElementById('progress-section').classList.remove('hidden');
    }

    function hideAllSections() {
      document.getElementById('error-section').classList.add('hidden');
      document.getElementById('progress-section').classList.add('hidden');
      document.getElementById('video-section').classList.add('hidden');
    }

    function retry() {
      startGeneration();
    }

    function generateNewVideo() {
      hideAllSections();
      document.getElementById('input-section').classList.remove('hidden');
      document.getElementById('phrase-input').value = '';
      currentTaskId = null;
      currentPhrase = null;
    }

    function resumeExistingTask() {
      const savedTaskId = localStorage.getItem('current_video_task');
      const savedPhrase = localStorage.getItem('current_phrase');

      if (savedTaskId && savedPhrase) {
        currentTaskId = savedTaskId;
        currentPhrase = savedPhrase;
        
        hideAllSections();
        showProgressSection();
        startPolling();
      }
    }

    function clearStorage() {
      localStorage.removeItem('current_video_task');
      localStorage.removeItem('current_phrase');
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
      stopPolling();
    });
  </script>
</body>
</html>
```

---

## UI/UX Patterns

### 1. Progress Indicators

#### Linear Progress Bar
```html
<div class="progress-bar">
  <div class="progress-fill" style="width: 45%">45%</div>
</div>

<style>
.progress-bar {
  width: 100%;
  height: 24px;
  background: #e0e0e0;
  border-radius: 12px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #007bff, #0056b3);
  transition: width 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: bold;
}
</style>
```

#### Circular Progress (CSS)
```html
<div class="circular-progress" data-progress="65">
  <svg viewBox="0 0 100 100">
    <circle cx="50" cy="50" r="45" />
    <circle cx="50" cy="50" r="45" stroke-dasharray="282.7" stroke-dashoffset="98.5" />
  </svg>
  <span class="progress-text">65%</span>
</div>

<style>
.circular-progress {
  position: relative;
  width: 120px;
  height: 120px;
}

.circular-progress svg {
  transform: rotate(-90deg);
}

.circular-progress circle:first-child {
  fill: none;
  stroke: #e0e0e0;
  stroke-width: 8;
}

.circular-progress circle:last-child {
  fill: none;
  stroke: #007bff;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.3s ease;
}

.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 20px;
  font-weight: bold;
}
</style>
```

#### Animated Spinner
```html
<div class="spinner-container">
  <div class="spinner"></div>
  <p>Generating video...</p>
</div>

<style>
@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e0e0e0;
  border-top-color: #007bff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 12px;
}
</style>
```

### 2. Status Messages

```typescript
const getStatusMessage = (status: string, progress: number): string => {
  switch (status) {
    case 'pending':
      return '🎬 Starting video generation...';
    case 'processing':
      if (progress < 30) return '🎨 Creating scene...';
      if (progress < 60) return '🎭 Adding characters...';
      if (progress < 90) return '🎵 Generating audio...';
      return '✨ Finalizing video...';
    case 'completed':
      return '✅ Video ready!';
    case 'failed':
      return '❌ Generation failed';
    default:
      return '';
  }
};
```

### 3. Optimistic UI Updates

```typescript
// Show immediate feedback before API response
const handleGenerate = async () => {
  // Optimistic update
  setStatus('pending');
  setProgress(5);
  
  try {
    const result = await generateVideo(phrase);
    // Continue with actual task
  } catch (error) {
    // Rollback optimistic state
    setStatus('idle');
    setProgress(0);
    showError(error);
  }
};
```

### 4. Skeleton Loading

```html
<div class="video-skeleton">
  <div class="skeleton-header"></div>
  <div class="skeleton-video"></div>
  <div class="skeleton-text"></div>
</div>

<style>
@keyframes shimmer {
  0% { background-position: -1000px 0; }
  100% { background-position: 1000px 0; }
}

.skeleton-header,
.skeleton-video,
.skeleton-text {
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 1000px 100%;
  animation: shimmer 2s infinite;
  border-radius: 4px;
  margin-bottom: 12px;
}

.skeleton-header { height: 24px; width: 60%; }
.skeleton-video { height: 300px; }
.skeleton-text { height: 16px; width: 80%; }
</style>
```

---

## Error Handling

### Error Types and Recovery

```typescript
interface VideoError {
  type: 'network' | 'api' | 'timeout' | 'unknown';
  message: string;
  retryable: boolean;
}

const handleVideoError = (error: any): VideoError => {
  // Network errors
  if (error instanceof TypeError && error.message.includes('fetch')) {
    return {
      type: 'network',
      message: 'Network error. Please check your connection.',
      retryable: true
    };
  }

  // API errors
  if (error.response) {
    const status = error.response.status;
    
    if (status === 400) {
      return {
        type: 'api',
        message: 'Invalid request. Please try a different phrase.',
        retryable: false
      };
    }
    
    if (status === 500) {
      return {
        type: 'api',
        message: 'Server error. Please try again later.',
        retryable: true
      };
    }
    
    if (status === 429) {
      return {
        type: 'api',
        message: 'Too many requests. Please wait a moment.',
        retryable: true
      };
    }
  }

  // Timeout
  if (error.message?.includes('timeout')) {
    return {
      type: 'timeout',
      message: 'Generation timed out. Please try again.',
      retryable: true
    };
  }

  // Unknown
  return {
    type: 'unknown',
    message: 'An unexpected error occurred.',
    retryable: true
  };
};

// Usage
try {
  await generateVideo(phrase);
} catch (error) {
  const videoError = handleVideoError(error);
  
  setError(videoError.message);
  setRetryable(videoError.retryable);
  
  if (videoError.type === 'network') {
    // Show offline indicator
    showOfflineMessage();
  }
}
```

### Retry Logic

```typescript
const generateWithRetry = async (
  phrase: string,
  maxRetries = 3,
  backoffMs = 1000
): Promise<string> => {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetch('/api/video/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phrase })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      return data.task_id;

    } catch (error) {
      console.warn(`Attempt ${attempt}/${maxRetries} failed:`, error);

      if (attempt === maxRetries) {
        throw error;
      }

      // Exponential backoff
      await new Promise(resolve => 
        setTimeout(resolve, backoffMs * Math.pow(2, attempt - 1))
      );
    }
  }

  throw new Error('Max retries exceeded');
};
```

### Error UI Component

```typescript
interface ErrorDisplayProps {
  error: string;
  retryable: boolean;
  onRetry: () => void;
  onDismiss: () => void;
}

const ErrorDisplay: React.FC<ErrorDisplayProps> = ({
  error,
  retryable,
  onRetry,
  onDismiss
}) => {
  return (
    <div className="error-banner">
      <div className="error-content">
        <span className="error-icon">⚠️</span>
        <p className="error-message">{error}</p>
      </div>
      
      <div className="error-actions">
        {retryable && (
          <button onClick={onRetry} className="retry-btn">
            🔄 Retry
          </button>
        )}
        <button onClick={onDismiss} className="dismiss-btn">
          ✕
        </button>
      </div>
    </div>
  );
};
```

---

## State Management

### Redux Example

```typescript
// types.ts
export interface VideoState {
  taskId: string | null;
  phrase: string | null;
  status: 'idle' | 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  videoUrl: string | null;
  error: string | null;
  isPolling: boolean;
}

// actions.ts
export const videoActions = {
  generateStart: (phrase: string) => ({
    type: 'video/generateStart' as const,
    payload: { phrase }
  }),
  
  generateSuccess: (taskId: string) => ({
    type: 'video/generateSuccess' as const,
    payload: { taskId }
  }),
  
  updateStatus: (data: Partial<VideoState>) => ({
    type: 'video/updateStatus' as const,
    payload: data
  }),
  
  generateError: (error: string) => ({
    type: 'video/generateError' as const,
    payload: { error }
  }),
  
  reset: () => ({
    type: 'video/reset' as const
  })
};

// reducer.ts
const initialState: VideoState = {
  taskId: null,
  phrase: null,
  status: 'idle',
  progress: 0,
  videoUrl: null,
  error: null,
  isPolling: false
};

export const videoReducer = (
  state = initialState,
  action: ReturnType<typeof videoActions[keyof typeof videoActions]>
): VideoState => {
  switch (action.type) {
    case 'video/generateStart':
      return {
        ...state,
        phrase: action.payload.phrase,
        status: 'pending',
        error: null,
        progress: 0
      };
      
    case 'video/generateSuccess':
      return {
        ...state,
        taskId: action.payload.taskId,
        isPolling: true
      };
      
    case 'video/updateStatus':
      return {
        ...state,
        ...action.payload
      };
      
    case 'video/generateError':
      return {
        ...state,
        status: 'failed',
        error: action.payload.error,
        isPolling: false
      };
      
    case 'video/reset':
      return initialState;
      
    default:
      return state;
  }
};

// thunks.ts
export const generateVideo = (phrase: string) => async (dispatch: any) => {
  dispatch(videoActions.generateStart(phrase));
  
  try {
    const response = await fetch('/api/video/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phrase })
    });
    
    const data = await response.json();
    
    if (!data.success) {
      throw new Error(data.error);
    }
    
    dispatch(videoActions.generateSuccess(data.task_id));
    dispatch(startPolling(data.task_id));
    
  } catch (error) {
    dispatch(videoActions.generateError(error.message));
  }
};

export const startPolling = (taskId: string) => async (dispatch: any) => {
  const poll = async () => {
    try {
      const response = await fetch(`/api/video/status/${taskId}`);
      const data = await response.json();
      
      dispatch(videoActions.updateStatus({
        status: data.status,
        progress: data.progress,
        videoUrl: data.video_url || null,
        isPolling: data.status === 'pending' || data.status === 'processing'
      }));
      
      if (data.status === 'completed' || data.status === 'failed') {
        return; // Stop polling
      }
      
      // Continue polling
      setTimeout(poll, 2000);
      
    } catch (error) {
      dispatch(videoActions.generateError('Polling failed'));
    }
  };
  
  await poll();
};

// Component usage
import { useDispatch, useSelector } from 'react-redux';

const VideoGenerator = () => {
  const dispatch = useDispatch();
  const video = useSelector((state: RootState) => state.video);
  
  const handleGenerate = () => {
    dispatch(generateVideo('break the ice'));
  };
  
  return (
    <div>
      <button onClick={handleGenerate}>Generate</button>
      {video.status === 'processing' && <p>Progress: {video.progress}%</p>}
      {video.videoUrl && <video src={video.videoUrl} controls />}
    </div>
  );
};
```

### Zustand Example (Simpler)

```typescript
import create from 'zustand';

interface VideoStore {
  taskId: string | null;
  phrase: string | null;
  status: 'idle' | 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  videoUrl: string | null;
  error: string | null;
  
  generate: (phrase: string) => Promise<void>;
  reset: () => void;
}

export const useVideoStore = create<VideoStore>((set, get) => ({
  taskId: null,
  phrase: null,
  status: 'idle',
  progress: 0,
  videoUrl: null,
  error: null,
  
  generate: async (phrase) => {
    set({ phrase, status: 'pending', error: null });
    
    try {
      const response = await fetch('/api/video/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phrase })
      });
      
      const data = await response.json();
      
      if (!data.success) {
        throw new Error(data.error);
      }
      
      set({ taskId: data.task_id });
      
      // Start polling
      const poll = async () => {
        const res = await fetch(`/api/video/status/${data.task_id}`);
        const status = await res.json();
        
        set({
          status: status.status,
          progress: status.progress,
          videoUrl: status.video_url || null
        });
        
        if (status.status === 'pending' || status.status === 'processing') {
          setTimeout(poll, 2000);
        }
      };
      
      await poll();
      
    } catch (error) {
      set({ status: 'failed', error: error.message });
    }
  },
  
  reset: () => set({
    taskId: null,
    phrase: null,
    status: 'idle',
    progress: 0,
    videoUrl: null,
    error: null
  })
}));

// Component usage
const VideoGenerator = () => {
  const { status, progress, videoUrl, generate } = useVideoStore();
  
  return (
    <div>
      <button onClick={() => generate('break the ice')}>Generate</button>
      {status === 'processing' && <p>Progress: {progress}%</p>}
      {videoUrl && <video src={videoUrl} controls />}
    </div>
  );
};
```

---

## Testing

### Unit Tests (Jest + React Testing Library)

```typescript
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { rest } from 'msw';
import { setupServer } from 'msw/node';
import PhraseVideoGenerator from './PhraseVideoGenerator';

// Mock server
const server = setupServer(
  rest.post('/api/video/generate', (req, res, ctx) => {
    return res(ctx.json({
      task_id: 'test-task-123',
      status: 'pending',
      success: true
    }));
  }),
  
  rest.get('/api/video/status/:taskId', (req, res, ctx) => {
    const { taskId } = req.params;
    
    return res(ctx.json({
      task_id: taskId,
      phrase: 'test phrase',
      status: 'completed',
      progress: 100,
      video_url: 'https://example.com/video.mp4',
      success: true
    }));
  })
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('PhraseVideoGenerator', () => {
  test('generates video successfully', async () => {
    render(<PhraseVideoGenerator phrase="test phrase" />);
    
    // Click generate button
    const generateBtn = screen.getByText(/Generate Video/i);
    userEvent.click(generateBtn);
    
    // Wait for progress indicator
    await waitFor(() => {
      expect(screen.getByText(/Generating video/i)).toBeInTheDocument();
    });
    
    // Wait for video to appear
    await waitFor(() => {
      const video = screen.getByRole('video');
      expect(video).toHaveAttribute('src', 'https://example.com/video.mp4');
    }, { timeout: 5000 });
  });
  
  test('handles generation errors', async () => {
    server.use(
      rest.post('/api/video/generate', (req, res, ctx) => {
        return res(ctx.status(500), ctx.json({
          error: 'Server error',
          success: false
        }));
      })
    );
    
    render(<PhraseVideoGenerator phrase="test phrase" />);
    
    const generateBtn = screen.getByText(/Generate Video/i);
    userEvent.click(generateBtn);
    
    await waitFor(() => {
      expect(screen.getByText(/Server error/i)).toBeInTheDocument();
    });
  });
  
  test('polls for status updates', async () => {
    let pollCount = 0;
    
    server.use(
      rest.get('/api/video/status/:taskId', (req, res, ctx) => {
        pollCount++;
        
        if (pollCount < 3) {
          return res(ctx.json({
            task_id: 'test-task-123',
            phrase: 'test phrase',
            status: 'processing',
            progress: pollCount * 30,
            success: true
          }));
        }
        
        return res(ctx.json({
          task_id: 'test-task-123',
          phrase: 'test phrase',
          status: 'completed',
          progress: 100,
          video_url: 'https://example.com/video.mp4',
          success: true
        }));
      })
    );
    
    render(<PhraseVideoGenerator phrase="test phrase" />);
    
    userEvent.click(screen.getByText(/Generate Video/i));
    
    // Should poll multiple times
    await waitFor(() => {
      expect(pollCount).toBeGreaterThanOrEqual(3);
    }, { timeout: 10000 });
  });
});
```

### E2E Tests (Cypress)

```typescript
describe('Video Generation Flow', () => {
  beforeEach(() => {
    cy.visit('/');
  });
  
  it('generates video successfully', () => {
    // Intercept API calls
    cy.intercept('POST', '/api/video/generate', {
      statusCode: 202,
      body: {
        task_id: 'test-task-123',
        status: 'pending',
        success: true
      }
    }).as('generateVideo');
    
    cy.intercept('GET', '/api/video/status/*', (req) => {
      req.reply({
        statusCode: 200,
        body: {
          task_id: 'test-task-123',
          phrase: 'break the ice',
          status: 'completed',
          progress: 100,
          video_url: 'https://example.com/video.mp4',
          success: true
        }
      });
    }).as('checkStatus');
    
    // Type phrase
    cy.get('[data-testid="phrase-input"]').type('break the ice');
    
    // Click generate
    cy.get('[data-testid="generate-btn"]').click();
    
    // Verify API call
    cy.wait('@generateVideo');
    
    // Wait for polling
    cy.wait('@checkStatus');
    
    // Verify video appears
    cy.get('video').should('have.attr', 'src', 'https://example.com/video.mp4');
  });
  
  it('resumes task after page reload', () => {
    // Set localStorage
    cy.window().then((win) => {
      win.localStorage.setItem('video_task_break the ice', 'test-task-123');
    });
    
    // Intercept status check
    cy.intercept('GET', '/api/video/status/test-task-123', {
      statusCode: 200,
      body: {
        task_id: 'test-task-123',
        phrase: 'break the ice',
        status: 'processing',
        progress: 50,
        success: true
      }
    });
    
    // Reload page
    cy.reload();
    
    // Verify progress is shown
    cy.get('[data-testid="progress-bar"]').should('be.visible');
    cy.contains('50%').should('be.visible');
  });
});
```

---

## Best Practices Checklist

### Performance
- [ ] Poll every 2-3 seconds (not faster)
- [ ] Stop polling when task completes
- [ ] Clean up intervals on component unmount
- [ ] Use adaptive polling intervals based on progress
- [ ] Debounce generate button clicks

### UX
- [ ] Show immediate feedback on button click
- [ ] Display progress percentage
- [ ] Add helpful status messages
- [ ] Allow navigation away during generation
- [ ] Resume tasks on page return
- [ ] Show estimated time remaining

### Error Handling
- [ ] Handle network errors gracefully
- [ ] Show user-friendly error messages
- [ ] Provide retry functionality
- [ ] Log errors for debugging
- [ ] Handle edge cases (timeout, server error, etc.)

### State Management
- [ ] Persist task_id to localStorage
- [ ] Clean up localStorage on completion
- [ ] Handle multiple concurrent generations
- [ ] Sync state across browser tabs

### Accessibility
- [ ] Add ARIA labels to progress indicators
- [ ] Support keyboard navigation
- [ ] Provide screen reader announcements
- [ ] Use semantic HTML elements
- [ ] Ensure sufficient color contrast

---

## Production Checklist

- [ ] Set up error tracking (Sentry, LogRocket)
- [ ] Add analytics events (generation start, complete, fail)
- [ ] Monitor average generation time
- [ ] Track user retry rates
- [ ] Set up alerting for high failure rates
- [ ] Implement rate limiting on frontend
- [ ] Add request timeout (5 minutes max)
- [ ] Cache completed videos (optional)
- [ ] Add video preview thumbnails
- [ ] Implement video download feature

---

## Troubleshooting

### Common Issues

**Issue**: Polling doesn't stop after completion
```typescript
// Solution: Add cleanup effect
useEffect(() => {
  return () => {
    if (pollInterval) clearInterval(pollInterval);
  };
}, [pollInterval]);
```

**Issue**: Task resumes on every page refresh
```typescript
// Solution: Clear localStorage on completion
if (status === 'completed' || status === 'failed') {
  localStorage.removeItem(`video_task_${phrase}`);
}
```

**Issue**: Memory leak from uncancelled requests
```typescript
// Solution: Use AbortController
const controller = new AbortController();

fetch('/api/video/status/' + taskId, {
  signal: controller.signal
});

// Cleanup
return () => controller.abort();
```

**Issue**: CORS errors in development
```typescript
// Solution: Add proxy in package.json (Create React App)
{
  "proxy": "http://localhost:8000"
}

// Or configure CORS in Flask (already done)
```

---

## Support

For issues or questions:
- Check API logs: `tail -f ~/ppaiservice.log`
- Verify task status: `sqlite3 data/video_tasks.db "SELECT * FROM video_tasks WHERE task_id='...'"`
- Test endpoints with curl (see examples above)

---

**Last Updated**: 2024
**Version**: 1.0.0
