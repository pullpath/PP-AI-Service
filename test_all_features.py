#!/usr/bin/env python3
"""
Comprehensive test script for all AI service features
This script will be updated as new features are added
"""

import os
import sys
import json
import requests
from typing import Dict, Any, List
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

class FeatureTester:
    """Test all features of the AI service"""
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.test_results = {}
        
    def print_header(self, title: str):
        """Print a formatted header"""
        print(f"\n{'='*60}")
        print(f" {title}")
        print(f"{'='*60}")
    
    def print_result(self, test_name: str, success: bool, details: str = ""):
        """Print test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {test_name}: {status}")
        if details:
            print(f"    {details}")
        self.test_results[test_name] = success
    
    def test_dictionary_service_direct(self):
        """Test the dictionary service directly (without Flask)"""
        self.print_header("Testing Dictionary Service (Direct)")
        
        try:
            from ai_svc.dictionary import DictionaryService, dictionary_service
            
            # Test 1: Test global instance
            print("  Testing global dictionary_service instance...")
            self.print_result("Global Instance", True, "Global instance available")
            
            # Test 2: Create new agent instance
            print("  Creating new DictionaryService instance...")
            agent = DictionaryService()
            self.print_result("Agent Creation", True, "DictionaryService created successfully")
            
            # Test 3: Test section-based API with new instance
            test_word = "example"
            print(f"  Testing section-based API for: '{test_word}'...")
            
            # Test basic section
            basic_result = agent.lookup_section(test_word, "basic")
            success = basic_result.get("success", False)
            
            if success:
                headword = basic_result.get("headword", "N/A")
                pronunciation = basic_result.get("pronunciation", "N/A")
                total_senses = basic_result.get("total_senses", 0)
                
                self.print_result("Basic Section", True, 
                                 f"Headword: {headword}, Total senses: {total_senses}")
                
                # Test etymology section
                etymology_result = agent.lookup_section(test_word, "etymology")
                if etymology_result.get("success"):
                    self.print_result("Etymology Section", True, 
                                     "Etymology data retrieved")
                else:
                    self.print_result("Etymology Section", False, 
                                     f"Error: {etymology_result.get('error', 'Unknown')}")
                
                # Test frequency section
                frequency_result = agent.lookup_section(test_word, "frequency")
                if frequency_result.get("success"):
                    freq = frequency_result.get("frequency", "N/A")
                    self.print_result("Frequency Section", True, 
                                     f"Frequency: {freq}")
                else:
                    self.print_result("Frequency Section", False, 
                                     f"Error: {frequency_result.get('error', 'Unknown')}")
                
                # Test detailed_sense section
                if total_senses > 0:
                    sense_result = agent.lookup_section(test_word, "detailed_sense", index=0)
                    if sense_result.get("success"):
                        sense = sense_result.get("detailed_sense", {})
                        definition = sense.get("definition", "N/A")[:50]
                        self.print_result("Detailed Sense Section", True, 
                                         f"Sense 0: {definition}...")
                    else:
                        self.print_result("Detailed Sense Section", False, 
                                         f"Error: {sense_result.get('error', 'Unknown')}")
                
                # Test error handling - missing index
                error_result = agent.lookup_section(test_word, "detailed_sense")
                if not error_result.get("success") and "index" in error_result.get("error", ""):
                    self.print_result("Error Handling (Missing Index)", True, 
                                     "Correctly rejects missing index parameter")
                else:
                    self.print_result("Error Handling (Missing Index)", False, 
                                     "Should reject missing index parameter")
                
            else:
                error_msg = basic_result.get("error", "Unknown error")
                self.print_result("Basic Section", False, f"Error: {error_msg}")
            
            return success
            
        except Exception as e:
            self.print_result("Direct Agent Test", False, f"Error: {str(e)}")
            return False
    
    def test_flask_endpoints(self):
        """Test Flask API endpoints"""
        self.print_header("Testing Flask API Endpoints")
        
        endpoints = [
            # Dictionary endpoints
            {
                "name": "GET /api/dictionary/test",
                "method": "GET",
                "url": f"{self.base_url}/api/dictionary/test",
                "data": None,
                "expected_status": 200
            },
            {
                "name": "POST /api/dictionary (basic section)",
                "method": "POST",
                "url": f"{self.base_url}/api/dictionary",
                "data": {"word": "example", "section": "basic"},
                "expected_status": 200
            },
            {
                "name": "POST /api/dictionary (etymology section)",
                "method": "POST",
                "url": f"{self.base_url}/api/dictionary",
                "data": {"word": "example", "section": "etymology"},
                "expected_status": 200
            },
            {
                "name": "POST /api/dictionary (detailed_sense with index)",
                "method": "POST",
                "url": f"{self.base_url}/api/dictionary",
                "data": {"word": "example", "section": "detailed_sense", "index": 0},
                "expected_status": 200
            },
            {
                "name": "POST /api/dictionary (missing word)",
                "method": "POST",
                "url": f"{self.base_url}/api/dictionary",
                "data": {"section": "basic"},
                "expected_status": 400
            },
            {
                "name": "POST /api/dictionary (missing section)",
                "method": "POST",
                "url": f"{self.base_url}/api/dictionary",
                "data": {"word": "example"},
                "expected_status": 400
            },
            {
                "name": "POST /api/dictionary (detailed_sense missing index)",
                "method": "POST",
                "url": f"{self.base_url}/api/dictionary",
                "data": {"word": "example", "section": "detailed_sense"},
                "expected_status": 400
            },
        ]
        
        all_success = True
        
        for endpoint in endpoints:
            try:
                if endpoint["method"] == "GET":
                    response = requests.get(endpoint["url"])
                else:  # POST
                    response = requests.post(
                        endpoint["url"],
                        json=endpoint["data"],
                        headers={"Content-Type": "application/json"}
                    )
                
                success = response.status_code == endpoint["expected_status"]
                details = f"Status: {response.status_code} (expected: {endpoint['expected_status']})"
                
                if success and response.status_code == 200:
                    try:
                        data = response.json()
                        if "success" in data:
                            details += f", Success: {data['success']}"
                    except:
                        pass
                
                self.print_result(endpoint["name"], success, details)
                all_success = all_success and success
                
            except Exception as e:
                self.print_result(endpoint["name"], False, f"Error: {str(e)}")
                all_success = False
        
        return all_success
    
    def test_deepseek_integration(self):
        """Test DeepSeek API integration"""
        self.print_header("Testing DeepSeek Integration")
        
        # Test 1: Check API key
        api_key = os.getenv('DEEPSEEK_API_KEY')
        if api_key:
            self.print_result("API Key Config", True, f"API key found: {api_key[:10]}...")
        else:
            self.print_result("API Key Config", False, "DEEPSEEK_API_KEY not set in .env")
            return False
        
        # Test 2: Test simple DeepSeek query
        try:
            from openai import OpenAI
            
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Say 'Hello' in one word."}],
                max_tokens=10
            )
            
            if response.choices[0].message.content:
                self.print_result("DeepSeek API Connection", True, 
                                 f"Response: {response.choices[0].message.content}")
            else:
                self.print_result("DeepSeek API Connection", False, "No response content")
                return False
                
        except Exception as e:
            self.print_result("DeepSeek API Connection", False, f"Error: {str(e)}")
            return False
        
        # Test 3: Test Agno with DeepSeek
        try:
            from agno.agent import Agent
            from agno.models.deepseek import DeepSeek
            
            agent = Agent(
                model=DeepSeek(id="deepseek-chat", api_key=api_key),
                markdown=True
            )
            
            # Simple test
            response = agent.run("Say 'Test passed' if you can read this.")
            if response and response.content:
                self.print_result("Agno DeepSeek Integration", True, 
                                 f"Agno agent responded: {response.content[:50]}...")
            else:
                self.print_result("Agno DeepSeek Integration", False, "No response from Agno agent")
                return False
                
        except Exception as e:
            self.print_result("Agno DeepSeek Integration", False, f"Error: {str(e)}")
            return False
        
        return True
    
    def test_openai_audio_vision(self):
        """Test OpenAI audio/vision endpoints (basic connectivity)"""
        self.print_header("Testing OpenAI Audio/Vision Endpoints")
        
        endpoints = [
            {
                "name": "GET /api/transcribe",
                "url": f"{self.base_url}/api/transcribe",
                "expected_status": 405  # Method Not Allowed (requires POST)
            },
            {
                "name": "GET /api/vision",
                "url": f"{self.base_url}/api/vision",
                "expected_status": 200  # Returns HTML form for file upload
            },
        ]
        
        all_success = True
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint["url"])
                success = response.status_code == endpoint["expected_status"]
                details = f"Status: {response.status_code} (expected: {endpoint['expected_status']})"
                self.print_result(endpoint["name"], success, details)
                all_success = all_success and success
            except Exception as e:
                self.print_result(endpoint["name"], False, f"Error: {str(e)}")
                all_success = False
        
        return all_success
    
    def run_all_tests(self):
        """Run all tests"""
        print("\n" + "="*60)
        print(" COMPREHENSIVE AI SERVICE TEST")
        print("="*60)
        
        # Run tests in logical order
        print("\nRunning tests in order:")
        print("1. DeepSeek Integration Test")
        print("2. Dictionary Service Direct Test")
        print("3. Flask API Endpoints Test")
        print("4. OpenAI Audio/Vision Test")
        
        test1 = self.test_deepseek_integration()
        test2 = self.test_dictionary_service_direct()
        test3 = self.test_flask_endpoints()
        test4 = self.test_openai_audio_vision()
        
        # Summary
        self.print_header("TEST SUMMARY")
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result)
        
        print(f"  Total Tests: {total_tests}")
        print(f"  Passed: {passed_tests}")
        print(f"  Failed: {total_tests - passed_tests}")
        print(f"  Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        overall_success = all([test1, test2, test3, test4])
        
        if overall_success:
            print("\n✅ ALL TESTS PASSED!")
            print("\nSystem Architecture Summary:")
            print("  - Section-based API: Request specific sections (basic, etymology, etc.)")
            print("  - DeepSeek: Dictionary agent with hybrid API + AI architecture")
            print("  - OpenAI: Audio transcription, Vision analysis")
            print("  - Agno Framework: Agent-driven architecture with JSON mode")
            print("  - Flask API: All endpoints functional")
            print("  - No Caching: Simplified architecture, all requests hit service layer")
            print("  - Progressive Loading: Load basic first, then sections on-demand")
        else:
            print("\n❌ SOME TESTS FAILED")
            print("\nFailed tests:")
            for test_name, success in self.test_results.items():
                if not success:
                    print(f"  - {test_name}")
        
        return overall_success

def main():
    """Main function"""
    tester = FeatureTester()
    
    try:
        success = tester.run_all_tests()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())