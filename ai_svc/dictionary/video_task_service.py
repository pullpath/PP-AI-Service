"""
Video Task Service - Async video generation with persistent task tracking

Provides:
- Background video generation using threading
- SQLite-based task state persistence
- Task status polling for frontend progress updates
- Resume capability if user navigates away
"""
import sqlite3
import threading
import uuid
import time
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, Literal
from pathlib import Path

from .video import video_service
from .cache_service import cache_service

logger = logging.getLogger(__name__)

TaskStatus = Literal["pending", "processing", "completed", "failed"]


class VideoTaskService:
    """Service for managing asynchronous video generation tasks"""
    
    def __init__(self, db_path: str = "ai_svc/dictionary/video_tasks.db"):
        """Initialize the video task service
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_db()
        self._lock = threading.Lock()
        
        logger.info(f"VideoTaskService initialized with DB: {db_path}")
    
    def _init_db(self):
        """Initialize SQLite database with tasks table"""
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS video_tasks (
                    task_id TEXT PRIMARY KEY,
                    phrase TEXT NOT NULL,
                    style TEXT NOT NULL,
                    duration INTEGER NOT NULL,
                    resolution TEXT NOT NULL,
                    ratio TEXT NOT NULL,
                    status TEXT NOT NULL,
                    video_url TEXT,
                    error_message TEXT,
                    progress INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)
            conn.commit()
            
        logger.info("Video tasks database initialized")
    
    def create_task(
        self,
        phrase: str,
        style: str = "kids_cartoon",
        duration: int = 4,
        resolution: str = "480p",
        ratio: str = "16:9"
    ) -> str:
        """Create a new video generation task
        
        Args:
            phrase: The phrase to generate video for
            style: Video style
            duration: Video duration in seconds
            resolution: Video resolution
            ratio: Video aspect ratio
            
        Returns:
            task_id: Unique task identifier
        """
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO video_tasks 
                (task_id, phrase, style, duration, resolution, ratio, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_id, phrase, style, duration, resolution, ratio, "pending", now, now))
            conn.commit()
        
        logger.info(f"Created video task {task_id} for phrase '{phrase}'")
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a video task
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task status dictionary or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM video_tasks WHERE task_id = ?
            """, (task_id,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
    
    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        progress: Optional[int] = None,
        video_url: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """Update task status and metadata
        
        Args:
            task_id: Task identifier
            status: New status
            progress: Progress percentage (0-100)
            video_url: Video URL if completed
            error_message: Error message if failed
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            updates = ["status = ?", "updated_at = ?"]
            values: list[str | int] = [status, now]
            
            if progress is not None:
                updates.append("progress = ?")
                values.append(progress)
            
            if video_url is not None:
                updates.append("video_url = ?")
                values.append(video_url)
            
            if error_message is not None:
                updates.append("error_message = ?")
                values.append(error_message)
            
            if status == "completed" or status == "failed":
                updates.append("completed_at = ?")
                values.append(now)
            
            values.append(task_id)
            
            query = f"UPDATE video_tasks SET {', '.join(updates)} WHERE task_id = ?"
            conn.execute(query, values)
            conn.commit()
        
        logger.debug(f"Updated task {task_id}: status={status}, progress={progress}")
    
    def start_video_generation(self, task_id: str):
        """Start background video generation for a task
        
        Args:
            task_id: Task identifier
        """
        # Retrieve task details
        task = self.get_task_status(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return
        
        # Start background thread
        thread = threading.Thread(
            target=self._generate_video_background,
            args=(task_id, task),
            daemon=True
        )
        thread.start()
        
        logger.info(f"Started background video generation for task {task_id}")
    
    def _generate_video_background(self, task_id: str, task: Dict[str, Any]):
        """Background worker for video generation
        
        Args:
            task_id: Task identifier
            task: Task details dictionary
        """
        try:
            self.update_task_status(task_id, "processing", progress=10)
            
            logger.info(f"[Task {task_id}] Starting video generation for phrase '{task['phrase']}'")
            
            self.update_task_status(task_id, "processing", progress=30)
            
            result = video_service.generate_phrase_video(
                phrase=task['phrase'],
                style=task['style'],
                duration=task['duration'],
                resolution=task['resolution'],
                ratio=task['ratio'],
                timeout_seconds=300
            )
            
            if result.get("success"):
                video_url = result.get("video_url")
                self.update_task_status(
                    task_id,
                    "completed",
                    progress=100,
                    video_url=video_url
                )
                cache_service.update_ai_phrase_video_status(
                    task_id=task_id,
                    status="completed",
                    video_url=video_url
                )
                logger.info(f"[Task {task_id}] Video generation completed: {video_url}")
            else:
                error_msg = result.get("message", "Unknown error")
                self.update_task_status(
                    task_id,
                    "failed",
                    progress=0,
                    error_message=error_msg
                )
                cache_service.update_ai_phrase_video_status(
                    task_id=task_id,
                    status="failed",
                    video_url=None
                )
                logger.error(f"[Task {task_id}] Video generation failed: {error_msg}")
                
        except Exception as e:
            error_msg = str(e)
            self.update_task_status(
                task_id,
                "failed",
                progress=0,
                error_message=error_msg
            )
            cache_service.update_ai_phrase_video_status(
                task_id=task_id,
                status="failed",
                video_url=None
            )
            logger.exception(f"[Task {task_id}] Unexpected error during video generation")
    
    def cleanup_old_tasks(self, days: int = 7):
        """Clean up old completed/failed tasks
        
        Args:
            days: Remove tasks older than this many days
        """
        cutoff = datetime.utcnow().timestamp() - (days * 86400)
        cutoff_iso = datetime.utcfromtimestamp(cutoff).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM video_tasks 
                WHERE status IN ('completed', 'failed') 
                AND updated_at < ?
            """, (cutoff_iso,))
            deleted = cursor.rowcount
            conn.commit()
        
        logger.info(f"Cleaned up {deleted} old video tasks")
        return deleted


# Singleton instance
video_task_service = VideoTaskService()
