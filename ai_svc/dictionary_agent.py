"""
Dictionary Agent using Agno framework with DeepSeek
A simple agent that provides dictionary-like functionality using DeepSeek
"""
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from typing import Dict, Any
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field

class Definition(BaseModel):
    word: str = Field(..., description="The word or phrase being defined")
    definition: str = Field(..., description="The definition of the word or phrase")
    examples: list[str] = Field([], description="Example sentences using the word or phrase")
    synonyms: list[str] = Field([], description="Synonyms of the word or phrase")
    antonyms: list[str] = Field([], description="Antonyms of the word or phrase")
    etymology: str = Field("", description="The origin or etymology of the word or phrase")
    part_of_speech: str = Field("", description="The part of speech (noun, verb, adjective, etc.)")

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
        )
        
        # Initialize the Agno agent with DeepSeek
        self.agent = Agent(
            name="DictionaryAgent",
            model=deepseek_model,
            instructions="""
            You are a helpful dictionary assistant. Your task is to:
            1. Provide clear, concise definitions for words
            2. Give examples of word usage in sentences
            3. Provide synonyms and antonyms when relevant
            4. Explain word origins or etymology when known
            5. Handle multiple meanings for polysemous words
            
            Keep responses informative but concise.
            Always respond in valid JSON format.
            """,
            # markdown=True,
            use_json_mode=True,
            output_schema=Definition
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
            # Use the agent to generate a response
            response = self.agent.run(
                f"Please provide dictionary information for the word: '{word}'"
            )
            
            # Get the response content
            response_content = response.content
            
            # Try to parse as JSON
            import json
            try:
                result = json.loads(response_content)
                
                # Add success flag and ensure word is included
                result["success"] = True
                if "word" not in result:
                    result["word"] = word
                    
                return result
                
            except json.JSONDecodeError:
                # If response is not valid JSON, return it as plain text
                return {
                    "word": word,
                    "definition": response_content,
                    "raw_response": response_content,
                    "success": True,
                    "note": "Response was not in expected JSON format"
                }
            
        except Exception as e:
            return {
                "word": word,
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