---
name: crash-parser
description: |
  Parse structured Intel crashdump inputs into a normalized summary for BugScout.
  Use when the input is a crashdump JSON or text dump and you need platform,
  signature, MCA bank, subsystem, and severity extraction before handbook lookup.
---

# Crash Parser

## Purpose

Normalize crashdump input into a compact summary that can feed handbook retrieval
and report generation.

## When to use

- Acronym-like crashdump JSON with MCA banks, signature, or platform fields
- Text crash logs with machine-check bank summaries
- Any workflow that needs structured crash evidence before handbook retrieval

## Typical usage

```python
from src.crashdump_router import parse_crashdump
from pathlib import Path

summary = parse_crashdump(Path("crashdump.json"))
print(summary.to_dict())
```

## Output

The parser extracts:
- platform
- stepping
- crash_signature
- error_type
- subsystem
- primary_bank
- all_banks
- timestamp
- node_id
- socket_id
- raw_signature

## Notes

- Prefer structured JSON if available.
- Fall back to text parsing when JSON fields are incomplete.
- Keep the output stable and machine-readable.
