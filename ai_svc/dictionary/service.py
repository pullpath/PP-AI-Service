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
    UsageContextInfo, CulturalNotesInfo, DetailedWordSense, FrequencyInfo
)
from .prompts import (
    get_senses_discovery_prompt, get_etymology_prompt,
    get_word_family_prompt, get_usage_context_prompt,
    get_cultural_notes_prompt, get_detailed_sense_prompt,
    get_frequency_prompt, get_enhanced_sense_prompt
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
    
    def lookup_word(self, word: str) -> Dict[str, Any]:
        """
        Main dictionary lookup interface
        Uses hybrid API + AI architecture:
        1. Get discovery data (from API or AI fallback)
        2. Use AI for enhanced/missing information (frequency + detailed analysis)
        """
        try:
            start_time = time.time()
            
            # Step 1: Get discovery data (try API first, fallback to AI)
            print(f"Step 1: Fetching discovery data for '{word}'...")
            api_result = self._fetch_from_api(word)
            
            step_1_time = time.time()
            
            if api_result.get("success"):
                # API success: convert to discovery format
                print(f"Time spent on API fetch: {step_1_time - start_time:.2f}s")
                discovery_data = self._convert_api_to_discovery(word, api_result["data"])
                print(f"Converted {len(discovery_data['senses'])} senses from API to WordSensesDiscovery format")
            else:
                # API failed: use AI discovery
                print(f"API fetch failed, using AI discovery...")
                discovery_result = self._discover_word_senses(word)
                if not discovery_result.get("success"):
                    return discovery_result
                discovery_data = discovery_result["discovery_data"]
                print(f"AI discovered {len(discovery_data['senses'])} senses")
                print(f"Time spent on AI discovery: {step_1_time - start_time:.2f}s")
            
            total_senses = len(discovery_data["senses"])
            
            # Step 2: Parallel fetch of AI-enhanced information (same for both paths)
            print(f"Step 2: Fetching AI-enhanced information...")
            enhanced_result = self._fetch_detailed_info_parallel(word, discovery_data)
            
            step_2_time = time.time()
            print(f"Time spent on AI enhancement: {step_2_time - step_1_time:.2f}s")
            
            if not enhanced_result.get("success"):
                return enhanced_result
            
            # Combine results (same for both paths)
            final_result = self._combine_results(
                word, discovery_data, enhanced_result, start_time, total_senses
            )
            
            return final_result
            
        except Exception as e:
            return {
                "headword": word,
                "error": str(e),
                "success": False
            }
    
    def lookup_section(self, word: str, section: Optional[str] = None) -> Dict[str, Any]:
        """
        Look up full word data or specific section
        If section is None, returns full lookup (same as lookup_word)
        If section is provided, returns full data structure with only that section populated
        """
        # If no section specified, do full lookup
        if section is None:
            return self.lookup_word(word)
        
        try:
            start_time = time.time()
            
            # Validate section
            valid_sections = [
                'etymology', 'word_family', 'usage_context', 
                'cultural_notes', 'frequency', 'detailed_senses', 'basic'
            ]
            
            if section not in valid_sections:
                return {
                    "error": f"Invalid section '{section}'. Valid sections: {', '.join(valid_sections)}",
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
            
            # For AI sections, call the appropriate method
            section_method_map = {
                'etymology': self._fetch_etymology,
                'word_family': self._fetch_word_family,
                'usage_context': self._fetch_usage_context,
                'cultural_notes': self._fetch_cultural_notes,
                'frequency': self._fetch_frequency,
                'detailed_senses': self._fetch_all_detailed_senses
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
    
    def _fetch_all_detailed_senses(self, word: str) -> Dict[str, Any]:
        """Fetch all detailed senses for a word"""
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
            
            # Fetch detailed senses
            meanings = discovery_data.get("api_raw_meanings", [])
            senses = discovery_data.get("senses", [])
            is_from_api = bool(meanings)
            
            sense_futures = []
            
            if is_from_api:
                # API path: process each definition
                with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                    sense_index = 0
                    for meaning in meanings:
                        part_of_speech = meaning.get("partOfSpeech", "")
                        definitions = meaning.get("definitions", [])
                        meaning_synonyms = meaning.get("synonyms", [])
                        meaning_antonyms = meaning.get("antonyms", [])
                        
                        for def_obj in definitions:
                            definition = def_obj.get("definition", "")
                            example = def_obj.get("example", "")
                            def_synonyms = def_obj.get("synonyms", []) or meaning_synonyms
                            def_antonyms = def_obj.get("antonyms", []) or meaning_antonyms
                            
                            future = executor.submit(
                                self._fetch_enhanced_sense,
                                word, sense_index, part_of_speech, 
                                [definition], def_synonyms, def_antonyms, 
                                [example] if example else []
                            )
                            sense_futures.append(future)
                            sense_index += 1
                    
                    done, not_done = concurrent.futures.wait(sense_futures, timeout=60)
                    
                    detailed_senses = []
                    for i, future in enumerate(sense_futures):
                        sense_result = self._get_future_result(future, f"sense_{i}")
                        if sense_result and sense_result.get("success"):
                            detailed_senses.append(sense_result["sense_detail"])
            else:
                # AI path: process basic definitions
                with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                    for i, sense_basic in enumerate(senses):
                        future = executor.submit(
                            self._fetch_detailed_sense,
                            word, i, sense_basic["definition"]
                        )
                        sense_futures.append(future)
                    
                    done, not_done = concurrent.futures.wait(sense_futures, timeout=60)
                    
                    detailed_senses = []
                    for i, future in enumerate(sense_futures):
                        sense_result = self._get_future_result(future, f"sense_{i}")
                        if sense_result and sense_result.get("success"):
                            detailed_senses.append(sense_result["sense_detail"])
            
            return {
                "detailed_senses": detailed_senses,
                "success": True
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
    

    def _fetch_detailed_info_parallel(self, word: str, discovery_data: Dict[str, Any]) -> Dict[str, Any]:
        """Unified parallel fetch: works for both API and AI discovery paths"""
        try:
            # Detect source: API (has api_raw_meanings) vs AI (only has senses)
            meanings = discovery_data.get("api_raw_meanings", [])
            senses = discovery_data.get("senses", [])
            is_from_api = bool(meanings)
            
            # Calculate optimal thread count
            # For API: count individual definitions across all meanings
            if is_from_api:
                sense_count = sum(len(m.get("definitions", [])) for m in meanings)
            else:
                sense_count = len(senses)
            # 5 base tasks: etymology, word_family, usage_context, cultural_notes, frequency
            max_threads = min(15, 5 + sense_count)  # Increased max to handle more senses
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                # Submit granular info tasks (always needed)
                etymology_future = executor.submit(self._fetch_etymology, word)
                word_family_future = executor.submit(self._fetch_word_family, word)
                usage_context_future = executor.submit(self._fetch_usage_context, word)
                cultural_notes_future = executor.submit(self._fetch_cultural_notes, word)
                
                # Submit frequency detection (always needed - not in discovery_data anymore)
                frequency_future = executor.submit(self._fetch_frequency, word)
                
                # Submit sense analysis
                sense_futures = []
                if is_from_api:
                    # API path: enhance API data with AI analysis
                    # Process each individual definition, not just meanings groups
                    sense_index = 0
                    for meaning in meanings:
                        part_of_speech = meaning.get("partOfSpeech", "")
                        definitions = meaning.get("definitions", [])
                        meaning_synonyms = meaning.get("synonyms", [])
                        meaning_antonyms = meaning.get("antonyms", [])
                        
                        for def_obj in definitions:
                            definition = def_obj.get("definition", "")
                            example = def_obj.get("example", "")
                            
                            # Get definition-specific synonyms/antonyms, fallback to meaning-level
                            def_synonyms = def_obj.get("synonyms", []) or meaning_synonyms
                            def_antonyms = def_obj.get("antonyms", []) or meaning_antonyms
                            
                            future = executor.submit(
                                self._fetch_enhanced_sense,
                                word, sense_index, part_of_speech, 
                                [definition],  # Single definition
                                def_synonyms, def_antonyms, 
                                [example] if example else []
                            )
                            sense_futures.append(future)
                            sense_index += 1
                else:
                    # AI path: detailed analysis from basic definitions
                    for i, sense_basic in enumerate(senses):
                        future = executor.submit(
                            self._fetch_detailed_sense,
                            word, i, sense_basic["definition"]
                        )
                        sense_futures.append(future)
                
                # Wait for all tasks with progress tracking
                all_futures = [
                    etymology_future, word_family_future,
                    usage_context_future, cultural_notes_future
                ] + sense_futures
                if frequency_future:
                    all_futures.append(frequency_future)
                
                # Wait with timeout (60s total for all parallel tasks)
                done, not_done = concurrent.futures.wait(all_futures, timeout=60)
                
                # Log any tasks that didn't complete
                if not_done:
                    print(f"Warning: {len(not_done)} tasks did not complete within 60s timeout")
                    for future in not_done:
                        future.cancel()
                
                # Collect results
                results = {
                    "etymology": self._get_future_result(etymology_future, "etymology"),
                    "word_family": self._get_future_result(word_family_future, "word_family"),
                    "usage_context": self._get_future_result(usage_context_future, "usage_context"),
                    "cultural_notes": self._get_future_result(cultural_notes_future, "cultural_notes"),
                    "frequency": None,
                    "detailed_senses": []  # Use same key for both paths
                }
                
                # Get frequency (always fetched from AI)
                results["frequency"] = self._get_future_result(frequency_future, "frequency")
                
                # Collect sense details
                for i, future in enumerate(sense_futures):
                    sense_result = self._get_future_result(future, f"sense_{i}")
                    if sense_result and sense_result.get("success"):
                        results["detailed_senses"].append(sense_result["sense_detail"])
                
                # Handle failures gracefully (allow partial success)
                if not results["etymology"] or not results["etymology"].get("success"):
                    print("Warning: Failed to fetch etymology, continuing...")
                    results["etymology"] = {"success": True, "etymology": {"etymology": "", "root_analysis": ""}}
                
                if not results["word_family"] or not results["word_family"].get("success"):
                    print("Warning: Failed to fetch word family, continuing...")
                    results["word_family"] = {"success": True, "word_family": {"word_family": []}}
                
                if not results["usage_context"] or not results["usage_context"].get("success"):
                    print("Warning: Failed to fetch usage context, continuing...")
                    results["usage_context"] = {"success": True, "usage_context": {"modern_relevance": "", "common_confusions": [], "regional_variations": []}}
                
                if not results["cultural_notes"] or not results["cultural_notes"].get("success"):
                    print("Warning: Failed to fetch cultural notes, continuing...")
                    results["cultural_notes"] = {"success": True, "cultural_notes": {"notes": ""}}
                
                if not results["frequency"] or not results["frequency"].get("success"):
                    print("Warning: Failed to fetch frequency, using default 'common'")
                    results["frequency"] = {"success": True, "frequency": "common"}
                
                return {
                    "success": True,
                    "results": results
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "headword": word
            }
    
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
        """Fetch AI-enhanced analysis for a sense (API already provides basics)"""
        try:
            # Use prompt generator with API data
            prompt = get_enhanced_sense_prompt(
                word, sense_index, part_of_speech,
                api_definitions, api_synonyms or [], api_antonyms or [], api_examples or []
            )
            
            response = self.detailed_sense_agent.run(prompt)
            
            if isinstance(response.content, DetailedWordSense):
                sense_detail = response.content.model_dump()
                
                # Merge API data with AI enhancements
                definition = api_definitions[0] if api_definitions else ""
                sense_detail["definition"] = definition
                if not sense_detail.get("synonyms") and api_synonyms:
                    sense_detail["synonyms"] = api_synonyms
                if not sense_detail.get("antonyms") and api_antonyms:
                    sense_detail["antonyms"] = api_antonyms
                
                return {
                    "success": True,
                    "sense_index": sense_index,
                    "sense_detail": sense_detail
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to parse enhanced sense {sense_index}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _combine_results(self, word: str, discovery_data: Dict[str, Any], 
                        enhanced_result: Dict[str, Any], start_time: float, 
                        total_senses: int) -> Dict[str, Any]:
        """Combine discovery data with AI enhancements (unified for API and fallback paths)"""
        results = enhanced_result["results"]
        
        # Get frequency (from AI results only)
        frequency = results.get("frequency", {}).get("frequency", "common")
        
        # Determine data source
        data_source = "hybrid_api_ai" if "api_raw_meanings" in discovery_data else "ai_only"
        
        # Get pronunciation (audio URL or IPA string)
        pronunciation = discovery_data.get("pronunciation", "")
        
        # Create final result
        final_result = {
            "headword": word,
            "pronunciation": pronunciation,  # Audio URL (API) or IPA string (AI fallback)
            "frequency": frequency,
            "data_source": data_source,
            
            # AI-enhanced information
            "etymology": results["etymology"]["etymology"],
            "word_family": results["word_family"]["word_family"],
            "usage_context": results["usage_context"]["usage_context"],
            "cultural_notes": results["cultural_notes"]["cultural_notes"],
            
            # Detailed senses (same key for both API and AI paths)
            "detailed_senses": results["detailed_senses"],
            
            # Metadata
            "timestamp": time.time(),
            "total_senses": total_senses,
            "parallel_execution": True,
            "execution_time": time.time() - start_time,
            "success": True
        }
        
        return final_result
    
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
        """Fetch detailed analysis for a specific sense (fallback only)"""
        try:
            prompt = get_detailed_sense_prompt(word, sense_index, basic_definition)
            response = self.detailed_sense_agent.run(prompt)
            
            if isinstance(response.content, DetailedWordSense):
                return {
                    "success": True,
                    "sense_index": sense_index,
                    "sense_detail": response.content.model_dump()
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to parse detailed sense {sense_index}"
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