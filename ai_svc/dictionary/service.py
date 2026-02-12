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

# Import schemas and prompts
from .schemas import (
    WordSensesDiscovery, EtymologyInfo, WordFamilyInfo, 
    UsageContextInfo, CulturalNotesInfo, DetailedWordSense, FrequencyInfo,
    SenseCoreMetadata, SenseUsageExamples, SenseRelatedWords, SenseUsageNotes
)
from .prompts import (
    get_senses_discovery_prompt, get_etymology_prompt,
    get_word_family_prompt, get_usage_context_prompt,
    get_cultural_notes_prompt, get_frequency_prompt,
    get_sense_core_metadata_prompt, get_sense_usage_examples_prompt,
    get_sense_related_words_prompt, get_sense_usage_notes_prompt
)

load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)


class DictionaryService:
    """Dictionary service using hybrid API + AI architecture"""
    
    DICTIONARY_API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en"
    
    def __init__(self):
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
        
        self.frequency_agent = Agent(
            name="FrequencyAgent",
            model=simple_model,
            description="Estimates word frequency in modern usage",
            use_json_mode=True,
            output_schema=FrequencyInfo
        )
        
        # Parallel execution agents for detailed sense (faster performance)
        # These agents split DetailedWordSense generation into 4 parallel tasks
        # Optimized models with reduced tokens for faster generation
        
        # Agent 1: Core metadata (definition, POS, register, domain, tone) - needs more tokens
        core_metadata_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=300,  # Reduced from 512 for faster inference
            timeout=30.0,
            max_retries=0
        )
        
        # Agent 2: Examples and collocations (3 examples, 3 collocations) - medium tokens
        usage_examples_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=200,  # Reduced from 250 (removed usage_notes)
            timeout=30.0,
            max_retries=0
        )
        
        # Agent 3: Related words (3 synonyms, 3 antonyms, 3 phrases) - medium tokens
        related_words_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=200,  # Generating only 3 items each
            timeout=30.0,
            max_retries=0
        )
        
        # Agent 4: Usage notes (2-3 sentences) - smallest tokens
        usage_notes_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=150,  # Just usage notes guidance
            timeout=30.0,
            max_retries=0
        )
        
        self.sense_core_agent = Agent(
            name="SenseCoreMetadataAgent",
            model=core_metadata_model,
            description="Provides core metadata for word senses",
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
    
    
    def lookup_section(self, word: str, section: str, sense_index: Optional[int] = None, entry_index: Optional[int] = None, index: Optional[int] = None) -> Dict[str, Any]:
        """
        Look up specific section of word data with entry-level awareness
        
        Parameters:
        - word: The word to look up
        - section: Section to fetch
        - sense_index: Sense index within an entry (0-based, for 'detailed_sense')
        - entry_index: Entry index (0-based, for entry-specific sections and 'detailed_sense')
        - index: DEPRECATED - use (entry_index, sense_index) instead
        
        Sections:
        - basic: Returns entry-level structure (no parameters needed)
        - etymology, word_family, usage_context, cultural_notes, frequency: 
            Require entry_index (defaults to 0)
        - detailed_sense: Requires BOTH entry_index AND sense_index
        
        Examples:
        - {"word": "scrub", "section": "basic"}
        - {"word": "scrub", "section": "etymology", "entry_index": 1}
        - {"word": "scrub", "section": "detailed_sense", "entry_index": 1, "sense_index": 0}  # Entry 1, first sense
        """
        try:
            start_time = time.time()
            
            valid_sections = [
                'etymology', 'word_family', 'usage_context', 
                'cultural_notes', 'frequency', 'detailed_sense', 'basic'
            ]
            
            if section not in valid_sections:
                return {
                    "error": f"Invalid section '{section}'. Valid sections: {', '.join(valid_sections)}",
                    "success": False
                }
            
            if section == 'detailed_sense':
                if index is not None:
                    logger.warning(f"[{word}] DEPRECATED: 'index' parameter is deprecated. Use 'entry_index' + 'sense_index' instead.")
                    result = self._fetch_single_detailed_sense_flat(word, index)
                elif entry_index is not None and sense_index is not None:
                    result = self._fetch_single_detailed_sense_2d(word, entry_index, sense_index)
                else:
                    return {
                        "error": "detailed_sense requires both 'entry_index' and 'sense_index' (or deprecated 'index')",
                        "success": False
                    }
                
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
            
            entry_level_sections = ['etymology', 'word_family', 'usage_context', 'cultural_notes', 'frequency']
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
        Fetch basic word info with entry-level structure
        
        Returns:
        {
            "headword": "scrub",
            "pronunciation": "...",
            "total_entries": 2,
            "entries": [
                {
                    "entry_index": 0,
                    "meanings_summary": [
                        {"part_of_speech": "noun", "definition_count": 6},
                        {"part_of_speech": "adjective", "definition_count": 1}
                    ],
                    "total_senses": 7
                },
                {
                    "entry_index": 1,
                    "meanings_summary": [
                        {"part_of_speech": "noun", "definition_count": 7},
                        {"part_of_speech": "verb", "definition_count": 7}
                    ],
                    "total_senses": 14
                }
            ],
            "total_senses": 21,
            "data_source": "hybrid_api_ai",
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
                    
                    meanings_summary.append({
                        "part_of_speech": pos,
                        "definition_count": def_count
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
                "data_source": "hybrid_api_ai",
                "execution_time": time.time() - start_time,
                "success": True
            }
        else:
            logger.info(f"[{word}] Basic data: Using AI (ai_only) - API failed: {api_result.get('error', 'unknown')}")
            discovery_result = self._discover_word_senses(word)
            if not discovery_result.get("success"):
                return discovery_result
            
            discovery_data = discovery_result["discovery_data"]
            senses = discovery_data.get("senses", [])
            ai_ipa = discovery_data.get("pronunciation", "")
            
            return {
                "headword": word,
                "total_entries": 1,
                "entries": [{
                    "entry_index": 0,
                    "pronunciation": "",
                    "ipa": ai_ipa,
                    "meanings_summary": [{"part_of_speech": "mixed", "definition_count": len(senses)}],
                    "total_senses": len(senses)
                }],
                "total_senses": len(senses),
                "data_source": "ai_only",
                "execution_time": time.time() - start_time,
                "success": True
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
            'frequency': self._fetch_frequency
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
                logger.info(f"[{word}] Detailed sense (entry {entry_index}, sense {sense_index}): Using AI only - API failed")
                discovery_result = self._discover_word_senses(word)
                if not discovery_result.get("success"):
                    return discovery_result
                
                discovery_data = discovery_result["discovery_data"]
                senses = discovery_data.get("senses", [])
                
                if entry_index != 0:
                    return {
                        "error": f"AI-only mode has single entry. Requested entry_index={entry_index}, but only entry 0 exists",
                        "success": False
                    }
                
                if sense_index < 0 or sense_index >= len(senses):
                    return {
                        "error": f"Invalid sense_index {sense_index}. Entry 0 has {len(senses)} senses (0-{len(senses)-1})",
                        "success": False
                    }
                
                sense_basic = senses[sense_index]
                sense_result = self._fetch_detailed_sense(
                    word, sense_index, sense_basic["definition"]
                )
                
                if sense_result.get("success"):
                    return {
                        "detailed_sense": sense_result["sense_detail"],
                        "entry_index": 0,
                        "sense_index": sense_index,
                        "success": True
                    }
                else:
                    return sense_result
                
        except Exception as e:
            return {
                "error": str(e),
                "success": False
            }
    
    def _fetch_single_detailed_sense_flat(self, word: str, flat_index: int) -> Dict[str, Any]:
        """
        DEPRECATED: Fetch a single detailed sense by flat index across all entries
        
        Sense indexing is flat: sense #7 might be in entry 1, not entry 0
        Use _fetch_single_detailed_sense_2d instead
        """
        try:
            api_result = self._fetch_from_api(word)
            
            if api_result.get("success"):
                logger.info(f"[{word}] Detailed sense #{flat_index}: Using API basic data + AI enhancement (hybrid)")
                entries = api_result["entries"]
                
                current_index = 0
                for entry_idx, entry in enumerate(entries):
                    meanings = entry.get("meanings", [])
                    
                    for meaning in meanings:
                        part_of_speech = meaning.get("partOfSpeech", "")
                        definitions = meaning.get("definitions", [])
                        meaning_synonyms = meaning.get("synonyms", [])
                        meaning_antonyms = meaning.get("antonyms", [])
                        
                        for def_obj in definitions:
                            if current_index == flat_index:
                                definition = def_obj.get("definition", "")
                                example = def_obj.get("example", "")
                                def_synonyms = def_obj.get("synonyms", []) or meaning_synonyms
                                def_antonyms = def_obj.get("antonyms", []) or meaning_antonyms
                                
                                sense_result = self._fetch_enhanced_sense(
                                    word, flat_index, part_of_speech,
                                    [definition], def_synonyms, def_antonyms,
                                    [example] if example else []
                                )
                                
                                if sense_result.get("success"):
                                    return {
                                        "detailed_sense": sense_result["sense_detail"],
                                        "entry_index": entry_idx,
                                        "success": True
                                    }
                                else:
                                    return sense_result
                            
                            current_index += 1
                
                total_senses = current_index
                return {
                    "error": f"Invalid flat_index {flat_index}. Word has {total_senses} senses (0-{total_senses-1})",
                    "success": False
                }
            else:
                logger.info(f"[{word}] Detailed sense #{flat_index}: Using AI only - API failed: {api_result.get('error', 'unknown')}")
                discovery_result = self._discover_word_senses(word)
                if not discovery_result.get("success"):
                    return discovery_result
                
                discovery_data = discovery_result["discovery_data"]
                senses = discovery_data.get("senses", [])
                
                if flat_index < 0 or flat_index >= len(senses):
                    return {
                        "error": f"Invalid flat_index {flat_index}. Word has {len(senses)} senses (0-{len(senses)-1})",
                        "success": False
                    }
                
                sense_basic = senses[flat_index]
                sense_result = self._fetch_detailed_sense(
                    word, flat_index, sense_basic["definition"]
                )
                
                if sense_result.get("success"):
                    return {
                        "detailed_sense": sense_result["sense_detail"],
                        "entry_index": 0,
                        "success": True
                    }
                else:
                    return sense_result
                
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
        """Fetch AI-enhanced analysis for a sense using parallel execution (API already provides basics)"""
        try:
            basic_definition = api_definitions[0] if api_definitions else ""
            
            # Execute 4 agents in parallel for faster performance
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                # Submit all 4 tasks
                future_core = executor.submit(
                    self._fetch_sense_core_metadata, 
                    word, sense_index, basic_definition, part_of_speech
                )
                future_usage = executor.submit(
                    self._fetch_sense_usage_examples,
                    word, sense_index, basic_definition, api_examples or []
                )
                future_related = executor.submit(
                    self._fetch_sense_related_words,
                    word, sense_index, basic_definition, api_synonyms or [], api_antonyms or []
                )
                future_notes = executor.submit(
                    self._fetch_sense_usage_notes,
                    word, sense_index, basic_definition
                )
                
                # Wait for all tasks to complete (with timeout)
                done, not_done = concurrent.futures.wait(
                    [future_core, future_usage, future_related, future_notes],
                    timeout=45.0,
                    return_when=concurrent.futures.ALL_COMPLETED
                )
                
                # Cancel any incomplete tasks
                for future in not_done:
                    future.cancel()
                
                # Get results
                core_result = self._get_future_result(future_core, "core_metadata")
                usage_result = self._get_future_result(future_usage, "usage_examples")
                related_result = self._get_future_result(future_related, "related_words")
                notes_result = self._get_future_result(future_notes, "usage_notes")
            
            # Check if all succeeded
            if not all([
                core_result and core_result.get("success"),
                usage_result and usage_result.get("success"),
                related_result and related_result.get("success"),
                notes_result and notes_result.get("success")
            ]):
                errors = []
                if not core_result or not core_result.get("success"):
                    errors.append(f"core: {core_result.get('error') if core_result else 'timeout'}")
                if not usage_result or not usage_result.get("success"):
                    errors.append(f"usage: {usage_result.get('error') if usage_result else 'timeout'}")
                if not related_result or not related_result.get("success"):
                    errors.append(f"related: {related_result.get('error') if related_result else 'timeout'}")
                if not notes_result or not notes_result.get("success"):
                    errors.append(f"notes: {notes_result.get('error') if notes_result else 'timeout'}")
                
                return {
                    "success": False,
                    "error": f"Parallel execution failed: {', '.join(errors)}"
                }
            
            # At this point, all results are successful (type assertion for type checker)
            assert core_result and "data" in core_result
            assert usage_result and "data" in usage_result
            assert related_result and "data" in related_result
            assert notes_result and "data" in notes_result
            
            # Merge results into DetailedWordSense format
            sense_detail = {
                # From core metadata
                "definition": core_result["data"]["definition"],
                "part_of_speech": core_result["data"]["part_of_speech"],
                "usage_register": core_result["data"]["usage_register"],
                "domain": core_result["data"]["domain"],
                "tone": core_result["data"]["tone"],
                # From usage notes
                "usage_notes": notes_result["data"]["usage_notes"],
                # From usage examples
                "examples": usage_result["data"]["examples"],
                "collocations": usage_result["data"]["collocations"],
                # From related words
                "synonyms": related_result["data"]["synonyms"],
                "antonyms": related_result["data"]["antonyms"],
                "word_specific_phrases": related_result["data"]["word_specific_phrases"],
            }
            
            # Merge API data if AI didn't provide it
            if not sense_detail.get("synonyms") and api_synonyms:
                sense_detail["synonyms"] = api_synonyms
            if not sense_detail.get("antonyms") and api_antonyms:
                sense_detail["antonyms"] = api_antonyms
            
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
        """Fetch core metadata for a sense (parallel execution component)"""
        try:
            prompt = get_sense_core_metadata_prompt(word, sense_index, basic_definition)
            response = self.sense_core_agent.run(prompt)
            
            if isinstance(response.content, SenseCoreMetadata):
                data = response.content.model_dump()
                # Override part_of_speech if provided by API
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
                                   api_examples: Optional[List[str]] = None) -> Dict[str, Any]:
        """Fetch usage notes and examples for a sense (parallel execution component)"""
        try:
            prompt = get_sense_usage_examples_prompt(word, sense_index, basic_definition, api_examples)
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
                                  api_antonyms: Optional[List[str]] = None) -> Dict[str, Any]:
        """Fetch related words and phrases for a sense (parallel execution component)"""
        try:
            prompt = get_sense_related_words_prompt(word, sense_index, basic_definition, 
                                                   api_synonyms, api_antonyms)
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
    
    
    # Keep original AI-only methods for fallback
    def _discover_word_senses(self, word: str) -> Dict[str, Any]:
        """Phase 1: Discover all word senses (fallback only)"""
        try:
            # Create discovery agent on-demand for fallback
            deepseek_model = DeepSeek(
                id="deepseek-chat",
                api_key=os.getenv('DEEPSEEK_API_KEY'),
                temperature=0,
                max_tokens=1024,
                timeout=45.0,
                max_retries=0
            )
            
            senses_discovery_agent = Agent(
                name="SensesDiscoveryAgent",
                model=deepseek_model,
                description="Discovers all word senses and basic information",
                use_json_mode=True,
                output_schema=WordSensesDiscovery
            )
            
            prompt = get_senses_discovery_prompt(word)
            response = senses_discovery_agent.run(prompt)
            
            if isinstance(response.content, WordSensesDiscovery):
                discovery_data = response.content.model_dump()
                # AI fallback: pronunciation field contains IPA string
                return {
                    "success": True,
                    "discovery_data": discovery_data
                }
            else:
                error_msg = "Failed to parse word senses discovery"
                if hasattr(response, 'content') and response.content:
                    if isinstance(response.content, dict) and 'error' in response.content:
                        error_msg = f"Validation error: {response.content['error']}"
                    elif isinstance(response.content, str):
                        error_msg = f"Parse error: {response.content[:100]}..."
                
                return {
                    "success": False,
                    "error": error_msg,
                    "headword": word
                }
                
        except Exception as e:
            error_msg = str(e)
            if "tone" in error_msg.lower() and "enum" in error_msg.lower():
                error_msg = "Invalid tone value returned. Tone must be one of: positive, negative, neutral, humorous, derogatory, pejorative, approving"
            
            return {
                "success": False,
                "error": error_msg,
                "headword": word
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
    
    def _fetch_detailed_sense(self, word: str, sense_index: int, basic_definition: str) -> Dict[str, Any]:
        """Fetch detailed analysis for a specific sense using parallel execution (AI-only fallback)"""
        try:
            # Execute 4 agents in parallel for faster performance
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                # Submit all 4 tasks
                future_core = executor.submit(
                    self._fetch_sense_core_metadata, 
                    word, sense_index, basic_definition, ""  # No part_of_speech from API
                )
                future_usage = executor.submit(
                    self._fetch_sense_usage_examples,
                    word, sense_index, basic_definition, None  # No API examples
                )
                future_related = executor.submit(
                    self._fetch_sense_related_words,
                    word, sense_index, basic_definition, None, None  # No API synonyms/antonyms
                )
                future_notes = executor.submit(
                    self._fetch_sense_usage_notes,
                    word, sense_index, basic_definition
                )
                
                # Wait for all tasks to complete (with timeout)
                done, not_done = concurrent.futures.wait(
                    [future_core, future_usage, future_related, future_notes],
                    timeout=45.0,
                    return_when=concurrent.futures.ALL_COMPLETED
                )
                
                # Cancel any incomplete tasks
                for future in not_done:
                    future.cancel()
                
                # Get results
                core_result = self._get_future_result(future_core, "core_metadata")
                usage_result = self._get_future_result(future_usage, "usage_examples")
                related_result = self._get_future_result(future_related, "related_words")
                notes_result = self._get_future_result(future_notes, "usage_notes")
            
            # Check if all succeeded
            if not all([
                core_result and core_result.get("success"),
                usage_result and usage_result.get("success"),
                related_result and related_result.get("success"),
                notes_result and notes_result.get("success")
            ]):
                errors = []
                if not core_result or not core_result.get("success"):
                    errors.append(f"core: {core_result.get('error') if core_result else 'timeout'}")
                if not usage_result or not usage_result.get("success"):
                    errors.append(f"usage: {usage_result.get('error') if usage_result else 'timeout'}")
                if not related_result or not related_result.get("success"):
                    errors.append(f"related: {related_result.get('error') if related_result else 'timeout'}")
                if not notes_result or not notes_result.get("success"):
                    errors.append(f"notes: {notes_result.get('error') if notes_result else 'timeout'}")
                
                return {
                    "success": False,
                    "error": f"Parallel execution failed: {', '.join(errors)}"
                }
            
            # At this point, all results are successful (type assertion for type checker)
            assert core_result and "data" in core_result
            assert usage_result and "data" in usage_result
            assert related_result and "data" in related_result
            assert notes_result and "data" in notes_result
            
            # Merge results into DetailedWordSense format
            sense_detail = {
                # From core metadata
                "definition": core_result["data"]["definition"],
                "part_of_speech": core_result["data"]["part_of_speech"],
                "usage_register": core_result["data"]["usage_register"],
                "domain": core_result["data"]["domain"],
                "tone": core_result["data"]["tone"],
                # From usage notes
                "usage_notes": notes_result["data"]["usage_notes"],
                # From usage examples
                "examples": usage_result["data"]["examples"],
                "collocations": usage_result["data"]["collocations"],
                # From related words
                "synonyms": related_result["data"]["synonyms"],
                "antonyms": related_result["data"]["antonyms"],
                "word_specific_phrases": related_result["data"]["word_specific_phrases"],
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
    
    def _get_future_result(self, future, task_name: str) -> Optional[Dict[str, Any]]:
        """Safely get result from a future"""
        try:
            # No additional timeout - already handled by wait() with 60s
            if future.cancelled():
                print(f"Warning: Task {task_name} was cancelled")
                return {
                    "success": False,
                    "error": f"Task {task_name} was cancelled"
                }
            
            return future.result(timeout=0.1)  # Should be ready already
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
    



# Global instance
dictionary_service = DictionaryService()