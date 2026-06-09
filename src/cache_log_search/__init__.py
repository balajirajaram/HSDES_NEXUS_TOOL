"""
Log Search - Module for log file indexing and keyword searching.

This module provides efficient log file indexing with cached results and
flexible keyword-based searching with context extraction.

Public API - Import ONLY these from this module.
DO NOT directly import from searcher.py or indexer.py.
"""

from .searcher import (
    index,
    search,
    get_cache_info,
    list_cached_files,
    CACHE_DIR,
    REGISTRY_FILE
)

__all__ = [
    'index',
    'search',
    'get_cache_info',
    'list_cached_files',
    'CACHE_DIR',
    'REGISTRY_FILE'
]

__version__ = '1.0.0'
