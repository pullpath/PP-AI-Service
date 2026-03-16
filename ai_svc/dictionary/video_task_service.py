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
from .tos_storage import download_and_upload_video

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
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS video_tasks (
                    task_id TEXT PRIMARY KEY,
                    word TEXT,
                    phrase TEXT NOT NULL,
                    conversation_script TEXT,
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
            
            try:
                conn.execute("SELECT conversation_script FROM video_tasks LIMIT 1")
            except sqlite3.OperationalError:
                logger.info("Migrating database: adding conversation_script column")
                conn.execute("ALTER TABLE video_tasks ADD COLUMN conversation_script TEXT")
            
            try:
                conn.execute("SELECT word FROM video_tasks LIMIT 1")
            except sqlite3.OperationalError:
                logger.info("Migrating database: adding word column")
                conn.execute("ALTER TABLE video_tasks ADD COLUMN word TEXT")
            
            try:
                conn.execute("SELECT bucket_name FROM video_tasks LIMIT 1")
            except sqlite3.OperationalError:
                logger.info("Migrating database: adding bucket_name column")
                conn.execute("ALTER TABLE video_tasks ADD COLUMN bucket_name TEXT")
            
            conn.commit()
            
        logger.info("Video tasks database initialized")
    
    def create_task(
        self,
        phrase: str,
        bucket_name: str,
        word: Optional[str] = None,
        conversation_script: Optional[Dict[str, Any]] = None,
        style: str = "kids_cartoon",
        duration: int = 4,
        resolution: str = "480p",
        ratio: str = "16:9"
    ) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        import json
        conversation_json = json.dumps(conversation_script) if conversation_script else None
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO video_tasks 
                (task_id, word, phrase, conversation_script, bucket_name, style, duration, resolution, ratio, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_id, word, phrase, conversation_json, bucket_name, style, duration, resolution, ratio, "pending", now, now))
            conn.commit()
        
        logger.info(f"Created video task {task_id} for word '{word}' / phrase '{phrase}' with bucket '{bucket_name}'")
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        import json
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM video_tasks WHERE task_id = ?
            """, (task_id,))
            row = cursor.fetchone()
            
            if row:
                task_dict = dict(row)
                if task_dict.get('conversation_script'):
                    try:
                        task_dict['conversation_script'] = json.loads(task_dict['conversation_script'])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse conversation_script JSON for task {task_id}")
                        task_dict['conversation_script'] = None
                return task_dict
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
            from typing import Union, List
            values: List[Union[str, int]] = [status, now]
            
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
        try:
            self.update_task_status(task_id, "processing", progress=10)
            
            logger.info(f"[Task {task_id}] Starting video generation for phrase '{task['phrase']}'")
            
            self.update_task_status(task_id, "processing", progress=30)
            
            result = video_service.generate_phrase_video(
                phrase=task['phrase'],
                conversation_script=task.get('conversation_script'),
                style=task['style'],
                duration=task['duration'],
                resolution=task['resolution'],
                ratio=task['ratio'],
                timeout_seconds=300
            )
            
            if result.get("success"):
                volcengine_video_url = result.get("video_url")
                
                if not volcengine_video_url or not isinstance(volcengine_video_url, str):
                    logger.error(f"[Task {task_id}] Video generation succeeded but no valid video URL returned")
                    self.update_task_status(
                        task_id,
                        "failed",
                        progress=0,
                        error_message="Video generation succeeded but no video URL returned"
                    )
                    cache_service.update_ai_phrase_video_status(
                        task_id=task_id,
                        status="failed",
                        video_url=None
                    )
                    return
                
                logger.info(f"[Task {task_id}] Video generated from Volcengine: {volcengine_video_url}")
                
                self.update_task_status(task_id, "processing", progress=70)
                
                word = task.get('word', 'unknown')
                phrase = task['phrase']
                bucket_name = task.get('bucket_name')
                style = task.get('style', 'kids_cartoon')
                
                if not bucket_name:
                    error_msg = "bucket_name not found in task data"
                    logger.error(f"[Task {task_id}] {error_msg}")
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
                    return
                
                tos_video_url = download_and_upload_video(
                    video_url=volcengine_video_url,
                    word=word,
                    phrase=phrase,
                    bucket_name=bucket_name,
                    style=style
                )
                
                if tos_video_url:
                    final_video_url = tos_video_url
                    logger.info(f"[Task {task_id}] Video uploaded to TOS storage: {tos_video_url}")
                else:
                    final_video_url = volcengine_video_url
                    logger.warning(f"[Task {task_id}] TOS upload failed, using Volcengine URL (will expire in 24h)")
                
                self.update_task_status(
                    task_id,
                    "completed",
                    progress=100,
                    video_url=final_video_url
                )
                cache_service.update_ai_phrase_video_status(
                    task_id=task_id,
                    status="completed",
                    video_url=final_video_url
                )
                logger.info(f"[Task {task_id}] Video generation completed: {final_video_url}")
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
