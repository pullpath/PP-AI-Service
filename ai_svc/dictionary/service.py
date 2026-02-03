"""
Optimized Dictionary Service using two-phase parallel architecture
Phase 1: Discover all word senses
Phase 2: Parallel fetch of detailed information for all senses and granular components

Only exposes one interface: lookup_word()
"""
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from typing import Dict, Any, List, Optional
import os
import time
import concurrent.futures
from dotenv import load_dotenv

# Import schemas and prompts
from .schemas import (
    WordSensesDiscovery, EtymologyInfo, WordFamilyInfo, 
    UsageContextInfo, CulturalNotesInfo, DetailedWordSense
)
from .prompts import (
    get_senses_discovery_prompt, get_etymology_prompt,
    get_word_family_prompt, get_usage_context_prompt,
    get_cultural_notes_prompt, get_detailed_sense_prompt
)

load_dotenv()


class DictionaryService:
    """Dictionary service using two-phase parallel architecture"""
    
    def __init__(self):
        # Get DeepSeek API key from environment
        deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        
        if not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")
        
        # Create DeepSeek model with optimized settings
        deepseek_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0,
            max_tokens=1024,
            timeout=30.0,
            max_retries=2
        )
        
        # Create specialized agents for each task
        self.senses_discovery_agent = Agent(
            name="SensesDiscoveryAgent",
            model=deepseek_model,
            description="Discovers all word senses and basic information",
            use_json_mode=True,
            output_schema=WordSensesDiscovery
        )
        
        self.etymology_agent = Agent(
            name="EtymologyAgent",
            model=deepseek_model,
            description="Provides etymology and root analysis",
            use_json_mode=True,
            output_schema=EtymologyInfo
        )
        
        self.word_family_agent = Agent(
            name="WordFamilyAgent",
            model=deepseek_model,
            description="Provides word family and related terms",
            use_json_mode=True,
            output_schema=WordFamilyInfo
        )
        
        self.usage_context_agent = Agent(
            name="UsageContextAgent",
            model=deepseek_model,
            description="Provides modern usage context and trends",
            use_json_mode=True,
            output_schema=UsageContextInfo
        )
        
        self.cultural_notes_agent = Agent(
            name="CulturalNotesAgent",
            model=deepseek_model,
            description="Provides cultural and linguistic notes",
            use_json_mode=True,
            output_schema=CulturalNotesInfo
        )
        
        self.detailed_sense_agent = Agent(
            name="DetailedSenseAgent",
            model=deepseek_model,
            description="Provides detailed analysis of specific word senses",
            use_json_mode=True,
            output_schema=DetailedWordSense
        )
    
    def lookup_word(self, word: str) -> Dict[str, Any]:
        """
        Main dictionary lookup interface
        Uses two-phase parallel architecture:
        1. Discover all word senses
        2. Parallel fetch of detailed information
        """
        try:
            start_time = time.time()
            
            # Phase 1: Discover commonly used word senses
            print(f"Phase 1: Discovering commonly used senses for '{word}'...")
            discovery_result = self._discover_word_senses(word)
            if not discovery_result.get("success"):
                return discovery_result
            
            phase_1_time = time.time()
            
            print('time spent on phase 1:', phase_1_time - start_time)
            
            discovery_data = discovery_result["discovery_data"]
            total_senses = len(discovery_data["senses"])
            print(f"Discovered {total_senses} senses for '{word}'")
            
            # Phase 2: Parallel fetch of all detailed information
            print(f"Phase 2: Parallel fetch of detailed information...")
            detailed_result = self._fetch_detailed_info_parallel(word, discovery_data)
            if not detailed_result.get("success"):
                return detailed_result
            
            phase_2_time = time.time()
            print('time spent on phase 2:', phase_2_time - phase_1_time)
            
            # Combine results
            final_result = self._combine_results(
                word, discovery_data, detailed_result, start_time, total_senses
            )
            
            return final_result
            
        except Exception as e:
            return {
                "headword": word,
                "error": str(e),
                "success": False
            }
    
    def _discover_word_senses(self, word: str) -> Dict[str, Any]:
        """Phase 1: Discover all word senses"""
        try:
            prompt = get_senses_discovery_prompt(word)
            response = self.senses_discovery_agent.run(prompt)
            
            if isinstance(response.content, WordSensesDiscovery):
                return {
                    "success": True,
                    "discovery_data": response.content.model_dump()
                }
            else:
                # Try to get more specific error information
                error_msg = "Failed to parse word senses discovery"
                if hasattr(response, 'content') and response.content:
                    # Check if it's a validation error
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
            # Make error message more user-friendly
            if "tone" in error_msg.lower() and "enum" in error_msg.lower():
                error_msg = "Invalid tone value returned. Tone must be one of: positive, negative, neutral, humorous, derogatory, pejorative, approving"
            
            return {
                "success": False,
                "error": error_msg,
                "headword": word
            }
    
    def _fetch_detailed_info_parallel(self, word: str, discovery_data: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 2: Parallel fetch of all detailed information"""
        try:
            total_senses = len(discovery_data["senses"])
            
            # Calculate optimal thread count (max 10 threads total)
            max_threads = min(10, 4 + total_senses)  # 4 granular agents + sense agents
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                # Submit all granular info tasks
                etymology_future = executor.submit(self._fetch_etymology, word)
                word_family_future = executor.submit(self._fetch_word_family, word)
                usage_context_future = executor.submit(self._fetch_usage_context, word)
                cultural_notes_future = executor.submit(self._fetch_cultural_notes, word)
                
                # Submit detailed sense analysis tasks for ALL senses
                sense_futures = []
                for i, sense_basic in enumerate(discovery_data["senses"]):
                    future = executor.submit(
                        self._fetch_detailed_sense,
                        word, i, sense_basic["definition"]
                    )
                    sense_futures.append(future)
                
                # Wait for all tasks to complete
                all_futures = [
                    etymology_future, word_family_future, 
                    usage_context_future, cultural_notes_future
                ] + sense_futures
                
                concurrent.futures.wait(all_futures)
                
                # Collect results
                results = {
                    "etymology": self._get_future_result(etymology_future, "etymology"),
                    "word_family": self._get_future_result(word_family_future, "word_family"),
                    "usage_context": self._get_future_result(usage_context_future, "usage_context"),
                    "cultural_notes": self._get_future_result(cultural_notes_future, "cultural_notes"),
                    "detailed_senses": []
                }
                
                # Collect detailed senses
                for i, future in enumerate(sense_futures):
                    sense_result = self._get_future_result(future, f"sense_{i}")
                    if sense_result and sense_result.get("success"):
                        results["detailed_senses"].append(sense_result["sense_detail"])
                
                # Check for critical failures
                critical_fields = ["etymology", "word_family", "usage_context", "cultural_notes"]
                for field in critical_fields:
                    if not results[field] or not results[field].get("success"):
                        return {
                            "success": False,
                            "error": f"Failed to fetch {field} information",
                            "headword": word
                        }
                
                if len(results["detailed_senses"]) == 0:
                    return {
                        "success": False,
                        "error": "Failed to fetch any detailed senses",
                        "headword": word
                    }
                
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
        """Fetch detailed analysis for a specific sense"""
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
            return future.result(timeout=35.0)
        except concurrent.futures.TimeoutError:
            print(f"Warning: Timeout fetching {task_name}")
            return {
                "success": False,
                "error": f"Timeout fetching {task_name}"
            }
        except Exception as e:
            print(f"Warning: Error fetching {task_name}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _combine_results(self, word: str, discovery_data: Dict[str, Any], 
                        detailed_result: Dict[str, Any], start_time: float, 
                        total_senses: int) -> Dict[str, Any]:
        """Combine all results into final dictionary result"""
        results = detailed_result["results"]
        
        # Create final result
        final_result = {
            "headword": word,
            "pronunciation": discovery_data["pronunciation"],
            "frequency": discovery_data["frequency"],
            
            # Granular secondary information
            "etymology_info": results["etymology"]["etymology_info"],
            "word_family_info": results["word_family"]["word_family_info"],
            "usage_context_info": results["usage_context"]["usage_context_info"],
            "cultural_notes_info": results["cultural_notes"]["cultural_notes_info"],
            
            # Detailed senses
            "detailed_senses": results["detailed_senses"],
            
            # Metadata
            "timestamp": time.time(),
            "total_senses": total_senses,
            "parallel_execution": True,
            "execution_time": time.time() - start_time,
            "success": True
        }
        
        return final_result


# Global instance
dictionary_service = DictionaryService()