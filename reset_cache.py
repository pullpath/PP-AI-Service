#!/usr/bin/env python3
"""
Manual script to reset the dictionary cache database.

Usage:
    python reset_cache.py              # Interactive confirmation
    python reset_cache.py --force      # Skip confirmation
    python reset_cache.py --word hello # Reset specific word only
"""

import argparse
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_svc.dictionary.cache_service import cache_service


def reset_all_cache(force: bool = False):
    """Reset entire cache database"""
    if not force:
        print("⚠️  WARNING: This will delete ALL cached dictionary data!")
        print(f"   Database: {cache_service.db_path}")
        response = input("\n   Continue? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("❌ Cancelled.")
            return False
    
    try:
        stats = cache_service.get_stats()
        total_words = stats['database']['total_words']
        total_entries = stats['database']['total_entries']
        total_senses = stats['database']['total_senses']
        
        cache_service.clear_all()
        
        print(f"\n✅ Cache reset successful!")
        print(f"   Deleted: {total_words} words, {total_entries} entries, {total_senses} senses")
        print(f"   Database: {cache_service.db_path}")
        return True
    except Exception as e:
        print(f"\n❌ Error resetting cache: {e}")
        return False


def reset_word_cache(word: str, force: bool = False):
    """Reset cache for specific word"""
    if not force:
        print(f"⚠️  WARNING: This will delete ALL cached data for word '{word}'")
        response = input("\n   Continue? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("❌ Cancelled.")
            return False
    
    try:
        cache_service.invalidate_word(word)
        print(f"\n✅ Cache invalidated for word: {word}")
        return True
    except Exception as e:
        print(f"\n❌ Error invalidating word cache: {e}")
        return False


def show_stats():
    """Show current cache statistics"""
    try:
        stats = cache_service.get_stats()
        print("\n📊 Cache Statistics:")
        print(f"   Total words: {stats['database']['total_words']}")
        print(f"   Total entries: {stats['database']['total_entries']}")
        print(f"   Total senses: {stats['database']['total_senses']}")
        print(f"   Database size: {stats['database'].get('db_size_mb', 'N/A')} MB")
        print(f"   Database: {cache_service.db_path}")
        
        if 'in_memory_stats' in stats:
            mem = stats['in_memory_stats']
            print(f"\n   Cache hit rate: {mem['cache_hit_rate']*100:.1f}%")
            print(f"   Total requests: {mem['total_requests']}")
            print(f"   Cache hits: {mem['cache_hits']}")
            print(f"   Cache misses: {mem['cache_misses']}")
    except Exception as e:
        print(f"\n❌ Error fetching stats: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Reset dictionary cache database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python reset_cache.py                 # Interactive reset all
  python reset_cache.py --force         # Reset all (skip confirmation)
  python reset_cache.py --word hello    # Reset specific word
  python reset_cache.py --stats         # Show cache statistics
        """
    )
    
    parser.add_argument('--force', '-f', action='store_true',
                        help='Skip confirmation prompt')
    parser.add_argument('--word', '-w', type=str,
                        help='Reset cache for specific word only')
    parser.add_argument('--stats', '-s', action='store_true',
                        help='Show cache statistics (no reset)')
    
    args = parser.parse_args()
    
    # Show stats only
    if args.stats:
        show_stats()
        return
    
    # Reset specific word
    if args.word:
        success = reset_word_cache(args.word, args.force)
        sys.exit(0 if success else 1)
    
    # Reset all
    success = reset_all_cache(args.force)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
