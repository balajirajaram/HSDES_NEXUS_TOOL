# Agent Specification — Auto HSD Analyser (GNR / SRF / CWF)

This is the full, human-readable specification behind
[../prompts/auto-hsd-analyser.prompt.md](../prompts/auto-hsd-analyser.prompt.md).
The `.prompt.md` file is the runnable version; this document explains the intent so
teammates can review and extend it.

## Purpose
Automate first-pass triage of RDT and UPI failure signatures on GNR, SRF, and CWF while
continuously learning from every case it handles.

## The two knowledge sources
1. **Learned Knowledge Base (KB)** — persistent memory of resolved cases. Queried first.
2. **HSDES** — authoritative fallback and source of truth for conflict resolution.

## Self-learning loop
```
Step 0  RECALL      -> search KB for the symptom signature, score confidence
Step 1  DECIDE      -> High = KB-first; Medium/Low/None = HSDES then merge
Step 2  INVESTIGATE -> target-HSD analysis + similar-HSD search
Step 3  WRITE-BACK  -> store/update KB entry (confirmed vs hypothesis)
Step 4  REPORT      -> explain how the KB was used and how it grew
```

## Report contract (sections A–H)
| Section | Content |
|---------|---------|
| A | Target HSD summary (title, component, stepping, status, owner, failure signature) |
| B | KB recall result (confidence + matched learned cases) |
| C | Similar HSDs table (ID, Source KB/HSDES, similarity reason, root cause, status) |
| D | Ranked root-cause hypotheses with supporting evidence |
| E | Ordered debug steps with exact PythonSV commands + decision branches |
| F | Data to request/collect (RPT fields, ucode/BIOS rev, cluster, bucket) |
| G | Learning summary (KB entry created/updated + confidence tag) |
| H | Known-issue verdict (known + HSD cite, or new sighting) |

## Guardrails
- No fabricated HSD IDs, register names, root causes, or commands.
- HSDES wins all conflicts; stale KB entries are corrected and re-tagged.
- Every entry tagged `confirmed` or `hypothesis`, with provenance + timestamp.
- Entries are GNR/SRF/CWF-scoped and stepping-aware.

See [KB_SCHEMA.md](KB_SCHEMA.md) for the exact KB entry structure.
