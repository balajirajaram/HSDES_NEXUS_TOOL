"""
Example usage of cache_log_search module for log indexing and searching.
"""

import sys
from pathlib import Path
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.cache_log_search import index, search, get_cache_info, list_cached_files

def main():
    # Example 1: Index a log file
    print("\n" + "="*80)
    print("Example 1: Index a log file")
    print("="*80)
    print("\nℹ️  Note: Replace this path with your actual log file path")
    print("   Example: log_file = Path('logs/combinedlog.txt')")
    
    # Uncomment and modify with your log file path:
    # log_file = Path("logs/combinedlog.txt")
    # cache_path = index(log_file)
    # print(f"\n✅ Indexed successfully! Cache: {cache_path}")
    
    # Example 2: Get cache info
    print("\n" + "="*80)
    print("Example 2: Get cache information")
    print("="*80)
    
    # Uncomment after indexing:
    # cache_info = get_cache_info(log_file)
    # if cache_info:
    #     print(json.dumps(cache_info, indent=2))
    
    # Example 3: Search for keywords in entire file
    print("\n" + "="*80)
    print("Example 3: Search entire file for keywords")
    print("="*80)
    
    # Uncomment after indexing:
    # keywords = ["socket_discovery", "acode manager", "Failed"]
    # results = search(
    #     file=log_file,
    #     keys=keywords,
    #     lines=50,  # ±50 lines of context
    #     section=None  # Search entire file
    # )
    
    # # Display results
    # for result in results:
    #     print(f"\n📌 Keyword: '{result['key']}'")
    #     print(f"   Unique matches: {result['uniques']}")
    #     print(f"   Top 3 anchors:")
    #     for anchor in result['anchors'][:3]:
    #         print(f"      • Line {anchor['Ln#']}: {anchor['Str'][:80]}... (Count: {anchor['Cnt']})")
    
    # Example 4: Search within specific section
    print("\n" + "="*80)
    print("Example 4: Search within specific section")
    print("="*80)
    
    # Uncomment after indexing:
    # results = search(
    #     file=log_file,
    #     keys=["discovery"],
    #     lines=30,
    #     section="socket_discovery"  # Only search sections with this name
    # )
    
    # print(f"\nFound {len(results)} result(s)")
    # for result in results:
    #     print(f"   '{result['key']}': {result['uniques']} unique matches")
    
    # Example 5: List all cached files
    print("\n" + "="*80)
    print("Example 5: List all cached files")
    print("="*80)
    
    cached = list_cached_files()
    print(f"\nTotal cached files: {len(cached)}")
    if cached:
        for file_path, info in cached.items():
            print(f"\n   File: {Path(file_path).name}")
            print(f"   Cache: {info['hex_digest']}")
            print(f"   Sections: {info['total_sections']}")
            print(f"   Indexed: {info['indexed_at']}")
    else:
        print("   No files cached yet. Run index() on a log file first.")
    
    print("\n" + "="*80)
    print("ℹ️  To use these examples, uncomment the code and provide a log file path")
    print("="*80)


if __name__ == "__main__":
    main()
