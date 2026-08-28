from pathlib import Path
import hashlib
import json
import re
import os
import time
from typing import Dict, List, Any, Optional

from .indexer import LogChunker, minimal_analyzer

# Cache directory
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Cache registry to track indexed files
REGISTRY_FILE = CACHE_DIR / "registry.json"


def _get_cache_path(file_path: Path) -> Path:
    """Generate cache filename from file path using hex digest."""
    file_path_str = str(file_path.absolute())
    hex_digest = hashlib.sha256(file_path_str.encode()).hexdigest()
    return CACHE_DIR / f"{hex_digest}.json"


def _update_registry(file_path: Path, cache_path: Path, metadata: Dict):
    """Update cache registry with file information."""
    registry = {}
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, 'r') as f:
            registry = json.load(f)
    
    registry[str(file_path.absolute())] = {
        "cache_file": str(cache_path),
        "hex_digest": cache_path.stem,
        "indexed_at": metadata.get("indexed_at"),
        "total_sections": metadata.get("total_sections"),
        "file_size": file_path.stat().st_size if file_path.exists() else 0
    }
    
    with open(REGISTRY_FILE, 'w') as f:
        json.dump(registry, f, indent=2)


def index(path: Path, header_pattern: str = r'\*{10,}\s+\[.*?\]\s+.*?\s+\*{10,}') -> Path:
    """
    Index a log file and cache the results.
    
    Args:
        path: Path to the log file
        header_pattern: Regex pattern to match section headers
        
    Returns:
        Path to the cached JSON file
    """
    total_start = time.time()
    
    # Generate cache filename
    cache_path = _get_cache_path(path)
    
    print(f"\n{'='*80}")
    print(f"📁 Indexing: {path}")
    print(f"💾 Cache file: {cache_path.name}")
    print(f"{'='*80}")
    
    # Step 1: Create lightweight index
    chunker = LogChunker(str(path), header_pattern)
    sections = chunker.create_index()
    chunker.print_summary()
    
    # Step 2: Determine optimal process count
    cpu_count = os.cpu_count() or 4
    optimal_workers = min(8, cpu_count)
    print(f"\n💡 System has {cpu_count} CPUs, using {optimal_workers} process workers")
    print(f"   2-level parallelism: {optimal_workers} processes × 4 threads = {optimal_workers * 4} concurrent tasks")
    
    # Step 3: Process sections with process pool
    print(f"\n🚀 Processing ALL {len(sections)} sections with optimized analyzer")
    
    results = chunker.process_sections_with_processes(
        analyzer_func=minimal_analyzer,
        max_workers=optimal_workers,
        section_ids=None
    )
    
    # Step 4: Save to cache directory
    output_file = chunker.save_unified_json(
        analysis_results=results,
        output_path=str(cache_path),
        is_multi_analyzer=False,
        demo_format=True
    )
    
    # Step 5: Update registry
    with open(cache_path, 'r') as f:
        cache_data = json.load(f)
    
    _update_registry(path, cache_path, cache_data)
    
    total_elapsed = time.time() - total_start
    
    print("\n" + "="*80)
    print("✅ Indexing Complete!")
    print(f"   Cache file: {cache_path}")
    print(f"   Total sections: {len(sections)}")
    print(f"   ⏱️  Total time: {total_elapsed:.2f}s ({total_elapsed/60:.2f}m)")
    print(f"   ⚡ Throughput: {len(results)/total_elapsed:.2f} sections/second")
    print("="*80)
    
    return cache_path


def search(
    file: Path, 
    keys: list[str], 
    lines: int = 100,
    section: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Search for keywords in a log file with context extraction.
    Does fresh regex search on the original log file for given keywords.
    
    Args:
        file: Path to the original log file
        keys: List of keywords/patterns to search for
        lines: Number of context lines (±N around each match)
        section: Optional section name to limit search (None = search entire file)
        
    Returns:
        List of dicts with search results per keyword:
        [
          {
            "key": "keyword1",
            "uniques": 3,
            "anchors": [
              {"Ln#": "123", "Str": "...", "Cnt": 2, "Log": "..."},
              ...
            ]
          },
          ...
        ]
    """
    # Derive cache path from file
    cache_path = _get_cache_path(file)
    
    if not cache_path.exists():
        raise FileNotFoundError(
            f"Cache not found for {file}. Run index() first.\n"
            f"Expected cache: {cache_path}"
        )
    
    # Load cache to get section metadata
    with open(cache_path, 'r') as f:
        cache_data = json.load(f)
    
    print(f"\n{'='*80}")
    print(f"🔍 Searching: {file.name}")
    print(f"   Keywords: {keys}")
    print(f"   Context: ±{lines} lines")
    if section:
        print(f"   Section filter: {section}")
    print(f"{'='*80}\n")
    
    # Read the original log file
    with open(file, 'r', encoding='utf-8', errors='ignore') as f:
        full_content = f.read()
    
    # Determine which section(s) to search
    sections_to_search = cache_data.get("sections", [])
    
    if section:
        # Filter to specific section by name
        sections_to_search = [
            s for s in sections_to_search 
            if section.lower() in s.get("name", "").lower()
        ]
        if not sections_to_search:
            print(f"⚠️  No sections found matching: {section}")
            return []
        print(f"   Found {len(sections_to_search)} matching section(s)")
    
    # Extract line ranges to search
    if sections_to_search:
        # Parse line ranges
        search_ranges = []
        for s in sections_to_search:
            line_range = s.get("lines", "")
            if "-" in line_range:
                start, end = map(int, line_range.split("-"))
                search_ranges.append((start, end))
        
        # Extract content from line ranges
        lines_list = full_content.split('\n')
        search_content = []
        
        for start, end in search_ranges:
            section_lines = lines_list[start-1:end]
            search_content.append({
                'content': '\n'.join(section_lines),
                'start_line': start,
                'end_line': end
            })
    else:
        # Search entire file
        search_content = [{
            'content': full_content,
            'start_line': 1,
            'end_line': full_content.count('\n') + 1
        }]
    
    # Perform search for each keyword
    results = []
    
    for key in keys:
        print(f"   Searching for: '{key}'")
        
        all_anchors = {}  # message -> {first_line, count, context}
        
        for content_block in search_content:
            content = content_block['content']
            start_line = content_block['start_line']
            
            # Search for keyword
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            content_lines = content.split('\n')
            
            for idx, line in enumerate(content_lines):
                if pattern.search(line):
                    cleaned = line.strip()[:500]
                    if cleaned:
                        abs_line_num = start_line + idx
                        
                        if cleaned not in all_anchors:
                            # Extract context
                            context_start = max(0, idx - lines)
                            context_end = min(len(content_lines), idx + lines + 1)
                            context = '\n'.join(content_lines[context_start:context_end])
                            context = context[:1000] if len(context) > 1000 else context
                            
                            all_anchors[cleaned] = {
                                'first_line': abs_line_num,
                                'count': 1,
                                'context': context
                            }
                        else:
                            all_anchors[cleaned]['count'] += 1
        
        # Build anchors array
        anchors = []
        for message, info in all_anchors.items():
            anchors.append({
                'Ln#': str(info['first_line']),
                'Str': message,
                'Cnt': info['count'],
                'Log': info['context']
            })
        
        # Sort by count descending
        anchors.sort(key=lambda x: x['Cnt'], reverse=True)
        
        result = {
            'key': key,
            'uniques': len(all_anchors),
            'anchors': anchors
        }
        
        results.append(result)
        print(f"      ✓ Found {len(all_anchors)} unique matches")
    
    print(f"\n{'='*80}")
    print(f"✅ Search complete! Found results for {len(results)} keywords")
    print(f"{'='*80}\n")
    
    return results


def get_cache_info(file: Path) -> Optional[Dict]:
    """Get cache information for a file."""
    if not REGISTRY_FILE.exists():
        return None
    
    with open(REGISTRY_FILE, 'r') as f:
        registry = json.load(f)
    
    return registry.get(str(file.absolute()))


def list_cached_files() -> Dict:
    """List all cached files in the registry."""
    if not REGISTRY_FILE.exists():
        return {}
    
    with open(REGISTRY_FILE, 'r') as f:
        return json.load(f)

