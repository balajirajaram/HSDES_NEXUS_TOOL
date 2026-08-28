# Log Search Skill

Fast log file indexing and keyword searching with context extraction for interactive analysis.

## 📖 Documentation

**Complete skill documentation**: See [.copilot/skills/log-search/SKILL.md](../../.copilot/skills/log-search/SKILL.md)

## 🚀 Quick Start

```python
from src.cache_log_search import index, search
from pathlib import Path

# Index a log file
log_file = Path("logs/combinedlog.txt")
cache_path = index(log_file)

# Search for keywords
results = search(log_file, ["error", "failed"], lines=50)
for result in results:
    print(f"{result['key']}: {result['uniques']} matches")
```

## 📋 API Functions

- **`index(path)`** - Index a log file with caching
- **`search(file, keys, lines, section)`** - Search with context extraction
- **`get_cache_info(file)`** - Check cache status
- **`list_cached_files()`** - List all cached files

## 🎯 Key Features

- ✅ Cached indexing (SHA256 hex digest naming)
- ✅ Keyword search with ±N lines context
- ✅ Section filtering
- ✅ Interactive chat analysis
- ✅ 2-level parallelism (processes + threads)
- ✅ Persistent cache with registry

## 📁 Structure

```
src/cache_log_search/
├── __init__.py          # Gated API exports
├── searcher.py          # Search implementation
├── indexer.py           # Index implementation
├── example_usage.py     # Usage examples
└── cache/               # Cache storage
```

## 🔐 Gated Access

**Always use gated imports**:
```python
✅ from src.cache_log_search import index, search
❌ from src.cache_log_search.searcher import index  # DO NOT
```

## 📊 Performance

- Indexing: ~7-10 sections/second
- Searching: Sub-second for most queries
- Cache: Persistent across sessions

## 🧪 Example Usage

```powershell
cd src/cache_log_search
python example_usage.py
```

---

**For complete documentation, examples, and integration details, see [.copilot/skills/log-search/SKILL.md](../../.copilot/skills/log-search/SKILL.md)**
