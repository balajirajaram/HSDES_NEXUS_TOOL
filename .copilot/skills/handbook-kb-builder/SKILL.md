---
name: handbook-kb-builder
description: |
  Build a local knowledge base from handbook markdown files for crashdump and
  debug-step retrieval. Use when you need a repeatable, offline KB artifact from
  handbook sources.
---

# Handbook KB Builder

## Purpose

Mine handbook markdown files into a JSON knowledge base that captures likely
causes, keywords, and source sections.

## Typical usage

```python
from src.handbook_kb_builder import HandbookKBBuilder

builder = HandbookKBBuilder("debug_handbooks/GNR-debug-handbooks")
kb = builder.build("output/handbook_kb.json")
```

## Output

The KB contains:
- handbook root
- section_count
- entries with source_file, title, keywords, and extracted causes

## Notes

- This is a lightweight, local first pass.
- Use it to support crashdump-oriented workflows before any MCP verification.
