"""
Bilibili Video Search Module

Decoupled Bilibili video search functionality for the dictionary service.
Implements enhanced search with KNOWLEDGE zones and optimized search queries.
"""

from typing import Dict, Any, List, Optional
import os
import time
import logging
import re
import requests
from bilibili_api import search, sync, video, Credential, video_zone

from .schemas import BilibiliVideoInfo

logger = logging.getLogger(__name__)


class BilibiliVideoSearch:
    """Bilibili video search service with enhanced KNOWLEDGE zone filtering"""
    
    # Bilibili search configuration
    PAGE_SIZE = 50
    MAX_VIDEOS_TO_CHECK_FOR_SUBTITLES = 50
    MAX_SEARCH_RETRIES = 3
    
    # KNOWLEDGE zone types for educational content
    KNOWLEDGE_ZONES = [
        video_zone.VideoZoneTypes.KNOWLEDGE,  # 知识区
        # video_zone.VideoZoneTypes.KNOWLEDGE_SCIENCE,  # 科学科普
        # video_zone.VideoZoneTypes.KNOWLEDGE_SOCIAL_SCIENCE,  # 社科·法律·心理
        # video_zone.VideoZoneTypes.KNOWLEDGE_HUMANITY_HISTORY,  # 人文历史
        # video_zone.VideoZoneTypes.KNOWLEDGE_BUSINESS,  # 财经商业
        video_zone.VideoZoneTypes.KNOWLEDGE_CAMPUS,  # 校园学习
        video_zone.VideoZoneTypes.KNOWLEDGE_CAREER,  # 职业职场
        video_zone.VideoZoneTypes.KNOWLEDGE_SKILL,  # 野生技术协会
    ]
    
    # Enhanced search tags for better video discovery
    ENHANCED_SEARCH_TAGS = [
        "英语",  # English
        # "学习",  # Learning
        # "教学",  # Teaching
        # "教程",  # Tutorial
        # "解释",  # Explanation
        # "词汇",  # Vocabulary
        # "语法",  # Grammar
        # "发音",  # Pronunciation
        # "口语",  # Speaking
        # "听力",  # Listening
    ]
    
    def __init__(self, credential: Optional[Credential] = None):
        """Initialize Bilibili video search service
        
        Args:
            credential: Optional Bilibili credentials for subtitle access
        """
        self.credential = credential
        if credential:
            logger.info("Bilibili credentials configured for subtitle access")
        else:
            logger.warning("Bilibili credentials not configured - subtitle access will be limited")
    
    def search_videos_for_word(self, word: str, phrases: List[str]) -> Dict[str, Any]:
        """Search Bilibili videos for a word using its common phrases
        
        Args:
            word: The word to search for
            phrases: List of common phrases for the word
            
        Returns:
            Dictionary with success status and video list
        """
        try:
            logger.info(f"[{word}] Starting Bilibili video search with phrases: {phrases}")
            
            all_videos = []
            
            for phrase in phrases:
                video_info = self._search_videos_for_phrase(word, phrase)
                if video_info:
                    all_videos.append(video_info)
            
            if not all_videos:
                logger.info(f"[{word}] No videos found for any phrases. Falling back to search with original word")
                video_info = self._search_videos_for_phrase(word, word, is_fallback=True)
                if video_info:
                    all_videos.append(video_info)
            
            return {
                "success": True,
                "bilibili_videos": all_videos
            }
            
        except Exception as e:
            logger.error(f"Error fetching Bilibili videos for '{word}': {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _search_videos_for_phrase(self, word: str, phrase: str, is_fallback: bool = False) -> Optional[Dict[str, Any]]:
        """Search Bilibili videos for a specific phrase
        
        Args:
            word: The original word being looked up
            phrase: The phrase to search for (could be the word itself in fallback)
            is_fallback: Whether this is a fallback search
            
        Returns:
            Video info dictionary if found, None otherwise
        """
        log_prefix = f"[{word}] Fallback -" if is_fallback else f"[{word}]"
        
        try:
            logger.info(f"{log_prefix} Searching Bilibili for phrase: '{phrase}'")
            
            search_queries = self._generate_enhanced_search_queries(phrase)
            
            best_video = None
            best_subtitle_occurrences = []
            best_score = 0
            
            for search_query in search_queries:
                logger.info(f"{log_prefix} Trying search query: '{search_query}'")
                
                for attempt in range(1, self.MAX_SEARCH_RETRIES + 1):
                    video_results = self._search_in_knowledge_zones(search_query)
                    
                    if not video_results:
                        logger.info(f"{log_prefix} No videos returned from Bilibili for query '{search_query}' (attempt {attempt}/{self.MAX_SEARCH_RETRIES}) — retrying")
                        continue
                    
                    logger.info(f"{log_prefix} Found {len(video_results)} videos in KNOWLEDGE zones for query '{search_query}' (attempt {attempt})")
                    
                    filtered_by_phrase = self._filter_videos_by_phrase(video_results, phrase)
                    logger.info(f"{log_prefix} After phrase filtering: {len(filtered_by_phrase)} videos contain whole phrase '{phrase}'")
                    
                    if not filtered_by_phrase:
                        logger.info(f"{log_prefix} No videos found containing whole phrase '{phrase}' - retrying (attempt {attempt}/{self.MAX_SEARCH_RETRIES})")
                        continue
                    
                    filtered_videos = [{'video': video, 'quality_score': 1.0} for video in filtered_by_phrase]
                    
                    logger.info(f"{log_prefix} After phrase filtering: {len(filtered_videos)} videos for query '{search_query}'")
                    
                    filtered_videos.sort(key=lambda x: x['quality_score'], reverse=True)
                    
                    video_found = self._find_best_video_with_subtitles(
                        filtered_videos, phrase, word
                    )
                    
                    if video_found:
                        best_video = video_found['video']
                        best_subtitle_occurrences = video_found['subtitle_occurrences']
                        best_score = video_found['score']
                        break
                
                if best_video:
                    break
            
            if best_video:
                video_info = self._create_video_info(
                    best_video, phrase, best_subtitle_occurrences, best_score, word
                )
                if video_info:
                    logger.info(f"{log_prefix} Added Bilibili video for phrase '{phrase}': {best_video.get('bvid')} (score: {best_score})")
                    return video_info
            else:
                logger.info(f"{log_prefix} No suitable video found for phrase '{phrase}'")
            
            return None
            
        except Exception as e:
            logger.warning(f"{log_prefix} Error searching Bilibili for phrase '{phrase}': {str(e)}")
            return None
    
    def _generate_enhanced_search_queries(self, phrase: str) -> List[str]:
        """Generate enhanced search queries for better video discovery
        
        Args:
            phrase: The original search phrase
            
        Returns:
            List of enhanced search queries to try
        """
        # Normalize the phrase (trim + lowercase)
        normalized_phrase = phrase.strip().lower()
        
        queries = []
        
        # 1. Phrase + enhanced tags
        for tag in self.ENHANCED_SEARCH_TAGS:
            queries.append(f"{normalized_phrase} {tag}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_queries = []
        for query in queries:
            if query not in seen:
                seen.add(query)
                unique_queries.append(query)
        
        logger.info(f"Generated enhanced search queries: {unique_queries}")
        return unique_queries
    
    def _search_in_knowledge_zones(self, query: str) -> List[Dict[str, Any]]:
        """Search for videos in KNOWLEDGE zones with multiple order types
        
        Args:
            query: Search query string
            
        Returns:
            List of video search results from all zones and order types
        """
        all_videos = []
        
        # Multiple order types for better coverage
        order_types = [
            search.OrderVideo.STOW,       # Favorites (收藏数)
            # search.OrderVideo.CLICK,      # View count (播放数)
            # search.OrderVideo.TOTALRANK   # Total ranking (综合排序)
        ]
        
        # Try each KNOWLEDGE zone with each order type
        for zone_type in self.KNOWLEDGE_ZONES:
            for order_type in order_types:
                try:
                    search_result = sync(search.search_by_type(
                        keyword=query,
                        search_type=search.SearchObjectType.VIDEO,
                        order_type=order_type,
                        video_zone_type=zone_type,
                        page=1,
                        page_size=self.PAGE_SIZE
                    ))
                    
                    videos = search_result.get('result', [])
                    if videos:
                        logger.info(f"Found {len(videos)} videos in zone {zone_type} with order {order_type} for query '{query}'")
                        all_videos.extend(videos)
                        
                except Exception as e:
                    logger.warning(f"Error searching in zone {zone_type} with order {order_type} for query '{query}': {str(e)}")
                    continue
        
        # Remove duplicates based on bvid
        seen_bvids = set()
        unique_videos = []
        for video in all_videos:
            bvid = video.get('bvid')
            if bvid and bvid not in seen_bvids:
                seen_bvids.add(bvid)
                unique_videos.append(video)
        
        logger.info(f"Total unique videos found for query '{query}': {len(unique_videos)}")
        return unique_videos
    
    def _filter_videos_by_phrase(self, videos: List[Dict[str, Any]], phrase: str) -> List[Dict[str, Any]]:
        """Filter videos to only include those containing the whole phrase in title, description, or tags
        
        Args:
            videos: List of video search results
            phrase: The phrase to match (whole word/phrase)
            
        Returns:
            List of videos that contain the whole phrase
        """
        filtered_videos = []
        phrase_lower = phrase.lower().strip()
        
        # Create pattern for whole phrase match (word boundaries)
        pattern = r'\b' + re.escape(phrase_lower) + r'\b'
        
        for video in videos:
            # Get text fields to search (strip all HTML tags)
            title = self._strip_html_tags(video.get('title', '')).lower()
            description = self._strip_html_tags(video.get('description', '')).lower()
            tags = video.get('tag', '').lower()
            
            # Combine all text for searching
            combined_text = f"{title} {description} {tags}"
            
            # Check if whole phrase matches
            if re.search(pattern, combined_text):
                filtered_videos.append(video)
        
        return filtered_videos

    
    def _filter_and_score_videos(self, videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter videos based on quality criteria and calculate quality scores
        
        Args:
            videos: List of video search results
            
        Returns:
            List of filtered videos with quality scores
        """
        filtered_videos = []
        
        for video in videos:
            # Parse duration
            duration = self._parse_duration(video.get('duration', '0'))
            
            # Apply basic filters
            if not (45 <= duration <= 1800):  # 45 seconds to 30 minutes
                continue
            
            if video.get('play', 0) < 100:  # Minimum views
                continue
            
            if video.get('favorites', 0) < 10:  # Minimum favorites
                continue
            
            # Calculate quality score
            quality_score = self._calculate_quality_score(video)
            if quality_score < 0.01:
                continue
            
            filtered_videos.append({
                'video': video,
                'quality_score': quality_score
            })
        
        return filtered_videos
    
    def _find_best_video_with_subtitles(self, filtered_videos: List[Dict[str, Any]], 
                                      phrase: str, word: str) -> Optional[Dict[str, Any]]:
        """Find the best video with subtitle matches
        
        Args:
            filtered_videos: List of filtered videos with quality scores
            phrase: Search phrase to match in subtitles
            word: Original word for logging
            
        Returns:
            Dictionary with video, subtitle occurrences, and score, or None
        """
        # Check top videos for subtitle matches
        for item in filtered_videos[:self.MAX_VIDEOS_TO_CHECK_FOR_SUBTITLES]:
            video = item['video']
            bvid = video.get('bvid', '')
            
            # Check for subtitle matches
            subtitle_occurrences = self._get_bilibili_subtitles(bvid, phrase)
            
            if subtitle_occurrences:
                logger.info(f"[{word}] Video {bvid} has {len(subtitle_occurrences)} subtitle matches for '{phrase}'")
                return {
                    'video': video,
                    'subtitle_occurrences': subtitle_occurrences,
                    'score': item['quality_score']
                }
            else:
                logger.info(f"[{word}] Video {bvid} has no subtitle matches for '{phrase}' - will use anyway")
                # If no subtitle matches found, still use the video but with start_time=0
                return {
                    'video': video,
                    'subtitle_occurrences': [],
                    'score': item['quality_score']
                }
        
        return None
    
    def _create_video_info(self, video: Dict[str, Any], phrase: str, 
                          subtitle_occurrences: List[Dict[str, Any]], 
                          score: float, word: str) -> Optional[Dict[str, Any]]:
        """Create BilibiliVideoInfo from video data
        
        Args:
            video: Video data from search results
            phrase: Matched phrase
            subtitle_occurrences: List of subtitle matches
            score: Quality score
            word: Original word for logging
            
        Returns:
            BilibiliVideoInfo as dictionary, or None on error
        """
        try:
            # Extract video information
            bvid = video.get('bvid', '')
            aid = video.get('aid', 0)
            title = self._strip_html_tags(video.get('title', ''))
            description = self._strip_html_tags(video.get('description', ''))[:200]
            pic = video.get('pic', '')
            author = video.get('author', '')
            mid = video.get('mid', 0)
            view = video.get('play', 0)
            danmaku = video.get('video_review', 0)
            reply = video.get('review', 0)
            favorite = video.get('favorites', 0)
            coin = video.get('coin', 0)
            share = video.get('share', 0)
            like = video.get('like', 0)
            pubdate = video.get('pubdate', 0)
            duration_str = video.get('duration', '0')
            
            # Convert duration string to seconds
            try:
                if ':' in duration_str:
                    parts = duration_str.split(':')
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    else:
                        duration = 0
                else:
                    duration = int(duration_str)
            except (ValueError, IndexError):
                duration = 0
            
            # Determine start time from subtitle matches (earliest occurrence)
            start_time = 0.0
            if subtitle_occurrences:
                start_time = min(occ['start'] for occ in subtitle_occurrences)
                logger.info(f"[{word}] Using start time {start_time}s for video {bvid} (phrase '{phrase}')")
            
            # Create video URL with optional start time
            video_url = f"https://www.bilibili.com/video/{bvid}"
            if start_time > 0:
                video_url += f"?t={start_time}"
            
            video_info = BilibiliVideoInfo(
                bvid=bvid,
                aid=aid,
                title=title,
                description=description,
                pic=pic,
                author=author,
                mid=mid,
                view=view,
                danmaku=danmaku,
                reply=reply,
                favorite=favorite,
                coin=coin,
                share=share,
                like=like,
                pubdate=pubdate,
                duration=duration,
                start_time=start_time,
                matched_phrase=phrase,
                video_url=video_url
            )
            
            return video_info.model_dump()
            
        except Exception as e:
            logger.warning(f"[{word}] Error processing video: {str(e)}")
            return None
    
    def _get_bilibili_subtitles(self, bvid: str, phrase: str) -> List[Dict[str, Any]]:
        """Get subtitle timestamps where the exact phrase appears in the Bilibili video
        
        Args:
            bvid: Bilibili video ID
            phrase: Phrase to search for in subtitles
            
        Returns:
            List of subtitle occurrences with timestamps
        """
        try:
            logger.info(f"[Subtitle] Starting subtitle fetch for {bvid}, looking for phrase: '{phrase}'")
            
            # Initialize video object with credentials if available
            if self.credential:
                video_obj = video.Video(bvid=bvid, credential=self.credential)
                logger.info(f"[Subtitle] Using authenticated session for video {bvid}")
            else:
                video_obj = video.Video(bvid=bvid)
                logger.warning(f"[Subtitle] No credentials available for video {bvid} - subtitles may not be accessible")
            
            # Get video info to find CID
            info = sync(video_obj.get_info())
            cid = info.get('cid', 0)
            
            if not cid:
                logger.warning(f"[Subtitle] Could not get CID for video {bvid}")
                return []
            
            logger.info(f"[Subtitle] Got CID {cid} for video {bvid}, fetching subtitle info...")
            
            # Get subtitle information
            subtitle_info = sync(video_obj.get_subtitle(cid=cid))
            
            if not subtitle_info or 'subtitles' not in subtitle_info:
                logger.warning(f"[Subtitle] No subtitles available for video {bvid} (subtitle_info: {subtitle_info})")
                return []
            
            logger.info(f"[Subtitle] Found {len(subtitle_info.get('subtitles', []))} subtitle tracks for video {bvid}")
            
            subtitle_url = None
            found_lang = None
            for sub in subtitle_info['subtitles']:
                lang = sub.get('lan', '')
                ai_status = sub.get('ai_status', 0)
                logger.info(f"[Subtitle] Available subtitle language: {lang}, ai_status: {ai_status}")
                if ai_status != 2:
                    continue  # Only use completed AI subtitles
                if lang.startswith('en') or 'en' in lang:
                    subtitle_url = sub.get('subtitle_url')
                    found_lang = lang
                    break
                elif ('zh' in lang or lang == 'ai-zh') and not subtitle_url:
                    subtitle_url = sub.get('subtitle_url')
                    found_lang = lang
            
            if not subtitle_url:
                logger.warning(f"[Subtitle] No suitable subtitle language found for video {bvid}")
                return []
            
            logger.info(f"[Subtitle] Using subtitle language '{found_lang}' for video {bvid}, URL: {subtitle_url}")
            
            # Handle protocol-relative URLs
            if subtitle_url.startswith('//'):
                subtitle_url = 'https:' + subtitle_url
            
            # Download subtitle content
            response = requests.get(subtitle_url, timeout=10)
            if response.status_code != 200:
                logger.warning(f"[Subtitle] Failed to download subtitles for video {bvid}: {response.status_code}")
                return []
            
            subtitle_data = response.json()
            logger.info(f"[Subtitle] Downloaded subtitle data for {bvid}, entries: {len(subtitle_data.get('body', []))}")
            
            # Look for exact phrase matches in subtitle content
            phrase_lower = phrase.lower()
            occurrences = []
            max_occurrences = 3
            
            if 'body' in subtitle_data:
                for item in subtitle_data['body']:
                    content = item.get('content', '')
                    if phrase_lower in content.lower():
                        logger.info(f"[Subtitle] Found phrase '{phrase}' in subtitle text: '{content}'")
                        
                        # Check if it's an exact phrase match (not just substring)
                        pattern = r'\b' + re.escape(phrase_lower) + r'\b'
                        if re.search(pattern, content.lower()):
                            start = item.get('from', 0)
                            duration = item.get('to', 0) - start
                            end = item.get('to', start + duration)
                            
                            occurrences.append({
                                'start': start,
                                'end': end,
                                'text': content.strip(),
                                'phrase': phrase
                            })
                            logger.info(f"[Subtitle] Matched at {start}s: '{content}'")
                            
                            if len(occurrences) >= max_occurrences:
                                break
            
            logger.info(f"[Subtitle] Total matches found for {bvid}: {len(occurrences)}")
            return occurrences
            
        except Exception as e:
            logger.warning(f"Could not fetch subtitles for video {bvid}: {str(e)}")
            return []

    def _strip_html_tags(self, text: str) -> str:
        """Strip all HTML tags from text
        
        Args:
            text: Text that may contain HTML tags
            
        Returns:
            Text with all HTML tags removed
        """
        import re
        # Remove all HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        return clean
    
    def _parse_duration(self, duration_str: str) -> int:
        """Convert duration string to seconds
        
        Args:
            duration_str: Duration string (e.g., "5:30" or "1:23:45")
            
        Returns:
            Duration in seconds, or 0 on error
        """
        try:
            parts = duration_str.split(':')
            if len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:  # HH:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except:
            return 0
        return 0
    
    def _calculate_quality_score(self, video: dict) -> float:
        """Calculate quality score based on engagement metrics
        
        Args:
            video: Video data dictionary
            
        Returns:
            Quality score between 0 and 1
        """
        views = video.get('play', 0)
        likes = video.get('like', 0)
        favorites = video.get('favorites', 0)
        comments = video.get('review', 0)
        
        if views == 0:
            return 0
        
        like_ratio = likes / views
        favorite_ratio = favorites / views
        engagement_ratio = (likes + favorites + comments) / views
        
        score = (
            like_ratio * 0.3 +
            favorite_ratio * 0.5 +
            engagement_ratio * 0.2 +
            min(views / 100000, 1.0) * 0.1
        )
        
        return score