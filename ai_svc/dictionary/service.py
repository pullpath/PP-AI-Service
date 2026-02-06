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
    get_cultural_notes_prompt, get_detailed_sense_prompt,
    get_frequency_prompt, get_enhanced_sense_prompt,
    get_sense_core_metadata_prompt, get_sense_usage_examples_prompt,
    get_sense_related_words_prompt, get_sense_usage_notes_prompt
)

load_dotenv()


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
    
    
    def lookup_section(self, word: str, section: str, index: Optional[int] = None) -> Dict[str, Any]:
        """
        Look up specific section of word data
        All requests must specify a section - no full lookup supported
        
        For 'detailed_sense' section, index parameter is required to specify which sense
        """
        try:
            start_time = time.time()
            
            # Validate section
            valid_sections = [
                'etymology', 'word_family', 'usage_context', 
                'cultural_notes', 'frequency', 'detailed_sense', 'basic'
            ]
            
            if section not in valid_sections:
                return {
                    "error": f"Invalid section '{section}'. Valid sections: {', '.join(valid_sections)}",
                    "success": False
                }
            
            # Special validation for detailed_sense
            if section == 'detailed_sense' and index is None:
                return {
                    "error": "index is required when requesting 'detailed_sense'",
                    "success": False
                }
            
            # Handle basic specially (doesn't require AI)
            if section == 'basic':
                api_result = self._fetch_from_api(word)
                
                if api_result.get("success"):
                    discovery_data = self._convert_api_to_discovery(word, api_result["data"])
                    data_source = "hybrid_api_ai"
                else:
                    discovery_result = self._discover_word_senses(word)
                    if not discovery_result.get("success"):
                        return discovery_result
                    discovery_data = discovery_result["discovery_data"]
                    data_source = "ai_only"
                
                return {
                    "headword": word,
                    "pronunciation": discovery_data.get("pronunciation", ""),
                    "total_senses": len(discovery_data.get("senses", [])),
                    "data_source": data_source,
                    "execution_time": time.time() - start_time,
                    "success": True
                }
            
            # Handle individual detailed_sense specially
            if section == 'detailed_sense':
                # index is guaranteed to be int at this point due to validation above
                assert index is not None, "index should have been validated"
                result = self._fetch_single_detailed_sense(word, index)
                
                if not result.get("success"):
                    return result
                
                return {
                    "headword": word,
                    "detailed_sense": result["detailed_sense"],
                    "execution_time": time.time() - start_time,
                    "success": True
                }
            
            # For AI sections, call the appropriate method
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
            
            result = method(word)
            
            if not result.get("success"):
                return result
            
            # Build response with same structure as full lookup
            # This allows frontend to merge section data easily
            response = {
                "headword": word,
                section: result[section],  # Use same property name as full lookup
                "execution_time": time.time() - start_time,
                "success": True
            }
            
            return response
                
        except Exception as e:
            return {
                "headword": word,
                "error": str(e),
                "success": False
            }
    
    def _fetch_single_detailed_sense(self, word: str, sense_index: int) -> Dict[str, Any]:
        """Fetch a single detailed sense by index"""
        try:
            # Get discovery data first
            api_result = self._fetch_from_api(word)
            
            if api_result.get("success"):
                discovery_data = self._convert_api_to_discovery(word, api_result["data"])
            else:
                discovery_result = self._discover_word_senses(word)
                if not discovery_result.get("success"):
                    return discovery_result
                discovery_data = discovery_result["discovery_data"]
            
            # Determine which path to use
            meanings = discovery_data.get("api_raw_meanings", [])
            senses = discovery_data.get("senses", [])
            is_from_api = bool(meanings)
            
            # Validate sense_index
            if is_from_api:
                # Count total definitions across all meanings
                total_senses = sum(len(m.get("definitions", [])) for m in meanings)
            else:
                total_senses = len(senses)
            
            if sense_index < 0 or sense_index >= total_senses:
                return {
                    "error": f"Invalid sense_index {sense_index}. Word has {total_senses} senses (0-{total_senses-1})",
                    "success": False
                }
            
            # Fetch the specific sense
            if is_from_api:
                # API path: find the definition at sense_index
                current_index = 0
                for meaning in meanings:
                    part_of_speech = meaning.get("partOfSpeech", "")
                    definitions = meaning.get("definitions", [])
                    meaning_synonyms = meaning.get("synonyms", [])
                    meaning_antonyms = meaning.get("antonyms", [])
                    
                    for def_obj in definitions:
                        if current_index == sense_index:
                            # Found the target sense
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
                                    "success": True
                                }
                            else:
                                return sense_result
                        
                        current_index += 1
            else:
                # AI path: direct index lookup
                sense_basic = senses[sense_index]
                sense_result = self._fetch_detailed_sense(
                    word, sense_index, sense_basic["definition"]
                )
                
                if sense_result.get("success"):
                    return {
                        "detailed_sense": sense_result["sense_detail"],
                        "success": True
                    }
                else:
                    return sense_result
            
            return {
                "error": f"Failed to fetch sense {sense_index}",
                "success": False
            }
                
        except Exception as e:
            return {
                "error": str(e),
                "success": False
            }
    
    def _fetch_from_api(self, word: str) -> Dict[str, Any]:
        """Fetch basic dictionary data from free API"""
        try:
            url = f"{self.DICTIONARY_API_BASE}/{word}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    # Get first entry
                    entry = data[0]
                    return {
                        "success": True,
                        "data": entry
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
    
    def _convert_api_to_discovery(self, word: str, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert API response to WordSensesDiscovery schema format"""
        try:
            # Extract audio URL from phonetics
            # Priority: UK audio > US audio > any other audio
            phonetics = api_data.get("phonetics", [])
            pronunciation = ""
            
            # First pass: look for UK audio
            for p in phonetics:
                audio = p.get("audio", "")
                if audio and ("-uk.mp3" in audio.lower() or "-uk-" in audio.lower()):
                    pronunciation = audio
                    break
            
            # Second pass: look for US audio if UK not found
            if not pronunciation:
                for p in phonetics:
                    audio = p.get("audio", "")
                    if audio and ("-us.mp3" in audio.lower() or "-us-" in audio.lower()):
                        pronunciation = audio
                        break
            
            # Third pass: take any audio URL
            if not pronunciation:
                for p in phonetics:
                    audio = p.get("audio", "")
                    if audio:
                        pronunciation = audio
                        break
            
            # Fallback: use IPA if no audio found
            if not pronunciation:
                # Try to get IPA from phonetics with text
                for p in phonetics:
                    if p.get("text"):
                        pronunciation = p["text"]
                        break
                
                # Last resort: phonetic field
                if not pronunciation:
                    pronunciation = api_data.get("phonetic", "")
            
            # Convert meanings to senses (WordSenseBasic format)
            senses = []
            meanings = api_data.get("meanings", [])
            sense_index = 0
            
            for meaning in meanings:
                definitions = meaning.get("definitions", [])
                for def_obj in definitions:
                    definition = def_obj.get("definition", "")
                    if definition:
                        senses.append({
                            "definition": definition,
                            "sense_index": sense_index
                        })
                        sense_index += 1
            
            # Create discovery data
            discovery_data = {
                "headword": word,
                "pronunciation": pronunciation,  # Audio URL (preferred) or IPA string (fallback)
                "senses": senses,
                "api_raw_meanings": meanings  # Keep original for detailed processing
            }
            
            return discovery_data
            
        except Exception as e:
            print(f"Error converting API response: {str(e)}")
            raise
    

    
    def _fetch_frequency(self, word: str) -> Dict[str, Any]:
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
    

    
    def _fetch_etymology(self, word: str) -> Dict[str, Any]:
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
    
    def _fetch_word_family(self, word: str) -> Dict[str, Any]:
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
    
    def _fetch_usage_context(self, word: str) -> Dict[str, Any]:
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
    
    def _fetch_cultural_notes(self, word: str) -> Dict[str, Any]:
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