"""
Dictionary service schemas
Contains Pydantic models for structured AI responses
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from .enums import FrequencyEnum, ToneEnum
class EtymologyInfo(BaseModel):
    """Etymology and historical development"""
    etymology: str = Field(..., description="Narrative of the word's origin, history, and meaning evolution.")
    root_analysis: str = Field(
        default="",
        description="Breakdown of roots, prefixes, and suffixes with their meanings."
    )


class WordFamilyInfo(BaseModel):
    """Word family and related terms"""
    word_family: List[str] = Field(
        default_factory=list,
        description="List of key words derived from the same root or sharing the same base."
    )


class UsageContextInfo(BaseModel):
    """Modern usage context and trends"""
    modern_relevance: str = Field(
        default="",
        description="Note on current usage trends, e.g., 'rising in tech contexts', 'considered outdated'."
    )
    common_confusions: List[str] = Field(
        default_factory=list,
        description="Words/phrases often confused with this one, with brief discriminators."
    )
    regional_variations: List[str] = Field(
        default_factory=list,
        description="Notable differences in meaning, spelling, or usage between English variants."
    )


class CulturalNotesInfo(BaseModel):
    """Cultural and linguistic notes"""
    notes: str = Field(
        default="",
        description="Any additional, overarching linguistic or cultural notes about the word."
    )


class FrequencyInfo(BaseModel):
    """Word frequency estimation"""
    frequency: FrequencyEnum = Field(
        ...,
        description="Indication of how common the word is in modern usage: very_common, common, uncommon, rare, very_rare"
    )


# Detailed Word Sense (for Phase 2 detailed analysis)
class DetailedWordSense(BaseModel):
    """Detailed analysis of a specific word sense"""
    definition: str = Field(..., description="The core definition for this specific meaning.")
    part_of_speech: str = Field(..., description="e.g., noun, verb, phrasal verb, adjective, idiom, etc.")
    usage_register: List[str] = Field(
        ...,
        description="List the appropriate contexts. Common values: 'formal', 'informal', 'colloquial', 'slang', 'archaic', 'literary', 'professional', 'academic', 'neutral'."
    )
    domain: List[str] = Field(
        default_factory=list,
        description="Specific fields of use, e.g., ['biology', 'law', 'gaming', 'business']. Can be empty."
    )
    tone: ToneEnum = Field(..., description="The primary connotation or emotional charge of this sense.")
    usage_notes: Optional[str] = Field(
        default=None,
        description="Critical guidance on when/how to use this sense and common pitfalls for learners. Fetch separately via 'usage_notes' section."
    )
    examples: Optional[List[str]] = Field(
        default=None,
        description="Exactly 2 example sentences. Fetch separately via 'examples' section."
    )
    collocations: List[str] = Field(
        default_factory=list,
        description="Frequent word partners for this sense. Format: 'strong evidence', 'gather evidence'."
    )
    word_specific_phrases: List[str] = Field(
        default_factory=list,
        description="Fixed expressions, phrasal verbs, or idioms built around this sense. e.g., 'run up a bill', 'in the long run'."
    )
    synonyms: List[str] = Field(default_factory=list, description="Close synonyms for this specific sense.")
    antonyms: List[str] = Field(default_factory=list, description="Close antonyms for this specific sense.")


# Parallel execution components for DetailedWordSense (split for faster generation)
class SenseCoreMetadata(BaseModel):
    """Core metadata without definition (API always provides definition)"""
    part_of_speech: str = Field(..., description="e.g., noun, verb, phrasal verb, adjective, idiom, etc.")
    usage_register: List[str] = Field(
        ...,
        description="List the appropriate contexts. Common values: 'formal', 'informal', 'colloquial', 'slang', 'archaic', 'literary', 'professional', 'academic', 'neutral'."
    )
    domain: List[str] = Field(
        default_factory=list,
        description="Specific fields of use, e.g., ['biology', 'law', 'gaming', 'business']. Can be empty."
    )
    tone: ToneEnum = Field(..., description="The primary connotation or emotional charge of this sense.")


class SenseUsageExamples(BaseModel):
    """Examples and collocations (Agent 2) - Dynamic count based on API data"""
    examples: List[str] = Field(
        default_factory=list,
        min_length=0,
        max_length=2,
        description="0-2 example sentences (dynamic based on API-provided examples)."
    )
    collocations: List[str] = Field(
        default_factory=list,
        min_length=0,
        max_length=3,
        description="0-3 frequent word partners (dynamic based on available data)."
    )


class SenseRelatedWords(BaseModel):
    """Synonyms, antonyms, and related phrases (Agent 3)"""
    synonyms: List[str] = Field(default_factory=list, description="Close synonyms for this specific sense.")
    antonyms: List[str] = Field(default_factory=list, description="Close antonyms for this specific sense.")
    word_specific_phrases: List[str] = Field(
        default_factory=list,
        description="Fixed expressions, phrasal verbs, or idioms built around this sense. e.g., 'run up a bill', 'in the long run'."
    )


class SenseUsageNotes(BaseModel):
    """Usage notes and guidance (Agent 4)"""
    usage_notes: str = Field(
        default="",
        description="Critical guidance on when/how to use this sense and common pitfalls for learners."
    )


class BilibiliVideoInfo(BaseModel):
    """Bilibili video information for dictionary word explanations"""
    bvid: str = Field(..., description="Bilibili video BV ID")
    aid: int = Field(..., description="Bilibili video AV ID")
    title: str = Field(..., description="Video title")
    description: str = Field(default="", description="Video description")
    pic: str = Field(default="", description="Video thumbnail URL")
    author: str = Field(default="", description="Author/UP name")
    mid: int = Field(default=0, description="Author UID")
    view: int = Field(default=0, description="View count")
    danmaku: int = Field(default=0, description="Danmaku count")
    reply: int = Field(default=0, description="Comment count")
    favorite: int = Field(default=0, description="Favorite count")
    coin: int = Field(default=0, description="Coin count")
    share: int = Field(default=0, description="Share count")
    like: int = Field(default=0, description="Like count")
    pubdate: int = Field(default=0, description="Publish timestamp")
    duration: int = Field(default=0, description="Video duration in seconds")
    start_time: float = Field(default=0.0, description="Start time in seconds for direct playback to relevant content")
    matched_phrase: str = Field(default="", description="The word or phrase that was matched to find this video")
    video_url: str = Field(default="", description="Composed Bilibili video URL with optional start time")


class CommonPhrases(BaseModel):
    """Common phrases and collocations for a word"""
    phrases: List[str] = Field(
        default_factory=list,
        min_length=1,
        max_length=3,
        description="1-3 commonly used phrases or collocations. If word is standalone, just the word."
    )