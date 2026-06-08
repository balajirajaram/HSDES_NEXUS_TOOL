---
name: log-search
description: Index and search log files with keyword queries and context extraction for interactive log analysis. Used by hsd-triage and live-debug skills for efficient log file analysis.
applyTo:
  - hsd-triage
  - live-debug
tools:
  - read_file
  - run_in_terminal
restrictions:
  directFileAccess: false
  note: "Use gated imports only: from src.cache_log_search import func. DO NOT import from searcher.py or indexer.py directly."
phase: CORE
---

# Log Search

**Purpose**: Enable interactive log analysis with cached indexing, keyword search, and context extraction for efficient log understanding via chat.

**Phase**: CORE (Analysis)

## Quick Start

```python
from src.cache_log_search import index, search, get_cache_info
from pathlib import Path

# 1. Index a log file (one-time operation)
log_file = Path("logs/combinedlog.txt")
cache_path = index(log_file)

# 2. Search for keywords with context
results = search(
    file=log_file,
    keys=["socket_discovery", "error", "Failed"],
    lines=50,  # ±50 lines of context
    section=None  # Search entire file
)

# 3. Process results
for result in results:
    print(f"Keyword: {result['key']}, Matches: {result['uniques']}")
    for anchor in result['anchors'][:3]:
        print(f"  Line {anchor['Ln#']}: {anchor['Str'][:80]}")
```

## API Functions

### `index(path: Path, header_pattern: str = DEFAULT_PATTERN) -> Path`

**Purpose**: Index a log file and cache results for fast searching

**Parameters**:

- `path`: Path to log file
- `header_pattern`: Regex pattern to match section headers (default: asterisk-based headers)

**Returns**: Path to cached JSON file

**Example**:

```python
cache_path = index(Path("logs/combinedlog.txt"))
# Creates cache with SHA256 hex digest filename
```

**Performance**: ~7-10 sections/second, 2-level parallelism (processes + threads)

---

### `search(file: Path, keys: list[str], lines: int = 100, section: Optional[str] = None) -> list[dict]`

**Purpose**: Search for keywords with context extraction

**Parameters**:

- `file`: Path to original log file
- `keys`: List of keywords/patterns to search for
- `lines`: Number of context lines (±N around each match, default: 100)
- `section`: Optional section name to limit search (None = entire file)

**Returns**: List of results per keyword:

```python
[
  {
    "key": "socket_discovery",
    "uniques": 127,  # Unique matching lines
    "anchors": [
      {
        "Ln#": "413990",  # Line number
        "Str": "03-08 15:21:socket_discovery :1822 :DEBUG ...",  # Matching line
        "Cnt": 5,  # Count of this exact line
        "Log": "... ±N lines of context ..."  # Context window
      },
      ...
    ]
  },
  ...
]
```

**Example**:

```python
# Search entire file
results = search(log_file, ["error", "warning"], lines=50)

# Search specific section only
results = search(log_file, ["timeout"], lines=30, section="socket_discovery")
```

---

### `get_cache_info(file: Path) -> Optional[Dict]`

**Purpose**: Get cache information for a file

**Parameters**:

- `file`: Path to log file

**Returns**: Cache metadata or None if not cached:

```python
{
  "cache_file": "/path/to/cache/abc123.json",
  "hex_digest": "abc123...",
  "indexed_at": "2026-06-04T12:34:56",
  "total_sections": 228,
  "file_size": 131564201
}
```

**Example**:

```python
info = get_cache_info(log_file)
if info:
    print(f"Already cached with {info['total_sections']} sections")
else:
    print("Not cached yet, indexing required")
```

---

### `list_cached_files() -> Dict`

**Purpose**: List all cached files in the registry

**Returns**: Dictionary mapping file paths to cache info

**Example**:

```python
cached = list_cached_files()
for file_path, info in cached.items():
    print(f"{Path(file_path).name}: {info['total_sections']} sections")
```

## Integration

**Used by skills**: hsd-triage, live-debug

**Typical workflow**:

1. **Index**: Index log files from debug session or HSD ticket logs
2. **Search**: Query for specific error patterns, keywords, or stack traces
3. **Analyze**: Extract context around matches for hypothesis formation
4. **Report**: Integrate findings into debug reports or HSD triage notes

**Common use in BugScout**:
- HSD triage: Search for known error patterns in attached logs
- Live debug: Iteratively search logs as hypotheses evolve
- Root cause analysis: Find related errors across multiple log sections

## Use Cases

| Use Case             | Keywords                                | Lines | Section              |
| -------------------- | --------------------------------------- | ----- | -------------------- |
| Error investigation  | `["error", "exception", "failed"]`      | 100   | None                 |
| Function tracing     | `["socket_discovery", "acode manager"]` | 50    | None                 |
| Section analysis     | `["timeout", "retry"]`                  | 30    | `"socket_discovery"` |
| Critical events      | `["CRITICAL", "FATAL"]`                 | 150   | None                 |
| Multi-pattern search | `["NullPointer", "Connection.*failed"]` | 80    | None                 |

## Chat Interaction Examples

### Example 1: First-Time Analysis

```
User: "What socket_discovery errors are in the log?"

Agent:
1. Checks cache: get_cache_info(logs/combinedlog.txt)
2. Indexes if needed: index(logs/combinedlog.txt)
3. Searches: search(file, keys=["socket_discovery", "error"], lines=50)
4. Responds: "Found 127 socket_discovery entries. Most common:
   Line 413990 (5 times): 'socket_discovery :1822 :DEBUG - Connection timeout'"
```

### Example 2: Multi-Keyword Investigation

```
User: "Find all critical failures"

Agent:
1. Searches: search(file, keys=["Failed", "CRITICAL", "exception"], lines=100)
2. Responds: "Found 3 keywords: Failed (45), CRITICAL (12), exception (23).
   Top issue: Line 234567 'CRITICAL: Database connection pool exhausted'"
```

### Example 3: Section-Specific Deep Dive

```
User: "What's in the socket_discovery section?"

Agent:
1. Searches: search(file, keys=[".*"], lines=20, section="socket_discovery")
2. Responds: "45 entries in socket_discovery (lines 410000-425000):
   • 15 connection attempts
   • 8 timeouts
   • 3 successful discoveries"
```

## Error Handling

| Error                                   | Cause                | Resolution                                 |
| --------------------------------------- | -------------------- | ------------------------------------------ |
| `FileNotFoundError: Cache not found`    | File not indexed     | Run `index(file)` first                    |
| `FileNotFoundError: Log file not found` | Invalid path         | Check file path exists                     |
| `ValueError: No sections found`         | Wrong header pattern | Adjust `header_pattern` parameter          |
| Empty `anchors` array                   | No keyword matches   | Try different keywords or broader patterns |

## Performance

- **Indexing**: ~7-10 sections/second (125MB file with 228 sections)
- **Searching**: Fast regex search (sub-second for most queries)
- **Cache**: Persistent across sessions, stored in `src/cache_log_search/cache/` with SHA256 naming
- **Parallelism**: 2-level (ProcessPoolExecutor + ThreadPoolExecutor)

**Typical timing**:

- Index 228 sections: ~30-40 seconds
- Search 3 keywords: ~2-5 seconds
- Get cache info: <0.1 seconds

## Cache Structure

```
src/cache_log_search/
├── cache/
│   ├── abc123...json     # Indexed log data (SHA256 hex digest naming)
│   ├── def456...json
│   └── registry.json     # Cache registry tracking all indexed files
└── ...                   # Implementation files
```

## Restrictions

⚠️ **CRITICAL - Agents MUST follow**:

- ✅ USE: `from src.cache_log_search import index, search`
- ❌ DO NOT: `from src.cache_log_search.searcher import index`
- ❌ DO NOT: `import src.cache_log_search.indexer`
- ❌ DO NOT: Directly read/write cache files
- ❌ DO NOT: Manually manipulate registry.json

**Enforcement**: All access via `__init__.py` gated exports only. Direct imports from `searcher.py` or `indexer.py` should fail or be rejected.

## Example Terminal Commands

For agent execution via `run_in_terminal`:

**Index a log file**:

```python
python -c "from src.cache_log_search import index; from pathlib import Path; print(index(Path('logs/combinedlog.txt')))"
```

**Search for keywords**:

```python
python -c "from src.cache_log_search import search; from pathlib import Path; import json; results = search(Path('logs/combinedlog.txt'), ['socket_discovery'], 50); print(json.dumps(results, indent=2))"
```

**Check cache**:

```python
python -c "from src.cache_log_search import get_cache_info; from pathlib import Path; import json; print(json.dumps(get_cache_info(Path('logs/combinedlog.txt')), indent=2))"
```

## Example Usage

Run the example script:

```powershell
cd src/cache_log_search
python example_usage.py
```

The example demonstrates:

- ✅ Indexing log files
- ✅ Searching with keywords
- ✅ Section-specific filtering
- ✅ Cache management

## Agent Behavior Requirements

When user asks about log file contents:

1. ✅ Check cache status: `get_cache_info(file)`
2. ✅ Index if needed: `index(file)`
3. ✅ Search with keywords: `search(file, keys, lines, section)`
4. ✅ Present results conversationally
5. ❌ DO NOT directly read log files
6. ❌ DO NOT recreate search/index logic
7. ❌ DO NOT bypass caching system
