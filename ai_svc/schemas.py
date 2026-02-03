"""
Schemas module for AI service
Contains Pydantic models for structured AI responses
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


# Enums for controlled vocabulary
class ToneEnum(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    HUMOROUS = "humorous"
    DEROGATORY = "derogatory"
    PEJORATIVE = "pejorative"
    APPROVING = "approving"


class FrequencyEnum(str, Enum):
    VERY_HIGH = "very high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ARCHAIC_RARE = "archaic/rare"


class WordSense(BaseModel):
    """Represents a specific meaning/sense of a word"""
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
    usage_notes: str = Field(
        default="",
        description="Critical guidance on when/how to use this sense and common pitfalls for learners."
    )
    examples: List[str] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="3-5 example sentences. Include at least one corrected common learner error."
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


class DictionaryEntry(BaseModel):
    """Comprehensive dictionary entry for a word or phrase"""
    headword: str = Field(..., description="The requested word or phrase.")
    pronunciation: str = Field(..., description="IPA transcription and/or a simple phonetic guide.")
    # audio_link: str = Field(default="", description="Placeholder for future audio URL.")
    senses: List[WordSense] = Field(
        ...,
        min_length=1,
        description="List of the word's different meanings/senses, ordered by most common/frequent first."
    )
    
    etymology: str = Field(..., description="Narrative of the word's origin, history, and meaning evolution.")
    root_analysis: str = Field(
        default="",
        description="Breakdown of roots, prefixes, and suffixes with their meanings."
    )
    word_family: List[str] = Field(
        default_factory=list,
        description="List of key words derived from the same root or sharing the same base."
    )
    frequency: FrequencyEnum = Field(..., description="Indication of how common the word is in modern usage.")
    modern_relevance: str = Field(
        default="",
        description="Note on current usage trends, e.g., 'rising in tech contexts', 'considered outdated'."
    )
    common_confusions: List[str] = Field(
        default_factory=list,
        description="Words/phrases often confused with this one, with brief discriminators."
    )
    # visual_mnemonic: str = Field(
    #     default="",
    #     description="A creative sentence or image suggestion to aid memory. No actual image references."
    # )
    regional_variations: List[str] = Field(
        default_factory=list,
        description="Notable differences in meaning, spelling, or usage between English variants."
    )
    notes: str = Field(
        default="",
        description="Any additional, overarching linguistic or cultural notes about the word."
    )


# Response wrapper for API consistency
class APIResponse(BaseModel):
    """Standard API response wrapper"""
    success: bool = Field(..., description="Whether the request was successful")
    data: Optional[dict] = Field(default=None, description="Response data if successful")
    error: Optional[str] = Field(default=None, description="Error message if not successful")
    message: Optional[str] = Field(default=None, description="Additional information")


# Simple definition schema for basic use cases
class SimpleDefinition(BaseModel):
    """Simple definition schema for basic dictionary lookups"""
    word: str = Field(..., description="The word being defined")
    definition: str = Field(..., description="The definition of the word")
    examples: List[str] = Field(default_factory=list, description="Example sentences")
    synonyms: List[str] = Field(default_factory=list, description="Synonyms")
    antonyms: List[str] = Field(default_factory=list, description="Antonyms")
    part_of_speech: str = Field(default="", description="Part of speech")