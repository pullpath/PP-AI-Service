"""
Dictionary service schemas for two-phase parallel architecture
Contains Pydantic models for structured AI responses
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from .enums import FrequencyEnum, ToneEnum


# Phase 1: Word Senses Discovery
class WordSenseBasic(BaseModel):
    """Basic information about a word sense (for discovery phase)"""
    definition: str = Field(..., description="The core definition for this specific meaning.")
    sense_index: int = Field(..., description="Index of this sense (0-based)")


class WordSensesDiscovery(BaseModel):
    """Result of Phase 1: Discover commonly used word senses"""
    headword: str = Field(..., description="The requested word or phrase.")
    pronunciation: str = Field(..., description="Audio URL (from API) or IPA string (AI-generated when API fails). Frontend should check if starts with 'http' to determine format.")
    senses: List[WordSenseBasic] = Field(
        ...,
        min_length=1,
        description="List of commonly used word senses, ordered by most common/frequent first."
    )


# Phase 2: Granular Information Components (for parallel fetch)
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
    usage_notes: str = Field(
        default="",
        description="Critical guidance on when/how to use this sense and common pitfalls for learners."
    )
    examples: List[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Exactly 3 example sentences."
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
    """Core definition and metadata (Agent 1)"""
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


class SenseUsageExamples(BaseModel):
    """Examples and collocations (Agent 2)"""
    examples: List[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Exactly 3 example sentences."
    )
    collocations: List[str] = Field(
        default_factory=list,
        description="Frequent word partners for this sense. Format: 'strong evidence', 'gather evidence'."
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