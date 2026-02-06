#!/usr/bin/env python
"""
Test script to verify section name changes
Tests all sections to ensure they return correct structure
"""
from ai_svc.dictionary import dictionary_service
import json

def test_section(word, section):
    """Test a specific section"""
    print(f"\n{'='*60}")
    print(f"Testing section: {section}")
    print('='*60)
    
    result = dictionary_service.lookup_section(word, section)
    
    if result.get("success"):
        print(f"✓ Success")
        print(f"Response keys: {list(result.keys())}")
        
        # Check if the section key exists
        if section and section != 'basic_info':
            if section in result:
                print(f"✓ Section key '{section}' found in response")
            else:
                print(f"✗ ERROR: Section key '{section}' NOT found in response")
                print(f"Available keys: {list(result.keys())}")
    else:
        print(f"✗ Failed: {result.get('error')}")
    
    return result

def main():
    word = "hello"
    
    print(f"Testing dictionary sections for word: '{word}'")
    
    # Test basic_info (no AI required, fast)
    test_section(word, "basic_info")
    
    # Test individual AI sections
    sections = [
        "etymology",
        "word_family", 
        "usage_context",
        "cultural_notes",
        "frequency",
    ]
    
    for section in sections:
        test_section(word, section)
    
    print(f"\n{'='*60}")
    print("All section tests completed!")
    print('='*60)

if __name__ == "__main__":
    main()
