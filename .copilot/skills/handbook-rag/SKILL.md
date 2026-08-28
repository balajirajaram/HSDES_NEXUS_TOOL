---
name: handbook-rag
description: |
  Retrieve relevant debug handbook sections for a crash signature, triage record, or
  symptom query.  BugScout ships a bundled handbook at docs/handbooks/ covering ACD,
  Crash Log, and known DMR accelerator failure patterns.  Use when you need handbook-
  backed evidence to ground an MCP query or validate a hypothesis against known root causes.
---

# Handbook RAG

## Purpose

Search handbook markdown files and return the most relevant debug sections for a
crashdump summary, triage symptom, or HSD component query.

## When to use

- ACD/Crash Log triage: need matching debug steps for a crash signature or MCA bank
- Before calling GENI in Phase 3.5 (ACD Handbook Verification): load context for the prompt
- Live-debug Phase LD-2a / LD-4 Step 2 (Conditional C): when component is dsa/iaa/qat/imc/upi
- Need handbook-backed evidence to supplement an MCP analysis

## Bundled handbook (BugScout default)

BugScout ships a pre-built handbook at `docs/handbooks/` covering:

| File | Content |
|---|---|
| `acd_debug_steps.md` | ACD and Crash Log debug process — trigger flow, MCA banks, known failure patterns |
| `acd_handbook_kb.json` | Pre-built keyword KB (loaded at startup, avoids first-run build cost) |

Use `from_default_root()` to load the bundled handbook without specifying a path:

```python
from src.handbook_rag import HandbookRAG

# Load BugScout's bundled ACD/Crash Log handbook
rag = HandbookRAG.from_default_root()
matches = rag.retrieve("DSA hang translation queue deadlock", top_k=4)
```

For triage records (parsed HSD dicts from `parse_hsd_row()`):

```python
rag = HandbookRAG.from_default_root()
matches = rag.triage_retrieve(parsed, top_k=4)
# Returns sections ranked by component + failure modes + symptom keywords
```

For custom handbook paths:

```python
rag = HandbookRAG("/path/to/custom-handbooks")
matches = rag.retrieve("UPI VN0 credit loss HAMVF timeout", top_k=3)
```

## Output

Returns a ranked list (one dict per section) with:
- `rank` — 1-based position
- `title` — section heading from the markdown `##` header
- `source_file` — handbook filename
- `score` — keyword match score (title match = 5 pts; body token match = 1 pt each)
- `content_preview` — first 500 characters of the section body

## Notes

- Lightweight local retriever — no embeddings, no vector store, no LLM calls.
- Ranking: title keyword matches weighted 5×; body token matches 1× each.
- `triage_retrieve()` builds its query from `component`, `accelerator_type`,
  `failure_modes`, and the first 200 characters of `initial_symptom`.
- `HandbookKBBuilder.build_default()` regenerates `acd_handbook_kb.json` from the
  handbook markdown files if content changes.
