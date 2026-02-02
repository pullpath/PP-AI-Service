"""
Simple DeepSeek dictionary agent without Agno framework
Direct OpenAI client integration with DeepSeek API
"""
import os
import json
from typing import Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

class DeepSeekDictionary:
    """A simple dictionary agent using DeepSeek API directly"""
    
    def __init__(self):
        # Get DeepSeek API key from environment
        deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        
        if not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")
        
        # Initialize OpenAI client with DeepSeek configuration
        self.client = OpenAI(
            api_key=deepseek_api_key,
            base_url="https://api.deepseek.com"
        )
        
        # Dictionary agent instructions
        self.instructions = """
        You are a helpful dictionary assistant. Your task is to:
        1. Provide clear, concise definitions for words
        2. Give examples of word usage in sentences
        3. Provide synonyms and antonyms when relevant
        4. Explain word origins or etymology when known
        5. Handle multiple meanings for polysemous words
        
        Keep responses informative but concise. Format responses in a readable way.
        Always respond in valid JSON format with the following structure:
        {
            "word": "[the word being defined]",
            "definition": "[clear definition]",
            "examples": ["[example 1]", "[example 2]"],
            "synonyms": ["[synonym 1]", "[synonym 2]"],
            "antonyms": ["[antonym 1]", "[antonym 2]"],
            "etymology": "[brief etymology if known]",
            "part_of_speech": "[noun/verb/adjective/etc]"
        }
        """
    
    def lookup_word(self, word: str) -> Dict[str, Any]:
        """
        Look up a word using DeepSeek API
        
        Args:
            word: The word to look up
            
        Returns:
            Dictionary with word information
        """
        try:
            # Create the prompt
            prompt = f"{self.instructions}\n\nPlease provide dictionary information for the word: '{word}'"
            
            # Call DeepSeek API
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a dictionary assistant that responds in JSON format."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            # Get the response content
            response_content = response.choices[0].message.content
            
            # Try to parse as JSON
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


# Create a global instance for easy access
deepseek_dictionary = DeepSeekDictionary()