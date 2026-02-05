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
            # Extract pronunciation (IPA format preferred) and audio URL
            phonetics = api_data.get("phonetics", [])
            pronunciation = ""
            audio_url = ""
            
            for p in phonetics:
                # Prioritize entries with both text and audio
                if p.get("text") and p.get("audio"):
                    pronunciation = p["text"]
                    audio_url = p["audio"]
                    break
                elif p.get("text") and not pronunciation:
                    pronunciation = p["text"]
                elif p.get("audio") and not audio_url:
                    audio_url = p["audio"]
            
            # Fallback to phonetic field if no IPA found
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
            
            # Create discovery data (frequency will be added by AI later)
            discovery_data = {
                "headword": word,
                "pronunciation": pronunciation,
                "audio_url": audio_url,  # Add audio URL from API
                "frequency": "common",  # Placeholder, will be replaced by AI
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
            sense_count = len(meanings) if is_from_api else len(senses)
            # 5 base tasks: etymology, word_family, usage_context, cultural_notes, frequency
            max_threads = min(10, 5 + sense_count)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                # Submit granular info tasks (always needed)
                etymology_future = executor.submit(self._fetch_etymology, word)
                word_family_future = executor.submit(self._fetch_word_family, word)
                usage_context_future = executor.submit(self._fetch_usage_context, word)
                cultural_notes_future = executor.submit(self._fetch_cultural_notes, word)
                
                # Submit frequency detection
                # - For API path: frequency not available, need AI
                # - For AI path: already in discovery_data, but fetch anyway for consistency
                frequency_future = None
                if is_from_api or not discovery_data.get("frequency"):
                    frequency_future = executor.submit(self._fetch_frequency, word)
                
                # Submit sense analysis
                sense_futures = []
                if is_from_api:
                    # API path: enhance API data with AI analysis
                    for i, meaning in enumerate(meanings):
                        definitions = [d.get("definition", "") for d in meaning.get("definitions", [])]
                        part_of_speech = meaning.get("partOfSpeech", "")
                        synonyms = meaning.get("synonyms", [])
                        antonyms = meaning.get("antonyms", [])
                        examples = [d.get("example", "") for d in meaning.get("definitions", []) if d.get("example")]
                        
                        future = executor.submit(
                            self._fetch_enhanced_sense,
                            word, i, part_of_speech, definitions, synonyms, antonyms, examples
                        )
                        sense_futures.append(future)
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
                
                # Get frequency
                if frequency_future:
                    results["frequency"] = self._get_future_result(frequency_future, "frequency")
                else:
                    # Use frequency from AI discovery
                    results["frequency"] = {
                        "success": True,
                        "frequency": discovery_data.get("frequency", "common")
                    }
                
                # Collect sense details
                for i, future in enumerate(sense_futures):
                    sense_result = self._get_future_result(future, f"sense_{i}")
                    if sense_result and sense_result.get("success"):
                        results["detailed_senses"].append(sense_result["sense_detail"])
                
                # Handle failures gracefully (allow partial success)
                if not results["etymology"] or not results["etymology"].get("success"):
                    print("Warning: Failed to fetch etymology, continuing...")
                    results["etymology"] = {"success": True, "etymology_info": {"etymology": "", "root_analysis": ""}}
                
                if not results["word_family"] or not results["word_family"].get("success"):
                    print("Warning: Failed to fetch word family, continuing...")
                    results["word_family"] = {"success": True, "word_family_info": {"word_family": []}}
                
                if not results["usage_context"] or not results["usage_context"].get("success"):
                    print("Warning: Failed to fetch usage context, continuing...")
                    results["usage_context"] = {"success": True, "usage_context_info": {"modern_relevance": "", "common_confusions": [], "regional_variations": []}}
                
                if not results["cultural_notes"] or not results["cultural_notes"].get("success"):
                    print("Warning: Failed to fetch cultural notes, continuing...")
                    results["cultural_notes"] = {"success": True, "cultural_notes_info": {"notes": ""}}
                
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
                             api_definitions: List[str], api_synonyms: List[str] = None,
                             api_antonyms: List[str] = None, api_examples: List[str] = None) -> Dict[str, Any]:
        """Fetch AI-enhanced analysis for a sense (API already provides basics)"""
        try:
            # Use prompt generator with API data
            prompt = get_enhanced_sense_prompt(
                word, sense_index, part_of_speech,
                api_definitions, api_synonyms, api_antonyms, api_examples
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
        
        # Get frequency (from AI or from discovery_data)
        frequency = results.get("frequency", {}).get("frequency", discovery_data.get("frequency", "common"))
        
        # Determine data source
        data_source = "hybrid_api_ai" if "api_raw_meanings" in discovery_data else "ai_only"
        
        # Get audio URL and pronunciation
        audio_url = discovery_data.get("audio_url", "")
        pronunciation = discovery_data.get("pronunciation", "")
        
        # If no pronunciation available, it means API failed and AI discovery didn't provide IPA
        # In this case, pronunciation field already has the IPA from AI discovery
        
        # Create final result
        final_result = {
            "headword": word,
            "pronunciation": pronunciation,
            "audio_url": audio_url,  # Empty string if not available from API
            "frequency": frequency,
            "data_source": data_source,
            
            # AI-enhanced information
            "etymology_info": results["etymology"]["etymology_info"],
            "word_family_info": results["word_family"]["word_family_info"],
            "usage_context_info": results["usage_context"]["usage_context_info"],
            "cultural_notes_info": results["cultural_notes"]["cultural_notes_info"],
            
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
                # Add empty audio_url since AI doesn't generate audio
                discovery_data["audio_url"] = ""
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
                    "etymology_info": response.content.model_dump()
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
                    "word_family_info": response.content.model_dump()
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
                    "usage_context_info": response.content.model_dump()
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
                    "cultural_notes_info": response.content.model_dump()
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