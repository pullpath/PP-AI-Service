"""
Optimized Dictionary Service using hybrid API + AI architecture
Step 1: Fetch basic data from free dictionary API
Step 2: Use AI only for enhanced/missing information

Only exposes one interface: lookup_word()
"""
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from typing import Dict, Any, List, Optional
import os
import time
import concurrent.futures
import requests
import logging
from dotenv import load_dotenv
from bilibili_api import search, sync, video, Credential, video_zone


# Import schemas and prompts
from .schemas import (
    EtymologyInfo, WordFamilyInfo,
    UsageContextInfo, CulturalNotesInfo, DetailedWordSense, FrequencyInfo,
    SenseCoreMetadata, SenseUsageExamples, SenseRelatedWords, SenseUsageNotes,
    BilibiliVideoInfo, CommonPhrases
)
from .prompts import (
    get_etymology_prompt,
    get_word_family_prompt, get_usage_context_prompt,
    get_cultural_notes_prompt, get_frequency_prompt,
    get_sense_core_metadata_prompt, get_sense_usage_examples_prompt,
    get_sense_related_words_prompt, get_sense_usage_notes_prompt,
    get_common_phrases_prompt
)

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

class DictionaryService:
    """Dictionary service with hybrid API + AI architecture"""

    DICTIONARY_API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en"
    
    # Bilibili search configuration
    BILIBILI_PAGE_SIZE = 50
    MAX_VIDEOS_TO_CHECK_FOR_SUBTITLES = 50

    def __init__(self):
        """Initialize the dictionary service with AI agents and credentials"""
        # Load environment variables
        load_dotenv()

        # Set up Bilibili credentials for subtitle access
        sessdata = os.getenv('BILIBILI_SESSDATA')
        bili_jct = os.getenv('BILIBILI_BILI_JCT')
        buvid3 = os.getenv('BILIBILI_BUVID3')

        if sessdata and bili_jct:  # buvid3 is optional but recommended
            self.bilibili_credential = Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3)
            logger.info("Bilibili credentials configured for subtitle access")
        else:
            self.bilibili_credential = None
            logger.warning("Bilibili credentials not configured - subtitle access will be limited")

        # Get DeepSeek API key from environment
        deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')

        if not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

        # Create DeepSeek models with different token limits for optimization
        # Simple tasks (frequency, word_family): 256 tokens
        # Medium tasks (etymology, cultural_notes, usage_context): 512 tokens
        # Complex tasks (detailed_sense): 1024 tokens

        simple_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=256,
            timeout=45.0,
            max_retries=0
        )

        medium_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=512,
            timeout=45.0,
            max_retries=0
        )

        complex_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=600,  # Further reduced to speed up
            timeout=30.0,  # Reduced timeout to push for faster inference
            max_retries=0
        )

        # Create specialized agents with appropriate models
        self.etymology_agent = Agent(
            name="EtymologyAgent",
            model=medium_model,
            description="Provides etymology and root analysis",
            use_json_mode=True,
            output_schema=EtymologyInfo
        )

        self.word_family_agent = Agent(
            name="WordFamilyAgent",
            model=simple_model,
            description="Provides word family and related terms",
            use_json_mode=True,
            output_schema=WordFamilyInfo
        )

        self.usage_context_agent = Agent(
            name="UsageContextAgent",
            model=medium_model,
            description="Provides modern usage context and trends",
            use_json_mode=True,
            output_schema=UsageContextInfo
        )

        self.cultural_notes_agent = Agent(
            name="CulturalNotesAgent",
            model=medium_model,
            description="Provides cultural and linguistic notes",
            use_json_mode=True,
            output_schema=CulturalNotesInfo
        )

        self.detailed_sense_agent = Agent(
            name="DetailedSenseAgent",
            model=complex_model,
            description="Provides enhanced analysis for specific word senses",
            use_json_mode=True,
            output_schema=DetailedWordSense
        )

        self.common_phrases_agent = Agent(
            name="CommonPhrasesAgent",
            model=simple_model,
            description="Provides commonly used phrases for a word",
            use_json_mode=True,
            output_schema=CommonPhrases
        )

        self.frequency_agent = Agent(
            name="FrequencyAgent",
            model=simple_model,
            description="Provides frequency estimation for a word",
            use_json_mode=True,
            output_schema=FrequencyInfo
        )

        # Parallel execution agents for detailed sense (faster performance)
        # These agents split DetailedWordSense generation into 2 parallel tasks
        # Optimized models with reduced tokens for faster generation

        # Agent 1: Core metadata WITHOUT definition (API always provides definition)
        core_metadata_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=200,
            timeout=30.0,
            max_retries=0
        )

        # Agent 2: Examples and collocations (3 examples, 3 collocations) - medium tokens
        usage_examples_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=200,
            timeout=30.0,
            max_retries=0
        )

        # Agent 3: Related words (3 synonyms, 3 antonyms, 3 phrases) - medium tokens
        related_words_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=200,
            timeout=30.0,
            max_retries=0
        )

        # Agent 4: Usage notes (2-3 sentences) - smallest tokens
        usage_notes_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=150,
            timeout=30.0,
            max_retries=0
        )

        self.sense_core_agent = Agent(
            name="SenseCoreMetadataAgent",
            model=core_metadata_model,
            description="Provides core metadata (API provides definition)",
            use_json_mode=True,
            output_schema=SenseCoreMetadata
        )

        self.sense_usage_agent = Agent(
            name="SenseUsageExamplesAgent",
            model=usage_examples_model,
            description="Provides examples and collocations",
            use_json_mode=True,
            output_schema=SenseUsageExamples
        )

        self.sense_related_agent = Agent(
            name="SenseRelatedWordsAgent",
            model=related_words_model,
            description="Provides synonyms, antonyms, and related phrases",
            use_json_mode=True,
            output_schema=SenseRelatedWords
        )

        self.sense_usage_notes_agent = Agent(
            name="SenseUsageNotesAgent",
            model=usage_notes_model,
            description="Provides usage notes and guidance",
            use_json_mode=True,
            output_schema=SenseUsageNotes
        )
    
    
    def lookup_section(self, word: str, section: str, sense_index: Optional[int] = None, entry_index: Optional[int] = None) -> Dict[str, Any]:
        """
        Look up specific section of word data with entry-level awareness
        
        Parameters:
        - word: The word to look up
        - section: Section to fetch
        - sense_index: Sense index within an entry (0-based, for 'detailed_sense')
        - entry_index: Entry index (0-based, for entry-specific sections and 'detailed_sense')
        
        Sections:
        - basic: Returns entry-level structure (no parameters needed)
        - etymology, word_family, usage_context, cultural_notes, frequency: 
            Require entry_index (defaults to 0)
        - detailed_sense: Requires BOTH entry_index AND sense_index
        
        Examples:
        - {"word": "scrub", "section": "basic"}
        - {"word": "scrub", "section": "etymology", "entry_index": 1}
        - {"word": "scrub", "section": "detailed_sense", "entry_index": 1, "sense_index": 0}
        """
        try:
            start_time = time.time()
            
            valid_sections = [
                'etymology', 'word_family', 'usage_context', 
                'cultural_notes', 'frequency', 'detailed_sense', 'basic',
                'examples', 'usage_notes', 'bilibili_videos'
            ]
            
            if section not in valid_sections:
                return {
                    "error": f"Invalid section '{section}'. Valid sections: {', '.join(valid_sections)}",
                    "success": False
                }
            
            if section == 'detailed_sense':
                if entry_index is None or sense_index is None:
                    return {
                        "error": "detailed_sense requires both 'entry_index' and 'sense_index'",
                        "success": False
                    }
                
                result = self._fetch_single_detailed_sense_2d(word, entry_index, sense_index)
                
                if not result.get("success"):
                    return result
                
                return {
                    "headword": word,
                    "detailed_sense": result["detailed_sense"],
                    "entry_index": result.get("entry_index", 0),
                    "sense_index": result.get("sense_index", 0),
                    "execution_time": time.time() - start_time,
                    "success": True
                }
            
            if section == 'basic':
                return self._fetch_basic(word, start_time)
            
            if section == 'examples':
                if entry_index is None or sense_index is None:
                    return {
                        "error": "examples section requires both 'entry_index' and 'sense_index'",
                        "success": False
                    }
                result = self._fetch_sense_examples_standalone(word, entry_index, sense_index)
                if not result.get("success"):
                    return result
                return {
                    "headword": word,
                    "entry_index": entry_index,
                    "sense_index": sense_index,
                    "examples": result["examples"],
                    "collocations": result["collocations"],
                    "execution_time": time.time() - start_time,
                    "success": True
                }
            
            if section == 'usage_notes':
                if entry_index is None or sense_index is None:
                    return {
                        "error": "usage_notes section requires both 'entry_index' and 'sense_index'",
                        "success": False
                    }
                result = self._fetch_sense_usage_notes_standalone(word, entry_index, sense_index)
                if not result.get("success"):
                    return result
                return {
                    "headword": word,
                    "entry_index": entry_index,
                    "sense_index": sense_index,
                    "usage_notes": result["usage_notes"],
                    "execution_time": time.time() - start_time,
                    "success": True
                }
            
            entry_level_sections = ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency', 'bilibili_videos']
            if section in entry_level_sections:
                return self._fetch_entry_level_section(word, section, entry_index, start_time)
            
            return {
                "error": f"Section '{section}' not implemented",
                "success": False
            }
                
        except Exception as e:
            return {
                "headword": word,
                "error": str(e),
                "success": False
            }
    
    def _fetch_basic(self, word: str, start_time: float) -> Dict[str, Any]:
        """
        Fetch basic word info with entry-level structure including API sense data
        
        Returns:
        {
            "headword": "scrub",
            "total_entries": 2,
            "entries": [
                {
                    "entry_index": 0,
                    "pronunciation": "https://api.dictionaryapi.dev/media/pronunciations/en/scrub-uk.mp3",
                    "ipa": "/skrʌb/",
                    "meanings_summary": [
                        {
                            "part_of_speech": "noun",
                            "definition_count": 6,
                            "senses": [
                                {
                                    "definition": "A thicket or jungle, often specified by the name of the prevailing plant",
                                    "example": "We fought our way through the oak scrub.",
                                    "synonyms": ["brush", "undergrowth"],
                                    "antonyms": []
                                },
                                ...
                            ]
                        }
                    ],
                    "total_senses": 7
                }
            ],
            "total_senses": 21,
            "data_source": "api",
            "execution_time": 0.543,
            "success": True
        }
        """
        api_result = self._fetch_from_api(word)
        
        if api_result.get("success"):
            logger.info(f"[{word}] Basic data: Using FREE API (hybrid_api_ai)")
            entries_data = api_result["entries"]
            
            entries_info = []
            total_senses = 0
            
            for entry_idx, entry in enumerate(entries_data):
                meanings = entry.get("meanings", [])
                meanings_summary = []
                entry_senses = 0
                
                for meaning in meanings:
                    pos = meaning.get("partOfSpeech", "unknown")
                    definitions = meaning.get("definitions", [])
                    def_count = len(definitions)
                    entry_senses += def_count
                    
                    meaning_synonyms = meaning.get("synonyms", [])
                    meaning_antonyms = meaning.get("antonyms", [])
                    
                    senses = []
                    for def_obj in definitions:
                        definition = def_obj.get("definition", "")
                        example = def_obj.get("example", "")
                        def_synonyms = def_obj.get("synonyms", []) or meaning_synonyms
                        def_antonyms = def_obj.get("antonyms", []) or meaning_antonyms
                        
                        senses.append({
                            "definition": definition,
                            "example": example if example else None,
                            "synonyms": def_synonyms[:3] if def_synonyms else [],
                            "antonyms": def_antonyms[:3] if def_antonyms else []
                        })
                    
                    meanings_summary.append({
                        "part_of_speech": pos,
                        "definition_count": def_count,
                        "senses": senses
                    })
                
                pronunciation_data = self._extract_pronunciation_data(entry)
                
                entries_info.append({
                    "entry_index": entry_idx,
                    "pronunciation": pronunciation_data["pronunciation"],
                    "ipa": pronunciation_data["ipa"],
                    "meanings_summary": meanings_summary,
                    "total_senses": entry_senses
                })
                
                total_senses += entry_senses
            
            return {
                "headword": word,
                "total_entries": len(entries_data),
                "entries": entries_info,
                "total_senses": total_senses,
                "data_source": "api",
                "execution_time": time.time() - start_time,
                "success": True
            }
        else:
            logger.error(f"[{word}] Basic data: API failed - {api_result.get('error', 'unknown')}")
            return {
                "headword": word,
                "error": f"Dictionary API failed: {api_result.get('error', 'Word not found')}",
                "success": False
            }
    
    def _extract_pronunciation_data(self, entry: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract pronunciation data (audio URL + IPA) from API entry
        
        Returns:
        {
            "pronunciation": "audio_url",  # Empty string if not found
            "ipa": "/skrʌb/"                # Empty string if not found
        }
        """
        phonetics = entry.get("phonetics", [])
        audio_url = ""
        ipa_text = ""
        
        # Extract audio URL (prefer UK > US > any)
        for p in phonetics:
            audio = p.get("audio", "")
            if audio and ("-uk.mp3" in audio.lower() or "-uk-" in audio.lower()):
                audio_url = audio
                break
        
        if not audio_url:
            for p in phonetics:
                audio = p.get("audio", "")
                if audio and ("-us.mp3" in audio.lower() or "-us-" in audio.lower()):
                    audio_url = audio
                    break
        
        if not audio_url:
            for p in phonetics:
                audio = p.get("audio", "")
                if audio:
                    audio_url = audio
                    break
        
        # Extract IPA text
        for p in phonetics:
            if p.get("text"):
                ipa_text = p["text"]
                break
        
        if not ipa_text:
            ipa_text = entry.get("phonetic", "")
        
        return {
            "pronunciation": audio_url,
            "ipa": ipa_text
        }
    
    def _fetch_entry_level_section(self, word: str, section: str, entry_index: Optional[int], start_time: float) -> Dict[str, Any]:
        """
        Fetch entry-specific section (etymology, word_family, etc.)
        
        If entry_index is None, defaults to entry 0 for backward compatibility
        """
        if entry_index is not None and entry_index < 0:
            return {
                "error": f"entry_index must be >= 0, got {entry_index}",
                "success": False
            }
        
        api_result = self._fetch_from_api(word)
        
        if api_result.get("success"):
            entries = api_result["entries"]
            target_entry_index = entry_index if entry_index is not None else 0
            
            if target_entry_index >= len(entries):
                return {
                    "error": f"entry_index {target_entry_index} out of range. Word has {len(entries)} entries (0-{len(entries)-1})",
                    "success": False
                }
            
            logger.info(f"[{word}] {section} (entry #{target_entry_index}): Using API structure + AI")
            context_entry = entries[target_entry_index]
        else:
            logger.info(f"[{word}] {section}: Using AI only - API failed")
            target_entry_index = 0
            context_entry = None
        
        section_method_map = {
            'etymology': self._fetch_etymology,
            'word_family': self._fetch_word_family,
            'usage_context': self._fetch_usage_context,
            'cultural_notes': self._fetch_cultural_notes,
            'frequency': self._fetch_frequency,
            'bilibili_videos': self._fetch_bilibili_videos
        }
        
        method = section_method_map.get(section)
        if not method:
            return {
                "error": f"Section '{section}' not implemented",
                "success": False
            }
        
        result = method(word, context_entry)
        
        if not result.get("success"):
            return result
        
        response = {
            "headword": word,
            "entry_index": target_entry_index,
            section: result[section],
            "execution_time": time.time() - start_time,
            "success": True
        }
        
        return response
    
    def _fetch_single_detailed_sense_2d(self, word: str, entry_index: int, sense_index: int) -> Dict[str, Any]:
        """
        Fetch a single detailed sense using 2D indexing (entry_index, sense_index)
        
        Clean approach: entry_index=1, sense_index=0 means "entry 1, first sense"
        """
        try:
            api_result = self._fetch_from_api(word)
            
            if api_result.get("success"):
                logger.info(f"[{word}] Detailed sense (entry {entry_index}, sense {sense_index}): Using API + AI (hybrid)")
                entries = api_result["entries"]
                
                if entry_index < 0 or entry_index >= len(entries):
                    return {
                        "error": f"Invalid entry_index {entry_index}. Word has {len(entries)} entries (0-{len(entries)-1})",
                        "success": False
                    }
                
                entry = entries[entry_index]
                meanings = entry.get("meanings", [])
                
                current_sense_index = 0
                for meaning in meanings:
                    part_of_speech = meaning.get("partOfSpeech", "")
                    definitions = meaning.get("definitions", [])
                    meaning_synonyms = meaning.get("synonyms", [])
                    meaning_antonyms = meaning.get("antonyms", [])
                    
                    for def_obj in definitions:
                        if current_sense_index == sense_index:
                            definition = def_obj.get("definition", "")
                            example = def_obj.get("example", "")
                            def_synonyms = def_obj.get("synonyms", []) or meaning_synonyms
                            def_antonyms = def_obj.get("antonyms", []) or meaning_antonyms
                            
                            sense_result = self._fetch_enhanced_sense(
                                word, sense_index, part_of_speech,
                                [definition], def_synonyms, def_antonyms,
                                [example] if example else []
                            )
                            
                            if sense_result.get("success"):
                                return {
                                    "detailed_sense": sense_result["sense_detail"],
                                    "entry_index": entry_index,
                                    "sense_index": sense_index,
                                    "success": True
                                }
                            else:
                                return sense_result
                        
                        current_sense_index += 1
                
                total_senses_in_entry = current_sense_index
                return {
                    "error": f"Invalid sense_index {sense_index}. Entry {entry_index} has {total_senses_in_entry} senses (0-{total_senses_in_entry-1})",
                    "success": False
                }
            else:
                logger.error(f"[{word}] Detailed sense (entry {entry_index}, sense {sense_index}): API failed - {api_result.get('error', 'unknown')}")
                return {
                    "error": f"Dictionary API failed: {api_result.get('error', 'Word not found')}",
                    "success": False
                }
                
        except Exception as e:
            return {
                "error": str(e),
                "success": False
            }
    
    def _fetch_from_api(self, word: str) -> Dict[str, Any]:
        """
        Fetch basic dictionary data from free API with entry-level structure
        
        Returns entry-aware structure:
        {
            "success": True,
            "entries": [entry1, entry2, ...],  # Raw API entries
            "total_entries": 2
        }
        """
        try:
            url = f"{self.DICTIONARY_API_BASE}/{word}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return {
                        "success": True,
                        "entries": data,
                        "total_entries": len(data)
                    }
            
            return {
                "success": False,
                "error": f"API returned status {response.status_code}"
            }
            
        except requests.Timeout:
            return {
                "success": False,
                "error": "API request timeout"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    
    def _fetch_common_phrases(self, word: str) -> List[str]:
        """Fetch common phrases for a word via AI"""
        try:
            prompt = get_common_phrases_prompt(word)
            response = self.common_phrases_agent.run(prompt)
            
            if isinstance(response.content, CommonPhrases):
                return response.content.phrases
            else:
                return [word]  # fallback to just the word
        except Exception as e:
            logger.error(f"Error fetching common phrases for '{word}': {str(e)}")
            return [word]  # fallback
    
    def _fetch_frequency(self, word: str, context_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch frequency estimation via AI"""
        try:
            prompt = get_frequency_prompt(word)
            response = self.frequency_agent.run(prompt)
            
            if isinstance(response.content, FrequencyInfo):
                return {
                    "success": True,
                    "frequency": response.content.frequency
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse frequency information"
                }
        except Exception as e:
            print(f"Error fetching frequency: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_enhanced_sense(self, word: str, sense_index: int, part_of_speech: str,
                             api_definitions: List[str], api_synonyms: Optional[List[str]] = None,
                             api_antonyms: Optional[List[str]] = None, api_examples: Optional[List[str]] = None) -> Dict[str, Any]:
        """Fetch AI-enhanced analysis for a sense using parallel execution (API already provides basics)
        
        Note: Examples and usage_notes are excluded for faster loading.
        Frontend should fetch them separately via 'examples' and 'usage_notes' sections.
        """
        try:
            basic_definition = api_definitions[0] if api_definitions else ""
            
            api_synonyms = api_synonyms or []
            api_antonyms = api_antonyms or []
            
            TARGET_SYNONYMS = 3
            TARGET_ANTONYMS = 3
            TARGET_PHRASES = 3
            
            synonyms_needed = max(0, TARGET_SYNONYMS - len(api_synonyms))
            antonyms_needed = max(0, TARGET_ANTONYMS - len(api_antonyms))
            phrases_needed = TARGET_PHRASES
            
            logger.info(f"[Dynamic Prompts] Word '{word}' sense {sense_index}: "
                       f"synonyms {len(api_synonyms)}→{synonyms_needed}, "
                       f"antonyms {len(api_antonyms)}→{antonyms_needed} "
                       f"(definition from API, examples/usage_notes: fetch separately)")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_core = executor.submit(
                    self._fetch_sense_core_metadata, 
                    word, sense_index, basic_definition, part_of_speech
                )
                future_related = executor.submit(
                    self._fetch_sense_related_words,
                    word, sense_index, basic_definition, api_synonyms, api_antonyms,
                    synonyms_needed, antonyms_needed, phrases_needed
                )
                
                done, not_done = concurrent.futures.wait(
                    [future_core, future_related],
                    timeout=30.0,
                    return_when=concurrent.futures.ALL_COMPLETED
                )
                
                for future in not_done:
                    future.cancel()
                
                core_result = self._get_future_result(future_core, "core_metadata")
                related_result = self._get_future_result(future_related, "related_words")
            
            if not all([
                core_result and core_result.get("success"),
                related_result and related_result.get("success")
            ]):
                errors = []
                if not core_result or not core_result.get("success"):
                    errors.append(f"core: {core_result.get('error') if core_result else 'timeout'}")
                if not related_result or not related_result.get("success"):
                    errors.append(f"related: {related_result.get('error') if related_result else 'timeout'}")
                
                return {
                    "success": False,
                    "error": f"Parallel execution failed: {', '.join(errors)}"
                }
            
            assert core_result and "data" in core_result
            assert related_result and "data" in related_result
            
            ai_synonyms = related_result["data"]["synonyms"]
            ai_antonyms = related_result["data"]["antonyms"]
            ai_phrases = related_result["data"]["word_specific_phrases"]
            
            merged_synonyms = list(dict.fromkeys(api_synonyms + ai_synonyms))[:TARGET_SYNONYMS]
            merged_antonyms = list(dict.fromkeys(api_antonyms + ai_antonyms))[:TARGET_ANTONYMS]
            merged_phrases = ai_phrases[:TARGET_PHRASES]
            
            while len(merged_synonyms) < TARGET_SYNONYMS:
                merged_synonyms.append("")
            while len(merged_antonyms) < TARGET_ANTONYMS:
                merged_antonyms.append("")
            while len(merged_phrases) < TARGET_PHRASES:
                merged_phrases.append("")
            
            sense_detail = {
                "definition": core_result["data"]["definition"],
                "part_of_speech": core_result["data"]["part_of_speech"],
                "usage_register": core_result["data"]["usage_register"],
                "domain": core_result["data"]["domain"],
                "tone": core_result["data"]["tone"],
                "synonyms": merged_synonyms,
                "antonyms": merged_antonyms,
                "word_specific_phrases": merged_phrases,
            }
            
            return {
                "success": True,
                "sense_index": sense_index,
                "sense_detail": sense_detail
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_sense_core_metadata(self, word: str, sense_index: int, basic_definition: str, 
                                   part_of_speech: str = "") -> Dict[str, Any]:
        """Fetch core metadata for a sense (parallel execution component)
        
        Note: API always provides definition (assembled in logic after AI response)
        """
        try:
            prompt = get_sense_core_metadata_prompt(word, sense_index, basic_definition)
            response = self.sense_core_agent.run(prompt)
            
            if isinstance(response.content, SenseCoreMetadata):
                data = response.content.model_dump()
                # Assemble definition from API response (not AI-generated)
                data["definition"] = basic_definition
                if part_of_speech:
                    data["part_of_speech"] = part_of_speech
                return {
                    "success": True,
                    "data": data
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse core metadata"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_sense_usage_examples(self, word: str, sense_index: int, basic_definition: str,
                                   api_examples: Optional[List[str]] = None,
                                   examples_needed: int = 2,
                                   collocations_needed: int = 3) -> Dict[str, Any]:
        """Fetch usage notes and examples for a sense (parallel execution component)
        
        Dynamic generation based on API data availability
        """
        try:
            prompt = get_sense_usage_examples_prompt(
                word, sense_index, basic_definition, api_examples,
                examples_needed, collocations_needed
            )
            response = self.sense_usage_agent.run(prompt)
            
            if isinstance(response.content, SenseUsageExamples):
                return {
                    "success": True,
                    "data": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse usage examples"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_sense_related_words(self, word: str, sense_index: int, basic_definition: str,
                                  api_synonyms: Optional[List[str]] = None, 
                                  api_antonyms: Optional[List[str]] = None,
                                  synonyms_needed: int = 3,
                                  antonyms_needed: int = 3,
                                  phrases_needed: int = 3) -> Dict[str, Any]:
        """Fetch related words and phrases for a sense (parallel execution component)
        
        Dynamic generation based on API data availability
        """
        try:
            prompt = get_sense_related_words_prompt(
                word, sense_index, basic_definition, 
                api_synonyms, api_antonyms,
                synonyms_needed, antonyms_needed, phrases_needed
            )
            response = self.sense_related_agent.run(prompt)
            
            if isinstance(response.content, SenseRelatedWords):
                return {
                    "success": True,
                    "data": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse related words"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_sense_usage_notes(self, word: str, sense_index: int, basic_definition: str) -> Dict[str, Any]:
        """Fetch usage notes and guidance for a sense (parallel execution component)"""
        try:
            prompt = get_sense_usage_notes_prompt(word, sense_index, basic_definition)
            response = self.sense_usage_notes_agent.run(prompt)
            
            if isinstance(response.content, SenseUsageNotes):
                return {
                    "success": True,
                    "data": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse usage notes"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    
    def _fetch_etymology(self, word: str, context_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch etymology information"""
        try:
            prompt = get_etymology_prompt(word)
            response = self.etymology_agent.run(prompt)
            
            if isinstance(response.content, EtymologyInfo):
                return {
                    "success": True,
                    "etymology": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse etymology information"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_word_family(self, word: str, context_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch word family information"""
        try:
            prompt = get_word_family_prompt(word)
            response = self.word_family_agent.run(prompt)
            
            if isinstance(response.content, WordFamilyInfo):
                return {
                    "success": True,
                    "word_family": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse word family information"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_usage_context(self, word: str, context_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch usage context information"""
        try:
            prompt = get_usage_context_prompt(word)
            response = self.usage_context_agent.run(prompt)
            
            if isinstance(response.content, UsageContextInfo):
                return {
                    "success": True,
                    "usage_context": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse usage context information"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_cultural_notes(self, word: str, context_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch cultural notes information"""
        try:
            prompt = get_cultural_notes_prompt(word)
            response = self.cultural_notes_agent.run(prompt)
            
            if isinstance(response.content, CulturalNotesInfo):
                return {
                    "success": True,
                    "cultural_notes": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to parse cultural notes information"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _get_future_result(self, future, task_name: str) -> Optional[Dict[str, Any]]:
        """Safely get result from a future"""
        try:
            if future.cancelled():
                print(f"Warning: Task {task_name} was cancelled")
                return {
                    "success": False,
                    "error": f"Task {task_name} was cancelled"
                }
            
            return future.result(timeout=0.1)
        except concurrent.futures.TimeoutError:
            print(f"Warning: Task {task_name} not ready")
            return {
                "success": False,
                "error": f"Task {task_name} not ready"
            }
        except Exception as e:
            print(f"Warning: Error fetching {task_name}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_sense_examples_standalone(self, word: str, entry_index: int, sense_index: int) -> Dict[str, Any]:
        """Fetch examples and collocations for a specific sense (standalone endpoint)"""
        try:
            api_data = self._fetch_from_api(word)
            
            if api_data.get("success"):
                entries = api_data.get("entries", [])
                if entry_index >= len(entries):
                    return {
                        "success": False,
                        "error": f"Entry index {entry_index} out of range (total entries: {len(entries)})"
                    }
                
                entry = entries[entry_index]
                meanings = entry.get("meanings", [])
                
                flat_index = 0
                for meaning in meanings:
                    definitions = meaning.get("definitions", [])
                    if flat_index + len(definitions) > sense_index:
                        definition_index = sense_index - flat_index
                        definition = definitions[definition_index]
                        
                        api_example = definition.get("example")
                        api_examples = [api_example] if api_example else []
                        basic_definition = definition.get("definition", "")
                        
                        TARGET_EXAMPLES = 2
                        TARGET_COLLOCATIONS = 3
                        examples_needed = max(0, TARGET_EXAMPLES - len(api_examples))
                        collocations_needed = TARGET_COLLOCATIONS
                        
                        result = self._fetch_sense_usage_examples(
                            word, sense_index, basic_definition, api_examples,
                            examples_needed, collocations_needed
                        )
                        
                        if result.get("success"):
                            ai_examples = result["data"]["examples"]
                            ai_collocations = result["data"]["collocations"]
                            
                            merged_examples = list(dict.fromkeys(api_examples + ai_examples))[:TARGET_EXAMPLES]
                            merged_collocations = ai_collocations[:TARGET_COLLOCATIONS]
                            
                            while len(merged_examples) < TARGET_EXAMPLES:
                                merged_examples.append("")
                            while len(merged_collocations) < TARGET_COLLOCATIONS:
                                merged_collocations.append("")
                            
                            return {
                                "success": True,
                                "examples": merged_examples,
                                "collocations": merged_collocations
                            }
                        else:
                            return result
                    
                    flat_index += len(definitions)
                
                return {
                    "success": False,
                    "error": f"Sense index {sense_index} not found in entry {entry_index}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Dictionary API failed: {api_data.get('error', 'Word not found')}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_sense_usage_notes_standalone(self, word: str, entry_index: int, sense_index: int) -> Dict[str, Any]:
        """Fetch usage notes for a specific sense (standalone endpoint)"""
        try:
            api_data = self._fetch_from_api(word)
            
            if api_data.get("success"):
                entries = api_data.get("entries", [])
                if entry_index >= len(entries):
                    return {
                        "success": False,
                        "error": f"Entry index {entry_index} out of range (total entries: {len(entries)})"
                    }
                
                entry = entries[entry_index]
                meanings = entry.get("meanings", [])
                
                flat_index = 0
                for meaning in meanings:
                    definitions = meaning.get("definitions", [])
                    if flat_index + len(definitions) > sense_index:
                        definition_index = sense_index - flat_index
                        definition = definitions[definition_index]
                        basic_definition = definition.get("definition", "")
                        
                        result = self._fetch_sense_usage_notes(word, sense_index, basic_definition)
                        
                        if result.get("success"):
                            return {
                                "success": True,
                                "usage_notes": result["data"]["usage_notes"]
                            }
                        else:
                            return result
                    
                    flat_index += len(definitions)
                
                return {
                    "success": False,
                    "error": f"Sense index {sense_index} not found in entry {entry_index}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Dictionary API failed: {api_data.get('error', 'Word not found')}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _fetch_bilibili_videos(self, word: str, context_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch Bilibili videos related to the word's definition and explanation with phrase-based search"""
        try:
            # First, get common phrases for this word
            phrases = self._fetch_common_phrases(word)
            logger.info(f"[{word}] Generated phrases: {phrases}")
            
            all_videos = []
            
            # For each phrase, search Bilibili with improved filtering
            for phrase in phrases:
                logger.info(f"[{word}] Searching Bilibili for phrase: '{phrase}'")
                
                try:
                    # First try KNOWLEDGE zone for educational content
                    used_knowledge_zone = True
                    search_result = sync(search.search_by_type(
                        keyword=phrase, 
                        search_type=search.SearchObjectType.VIDEO,
                        order_type=search.OrderVideo.STOW,  # Sort by favorites for quality content
                        video_zone_type=video_zone.VideoZoneTypes.KNOWLEDGE,  # KNOWLEDGE section for educational content
                        page=1,
                        page_size=self.BILIBILI_PAGE_SIZE  # Increased to get more results to filter
                    ))
                    
                    videos = search_result.get('result', [])
                    logger.info(f"[{word}] Found {len(videos)} videos in KNOWLEDGE zone for phrase '{phrase}'")
                    
                    # If no videos found in KNOWLEDGE zone, try general search
                    if not videos:
                        logger.info(f"[{word}] No videos in KNOWLEDGE zone for '{phrase}', trying general search")
                        used_knowledge_zone = False
                        search_result = sync(search.search_by_type(
                            keyword=phrase, 
                            search_type=search.SearchObjectType.VIDEO,
                            order_type=search.OrderVideo.STOW,
                            page=1,
                            page_size=self.BILIBILI_PAGE_SIZE
                        ))
                        videos = search_result.get('result', [])
                        logger.info(f"[{word}] Found {len(videos)} videos in general search for phrase '{phrase}'")
                    
                    # Process search results and filter videos
                    filtered_videos = []
                    for video in videos:
                        # Parse duration
                        duration = self._parse_duration(video.get('duration', '0'))
                        
                        # Apply filters
                        if not (45 <= duration <= 1800):
                            continue
                        
                        # Use different educational criteria based on search type
                        if used_knowledge_zone:
                            # Strict filtering for KNOWLEDGE zone
                            if not self._is_educational_video(video):
                                continue
                        else:
                            # Relaxed filtering for general search - just avoid bad content
                            if self._has_avoid_tags(video):
                                continue
                        
                        if video.get('play', 0) < 100:
                            continue
                        
                        if video.get('favorites', 0) < 10:
                            continue
                        
                        # Calculate quality score
                        quality_score = self._calculate_quality_score(video)
                        if quality_score < 0.01:
                            continue
                        
                        filtered_videos.append({
                            'video': video,
                            'quality_score': quality_score
                        })
                    
                    logger.info(f"[{word}] After filtering: {len(filtered_videos)} videos for phrase '{phrase}'")
                     
                    # Sort by quality score and check subtitles
                    filtered_videos.sort(key=lambda x: x['quality_score'], reverse=True)
                    
                    best_video = None
                    best_subtitle_occurrences = []
                    best_score = 0
                    
                    # Check top 50 videos for subtitle matches
                    for item in filtered_videos[:self.MAX_VIDEOS_TO_CHECK_FOR_SUBTITLES]:
                        video = item['video']
                        bvid = video.get('bvid', '')
                        
                        # Check for subtitle matches
                        subtitle_occurrences = self._get_bilibili_subtitles(bvid, phrase)
                        
                        if subtitle_occurrences:
                            logger.info(f"[{word}] Video {bvid} has {len(subtitle_occurrences)} subtitle matches for '{phrase}'")
                            best_video = video
                            best_subtitle_occurrences = subtitle_occurrences
                            best_score = item['quality_score']
                            break  # Take first video with subtitle matches
                        else:
                            logger.info(f"[{word}] Video {bvid} has no subtitle matches for '{phrase}' - will use anyway")
                            # If no subtitle matches found, still use the video but with start_time=0
                            best_video = video
                            best_subtitle_occurrences = []
                            best_score = item['quality_score']
                            break  # Take first video even without subtitles
                     
                    # If we found a suitable video, add it
                    if best_video:
                        try:
                            # Extract video information
                            bvid = best_video.get('bvid', '')
                            aid = best_video.get('aid', 0)
                            title = best_video.get('title', '').replace('<em class="keyword">', '').replace('</em>', '')
                            description = best_video.get('description', '')[:200]
                            pic = best_video.get('pic', '')
                            author = best_video.get('author', '')
                            mid = best_video.get('mid', 0)
                            view = best_video.get('play', 0)
                            danmaku = best_video.get('video_review', 0)
                            reply = best_video.get('review', 0)
                            favorite = best_video.get('favorites', 0)
                            coin = best_video.get('coin', 0)
                            share = best_video.get('share', 0)
                            like = best_video.get('like', 0)
                            pubdate = best_video.get('pubdate', 0)
                            duration_str = best_video.get('duration', '0')
                            # Convert duration string like "5:0" to seconds
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
                            if best_subtitle_occurrences:
                                start_time = min(occ['start'] for occ in best_subtitle_occurrences)
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
                            all_videos.append(video_info.model_dump())
                            logger.info(f"[{word}] Added Bilibili video for phrase '{phrase}': {bvid} (score: {best_score}, start: {start_time}s)")
                        
                        except Exception as e:
                            logger.warning(f"[{word}] Error processing best video: {str(e)}")
                    else:
                        logger.info(f"[{word}] No suitable video found for phrase '{phrase}'")
                except Exception as e:
                    logger.warning(f"[{word}] Error searching Bilibili for phrase '{phrase}': {str(e)}")
                    continue
            
            # Return videos found
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
    
    def _get_bilibili_subtitles(self, bvid: str, phrase: str) -> List[Dict[str, Any]]:
        """Get subtitle timestamps where the exact phrase appears in the Bilibili video"""
        try:
            logger.info(f"[Subtitle] Starting subtitle fetch for {bvid}, looking for phrase: '{phrase}'")
            # Initialize video object with credentials if available
            if self.bilibili_credential:
                video_obj = video.Video(bvid=bvid, credential=self.bilibili_credential)
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
                        import re
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

    def _parse_duration(self, duration_str: str) -> int:
        """Convert duration string to seconds"""
        try:
            parts = duration_str.split(':')
            if len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:  # HH:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except:
            return 0
        return 0

    def _is_educational_video(self, video: dict) -> bool:
        """Check if video has educational content based on tags and title"""
        EDUCATIONAL_TAGS = ['英语学习', '英语', '学习', '教学', '教育', '课程', 
                            'English', 'learning', '口语', '听力']
        AVOID_TAGS = ['舞蹈', 'dance', '音乐', 'music', 'MV', '翻唱', 
                      '街舞', '宅舞', '明星']
        
        tags = video.get('tag', '').lower()
        title = video.get('title', '').lower().replace('<em class="keyword">', '').replace('</em>', '')
        
        has_edu_tags = any(tag.lower() in tags or tag.lower() in title 
                           for tag in EDUCATIONAL_TAGS)
        has_avoid_tags = any(tag.lower() in tags or tag.lower() in title 
                             for tag in AVOID_TAGS)
        
        return has_edu_tags and not has_avoid_tags

    def _has_avoid_tags(self, video: dict) -> bool:
        """Check if video has tags/content to avoid (dance, music, entertainment)"""
        AVOID_TAGS = ['舞蹈', 'dance', '音乐', 'music', 'MV', '翻唱', 
                      '街舞', '宅舞', '明星']
        
        tags = video.get('tag', '').lower()
        title = video.get('title', '').lower().replace('<em class="keyword">', '').replace('</em>', '')
        
        return any(tag.lower() in tags or tag.lower() in title 
                   for tag in AVOID_TAGS)

    def _calculate_quality_score(self, video: dict) -> float:
        """Calculate quality score based on engagement metrics"""
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


# Global instance
dictionary_service = DictionaryService()