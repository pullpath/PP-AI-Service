"""
Enums for dictionary service
Contains controlled vocabulary enums for tone and frequency
"""
from enum import Enum


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