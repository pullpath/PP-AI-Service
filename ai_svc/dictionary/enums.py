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
    VERY_COMMON = "very_common"
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    VERY_RARE = "very_rare"