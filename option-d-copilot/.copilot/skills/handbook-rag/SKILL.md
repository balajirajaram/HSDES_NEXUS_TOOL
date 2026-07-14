---
name: handbook-rag
description: |
  Self-learning knowledge base + handbook & command retrieval for GNR / SRF / CWF across
  ALL domains. Recalls prior resolved cases from the persistent co-design memory KB, grounds
  hypotheses in the bundled debug handbooks, and pulls the exact next-step commands from the
  all-domain command library. Use before ranking root causes, before an MCP query, when
  building a data-collection plan, and to write confirmed findings back into the KB.
tools:
  - codesign-debug-search-in-memories
  - codesign-debug-get-memory
  - codesign-debug-store-memory
  - read_file
---

# Handbook RAG + Learning KB — GNR / SRF / CWF (all domains)

## Purpose
Two grounding sources, queried in priority order:
1. **Learning KB** — persistent, self-growing store of previously resolved cases
   (symptom signature → similar HSDs → root cause → debug steps → resolution), held in
   the co-design debug memory store.
2. **Bundled handbook** — `docs/handbooks/` markdown (RDT/UPI known patterns, MCA/MCE
   banks, UPI link/credit failures) for offline grounding when the KB is empty.

## When to use
- Before Phase 4 (root-cause ranking) in `hsd-triage`, for ANY domain.
- When building the next-step data-collection command plan (Phase 5 / 5b).
- Live-debug Phase LD-2a / LD-4 when the symptom includes hang / crash / fatal / MCA / CRC /
  credit / corruption / throttle keywords.
- To write a confirmed finding back into the KB.

## KB recall  (codesign-debug-search-in-memories)
REQUIRED params — never empty:
- `cluster_stepping` = `{cluster}_{stepping}` (e.g. `upi_gnr-ap`, `rdt_srf-a0`).
- `bucket` = HSD failure bucket, or normalized `<CLASS>::<unit>::<signature>`.
- `query` = key symptom terms.

Report confidence:
| Matches | Confidence |
|---|---|
| Exact signature + same unit/stepping | High |
| Same unit, related signature | Medium |
| Loose keyword overlap | Low |
| "No memories to search." | None |

Use `codesign-debug-get-memory` to expand a matched entry (root cause + action items).

## Handbook retrieval  (read_file over docs/)
When the KB is None/Low, read the handbooks and rank sections by keyword overlap with
`{cluster}` + `{failure_class}` + symptom terms (title match weighted heaviest). Return the
top 3–4 section titles + previews as grounding evidence. Sources:
- `docs/handbooks/rdt_upi_debug_steps.md` — RDT/UPI patterns.
- `docs/handbooks/acd_debug_steps.md` — ACD/Crash-Log/MCA patterns.
- `docs/command_library.md` — **all-domain** command catalog; pull the § for the matched
  domain + failure class to build the exact next-step data-collection commands.

## KB write-back  (codesign-debug-store-memory)
Store/update after a case is analyzed. Required: `bucket`, `cluster_stepping`, `title`,
`symptom`, `root_cause`. Recommended: `tags`, `error_message`, `action_items` (numbered
diagnostic steps with exact commands).
- Tag each entry **confirmed** (from data) or **hypothesis**.
- If a matching entry exists, UPDATE it (reinforce / correct) — do not duplicate.
- **HSDES is the source of truth**; overwrite stale KB entries and note the correction.

## Guardrails
- Never store invented HSD IDs, root causes, or commands.
- Keep entries GNR/SRF/CWF-scoped and stepping-aware.
