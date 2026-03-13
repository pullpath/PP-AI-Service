"""
Video Generation Service using Volcengine Ark SDK (Doubao SeeDance)

Provides AI-powered text-to-video generation with parameterized prompts
for different learning contexts (kids, business, general education).
"""
from volcenginesdkarkruntime import Ark
from dotenv import load_dotenv
import os
import time
import logging
from typing import Dict, Any, Optional, Literal
from enum import Enum

load_dotenv()

logger = logging.getLogger(__name__)


class VideoStyle(str, Enum):
    """Available video styles for phrase learning"""
    KIDS_CARTOON = "kids_cartoon"
    BUSINESS_PROFESSIONAL = "business_professional"
    REALISTIC = "realistic"
    ANIME = "anime"


class VideoResolution(str, Enum):
    """Available video resolutions"""
    P480 = "480p"
    P720 = "720p"
    P1080 = "1080p"


class VideoRatio(str, Enum):
    """Available aspect ratios"""
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class VideoGenerationService:
    """Service for generating educational videos using Volcengine Ark API"""
    
    # API Configuration
    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    MODEL_ID = "doubao-seedance-1-5-pro-251215"
    
    # Polling Configuration
    POLL_INTERVAL_SECONDS = 1
    MAX_POLL_ATTEMPTS = 300  # 5 minutes max wait time
    
    # Style-specific prompt templates
    STYLE_TEMPLATES = {
        VideoStyle.KIDS_CARTOON: {
            "prefix": "Peppa Pig animation style, colorful and cheerful, simple 2D cartoon with bold outlines.",
            "scene_context": "A bright, friendly children's setting with simple backgrounds.",
            "character_style": "Cute cartoon characters with expressive faces and simple shapes.",
            "tone": "Educational, fun, and easy to understand for young learners."
        },
        VideoStyle.BUSINESS_PROFESSIONAL: {
            "prefix": "Professional business setting, modern corporate environment, clean and polished.",
            "scene_context": "Contemporary office space with natural lighting, minimalist design.",
            "character_style": "Professional adults in business attire, confident and articulate.",
            "tone": "Clear, professional, and suitable for workplace learning."
        },
        VideoStyle.REALISTIC: {
            "prefix": "Realistic style with natural lighting and authentic environments.",
            "scene_context": "Real-world everyday setting with natural atmosphere.",
            "character_style": "Realistic people in casual daily situations.",
            "tone": "Natural, conversational, and relatable for general learners."
        },
        VideoStyle.ANIME: {
            "prefix": "Japanese anime style, vibrant colors, expressive characters.",
            "scene_context": "Dynamic anime background with stylized environments.",
            "character_style": "Anime characters with characteristic large eyes and expressive features.",
            "tone": "Engaging, energetic, and visually appealing for anime enthusiasts."
        }
    }
    
    def __init__(self):
        """Initialize the video generation service"""
        # Get API key from environment
        self.api_key = os.getenv('ARK_API_KEY')
        
        if not self.api_key:
            raise ValueError("ARK_API_KEY environment variable is not set")
        
        # Initialize Ark client
        self.client = Ark(
            base_url=self.BASE_URL,
            api_key=self.api_key
        )
        
        logger.info("Video generation service initialized successfully")
    
    def _build_prompt(
        self,
        phrase: str,
        style: VideoStyle = VideoStyle.KIDS_CARTOON,
        duration: int = 4,
        resolution: VideoResolution = VideoResolution.P480,
        ratio: VideoRatio = VideoRatio.LANDSCAPE,
        context: Optional[str] = None
    ) -> str:
        """
        Build a prompt for video generation based on phrase and style
        
        Args:
            phrase: The English phrase to feature in the video
            style: Visual style of the video
            duration: Video duration in seconds (4-12)
            resolution: Video resolution
            ratio: Aspect ratio
            context: Optional additional context
            
        Returns:
            Complete prompt string for video generation
        """
        template = self.STYLE_TEMPLATES[style]
        
        # Build scene description based on phrase and style
        scene_parts = [
            template["prefix"],
            template["scene_context"],
            f"\n\nA short dialogue scene demonstrating the English phrase '{phrase}' in natural conversation.",
            f"Characters speak ONLY English, using the phrase '{phrase}' clearly and naturally within 2 short sentences of dialogue.",
            "STRICT LANGUAGE RULE: no Chinese characters, no Chinese words, no code-switching, no bilingual speech.",
            "The scene should help English learners understand the phrase's meaning and proper usage through visual context.",
            "Keep shots simple and static with minimal camera movement for faster generation.",
            "Use a single background and no scene cuts.",
            template["character_style"],
            f"\n\n{template['tone']}"
        ]
        
        # Add custom context if provided
        if context:
            scene_parts.append(f"\n\nAdditional context: {context}")
        
        # Build complete prompt with technical parameters
        prompt_parts = [
            " ".join(scene_parts),
            f"--ratio {ratio.value}",
            f"--resolution {resolution.value}",
            f"--duration {duration}",
            "--audio_language en",
            "--camerafixed true",
            "--watermark true"
        ]
        
        complete_prompt = " ".join(prompt_parts)
        
        logger.info(f"Built prompt for phrase '{phrase}' with style '{style.value}': {len(complete_prompt)} chars")
        return complete_prompt
    
    def _poll_task_status(
        self,
        task_id: str,
        timeout_seconds: int = 300
    ) -> Dict[str, Any]:
        """
        Poll video generation task status until completion or timeout
        
        Args:
            task_id: Task ID to poll
            timeout_seconds: Maximum wait time in seconds
            
        Returns:
            Final task result dictionary
            
        Raises:
            TimeoutError: If task doesn't complete within timeout
            RuntimeError: If task fails
        """
        max_attempts = timeout_seconds // self.POLL_INTERVAL_SECONDS
        
        for attempt in range(max_attempts):
            try:
                result = self.client.content_generation.tasks.get(task_id=task_id)
                status = result.status
                
                if status == "succeeded":
                    logger.info(f"Task {task_id} succeeded after {attempt + 1} attempts")
                    
                    video_url = None
                    if hasattr(result, 'content') and result.content:
                        if hasattr(result.content, 'video_url'):
                            video_url = result.content.video_url
                            logger.info(f"Extracted video_url from result.content.video_url: {video_url}")
                    
                    if not video_url:
                        logger.warning(f"Task {task_id} succeeded but no video_url found in response")
                        logger.debug(f"Response structure: {result.__dict__ if hasattr(result, '__dict__') else result}")
                    
                    return {
                        "status": "succeeded",
                        "task_id": task_id,
                        "video_url": video_url,
                        "result": result
                    }
                elif status == "failed":
                    error_msg = result.error if hasattr(result, 'error') else "Unknown error"
                    logger.error(f"Task {task_id} failed: {error_msg}")
                    raise RuntimeError(f"Video generation failed: {error_msg}")
                else:
                    # Task still in progress
                    if (attempt + 1) % 10 == 0:  # Log every 10 seconds
                        logger.info(f"Task {task_id} status: {status}, attempt {attempt + 1}/{max_attempts}")
                    time.sleep(self.POLL_INTERVAL_SECONDS)
                    
            except Exception as e:
                if "failed" in str(e).lower() or isinstance(e, RuntimeError):
                    raise
                logger.warning(f"Error polling task {task_id}: {str(e)}, retrying...")
                time.sleep(self.POLL_INTERVAL_SECONDS)
        
        raise TimeoutError(f"Task {task_id} did not complete within {timeout_seconds} seconds")
    
    def generate_phrase_video(
        self,
        phrase: str,
        style: str = "kids_cartoon",
        duration: int = 4,
        resolution: str = "480p",
        ratio: str = "16:9",
        context: Optional[str] = None,
        timeout_seconds: int = 300
    ) -> Dict[str, Any]:
        """
        Generate a video demonstrating an English phrase
        
        Args:
            phrase: The English phrase to feature (required)
            style: Video style ('kids_cartoon', 'business_professional', 'realistic', 'anime')
            duration: Video duration in seconds (4-12)
            resolution: Video resolution ('480p', '720p', '1080p')
            ratio: Aspect ratio ('16:9', '9:16', '1:1')
            context: Optional additional context about the scenario
            timeout_seconds: Maximum wait time for video generation
            
        Returns:
            Dictionary with:
                - success: bool
                - task_id: str
                - video_url: str (if successful)
                - status: str
                - message: str
                
        Raises:
            ValueError: If invalid parameters provided
            TimeoutError: If generation takes too long
            RuntimeError: If generation fails
        """
        # Validate inputs
        if not phrase or not phrase.strip():
            raise ValueError("Phrase cannot be empty")
        
        try:
            style_enum = VideoStyle(style)
        except ValueError:
            raise ValueError(f"Invalid style '{style}'. Valid options: {', '.join([s.value for s in VideoStyle])}")
        
        try:
            resolution_enum = VideoResolution(resolution)
        except ValueError:
            raise ValueError(f"Invalid resolution '{resolution}'. Valid options: {', '.join([r.value for r in VideoResolution])}")
        
        try:
            ratio_enum = VideoRatio(ratio)
        except ValueError:
            raise ValueError(f"Invalid ratio '{ratio}'. Valid options: {', '.join([r.value for r in VideoRatio])}")
        
        if not (4 <= duration <= 12):
            raise ValueError("Duration must be between 4 and 12 seconds")
        
        # Build prompt
        prompt = self._build_prompt(
            phrase=phrase.strip(),
            style=style_enum,
            duration=duration,
            resolution=resolution_enum,
            ratio=ratio_enum,
            context=context
        )
        
        logger.info(f"Starting video generation for phrase: '{phrase}'")
        
        # Create video generation task
        try:
            create_result = self.client.content_generation.tasks.create(
                model=self.MODEL_ID,
                content=[
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            )
            
            task_id = create_result.id
            logger.info(f"Video generation task created: {task_id}")
            
        except Exception as e:
            logger.error(f"Error creating video generation task: {str(e)}")
            raise RuntimeError(f"Failed to create video generation task: {str(e)}")
        
        # Poll for completion
        try:
            result = self._poll_task_status(task_id, timeout_seconds)
            
            return {
                "success": True,
                "task_id": task_id,
                "video_url": result.get("video_url"),
                "status": "completed",
                "message": f"Video generated successfully for phrase '{phrase}'",
                "phrase": phrase,
                "style": style,
                "duration": duration,
                "resolution": resolution,
                "ratio": ratio
            }
            
        except TimeoutError as e:
            logger.error(f"Video generation timeout: {str(e)}")
            return {
                "success": False,
                "task_id": task_id,
                "status": "timeout",
                "message": str(e),
                "phrase": phrase
            }
            
        except RuntimeError as e:
            logger.error(f"Video generation failed: {str(e)}")
            return {
                "success": False,
                "task_id": task_id,
                "status": "failed",
                "message": str(e),
                "phrase": phrase
            }


# Initialize service instance
video_service = VideoGenerationService()
