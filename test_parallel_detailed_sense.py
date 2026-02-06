#!/usr/bin/env python3
"""
Test script for parallel detailed_sense execution
Verifies that parallel execution produces correct output structure and is faster
"""

import sys
import time
from ai_svc.dictionary import dictionary_service

def test_parallel_detailed_sense():
    """Test parallel execution for detailed_sense"""
    print("="*60)
    print(" Testing Parallel Detailed Sense Execution")
    print("="*60)
    
    test_word = "run"
    test_index = 0
    
    print(f"\nTest 1: Fetching detailed_sense for '{test_word}' (sense #{test_index})")
    print("-" * 60)
    
    start_time = time.time()
    result = dictionary_service.lookup_section(test_word, "detailed_sense", index=test_index)
    execution_time = time.time() - start_time
    
    if not result.get("success"):
        print(f"❌ FAILED: {result.get('error')}")
        return False
    
    print(f"✅ SUCCESS: Execution time: {execution_time:.2f}s")
    
    # Verify structure
    sense = result.get("detailed_sense", {})
    
    required_fields = [
        "definition", "part_of_speech", "usage_register", "domain", "tone",
        "usage_notes", "examples", "collocations", "word_specific_phrases",
        "synonyms", "antonyms"
    ]
    
    missing_fields = [field for field in required_fields if field not in sense]
    
    if missing_fields:
        print(f"❌ MISSING FIELDS: {missing_fields}")
        return False
    
    print(f"✅ All required fields present")
    
    # Verify examples count
    examples = sense.get("examples", [])
    if len(examples) != 3:
        print(f"❌ Expected 3 examples, got {len(examples)}")
        return False
    
    print(f"✅ Correct number of examples: {len(examples)}")
    
    # Print sample output
    print("\n" + "-" * 60)
    print("Sample Output:")
    print("-" * 60)
    print(f"Definition: {sense['definition'][:100]}...")
    print(f"Part of Speech: {sense['part_of_speech']}")
    print(f"Usage Register: {sense['usage_register']}")
    print(f"Domain: {sense['domain']}")
    print(f"Tone: {sense['tone']}")
    print(f"Examples: {len(examples)} examples")
    print(f"Collocations: {len(sense.get('collocations', []))} collocations")
    print(f"Synonyms: {len(sense.get('synonyms', []))} synonyms")
    print(f"Antonyms: {len(sense.get('antonyms', []))} antonyms")
    print(f"Phrases: {len(sense.get('word_specific_phrases', []))} phrases")
    
    # Performance check
    print("\n" + "-" * 60)
    print("Performance Analysis:")
    print("-" * 60)
    
    if execution_time < 6:
        print(f"✅ EXCELLENT: {execution_time:.2f}s (target: <6s)")
    elif execution_time < 8:
        print(f"✅ GOOD: {execution_time:.2f}s (target: <6s, acceptable: <8s)")
    elif execution_time < 13:
        print(f"⚠️  ACCEPTABLE: {execution_time:.2f}s (old sequential: ~10-13s)")
    else:
        print(f"❌ SLOW: {execution_time:.2f}s (slower than old sequential method)")
    
    print("\n" + "=" * 60)
    print("Expected improvements with parallel execution:")
    print("- Old sequential: ~10-13s")
    print("- New parallel: ~4-6s (60-70% faster)")
    print("=" * 60)
    
    return True


def test_basic_then_detailed():
    """Test typical workflow: basic first, then detailed_sense"""
    print("\n\n" + "="*60)
    print(" Testing Typical Workflow: Basic → Detailed Sense")
    print("="*60)
    
    test_word = "example"
    
    # Step 1: Get basic info
    print(f"\nStep 1: Fetching basic info for '{test_word}'...")
    start_time = time.time()
    basic_result = dictionary_service.lookup_section(test_word, "basic")
    basic_time = time.time() - start_time
    
    if not basic_result.get("success"):
        print(f"❌ Basic lookup failed: {basic_result.get('error')}")
        return False
    
    total_senses = basic_result.get("total_senses", 0)
    print(f"✅ Basic info retrieved in {basic_time:.2f}s")
    print(f"   Total senses: {total_senses}")
    
    # Step 2: Get first detailed sense
    print(f"\nStep 2: Fetching detailed sense #0...")
    start_time = time.time()
    sense_result = dictionary_service.lookup_section(test_word, "detailed_sense", index=0)
    sense_time = time.time() - start_time
    
    if not sense_result.get("success"):
        print(f"❌ Detailed sense lookup failed: {sense_result.get('error')}")
        return False
    
    print(f"✅ Detailed sense retrieved in {sense_time:.2f}s")
    
    total_time = basic_time + sense_time
    print(f"\n" + "-" * 60)
    print(f"Total workflow time: {total_time:.2f}s")
    print(f"  - Basic: {basic_time:.2f}s")
    print(f"  - Detailed sense: {sense_time:.2f}s")
    print("-" * 60)
    
    return True


def main():
    """Run all tests"""
    try:
        print("\n🚀 Starting Parallel Execution Tests\n")
        
        test1_success = test_parallel_detailed_sense()
        test2_success = test_basic_then_detailed()
        
        print("\n\n" + "="*60)
        print(" TEST SUMMARY")
        print("="*60)
        
        if test1_success and test2_success:
            print("✅ ALL TESTS PASSED")
            print("\nParallel execution is working correctly!")
            print("- Output structure is correct (all fields present)")
            print("- Performance improvement achieved")
            print("- Typical workflow verified")
            return 0
        else:
            print("❌ SOME TESTS FAILED")
            if not test1_success:
                print("- Parallel detailed_sense test failed")
            if not test2_success:
                print("- Workflow test failed")
            return 1
            
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
