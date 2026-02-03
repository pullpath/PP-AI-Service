"""
Dictionary Agent using Agno framework with DeepSeek
A simple agent that provides dictionary-like functionality using DeepSeek
"""
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from typing import Dict, Any
import os
from dotenv import load_dotenv

# Import from modular schemas and prompts
from .schemas import DictionaryEntry
from .prompts import get_dictionary_prompt

load_dotenv()


class DictionaryAgent:
    """A simple dictionary agent that can look up words and provide definitions using DeepSeek"""
    
    def __init__(self):
        # Get DeepSeek API key from environment
        deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        
        if not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")
        
        # Create DeepSeek model using Agno's DeepSeek model
        deepseek_model = DeepSeek(
            id="deepseek-chat",
            api_key=deepseek_api_key,
            temperature=0
        )
        
        # Initialize the Agno agent with DeepSeek
        self.agent = Agent(
            name="DictionaryAgent",
            model=deepseek_model,
            description="A dictionary agent that provides comprehensive word definitions and linguistic analysis",
            instructions="""You are an AI assistant specialized in language analysis. Follow these guidelines:
1. Always respond in valid JSON format when JSON mode is enabled
2. Provide accurate, well-researched linguistic information
3. Structure responses according to the specified output schema
4. Focus on clarity and educational value for language learners""",
            use_json_mode=True,
            output_schema=DictionaryEntry
        )
    
    def lookup_word(self, word: str) -> Dict[str, Any]:
        """
        Look up a word and return dictionary information using DeepSeek
        
        Args:
            word: The word to look up
            
        Returns:
            Dictionary with word information in structured format
        """
        try:
            # Format the prompt with the actual word
            prompt = get_dictionary_prompt(word)
            
            # Use the agent to generate a response
            response = self.agent.run(prompt)
            
            # When using JSON mode with output_schema, response.content is a Pydantic model
            if isinstance(response.content, DictionaryEntry):
                definition_model = response.content
                # Convert Pydantic model to dict
                result = definition_model.model_dump()
                result["success"] = True
                return result
            else:
                # Fallback: try to parse as JSON string
                import json
                try:
                    result = json.loads(str(response.content))
                    result["success"] = True
                    if "headword" not in result:
                        result["headword"] = word
                    return result
                except json.JSONDecodeError:
                    # If response is not valid JSON, return it as plain text
                    return {
                        "headword": word,
                        "definition": str(response.content),
                        "raw_response": str(response.content),
                        "success": False,
                        "note": "Response was not in expected JSON format"
                    }
            
        except Exception as e:
            return {
                "headword": word,
                "error": str(e),
                "success": False
            }
    
    # Note: lookup_word is now synchronous, so no need for separate sync method
    # This method is kept for backward compatibility
    def lookup_word_sync(self, word: str) -> Dict[str, Any]:
        """
        Alias for lookup_word (now synchronous)
        
        Args:
            word: The word to look up
            
        Returns:
            Dictionary with word information
        """
        return self.lookup_word(word)


# Create a global instance for easy access
dictionary_agent = DictionaryAgent()