---
name: crash-parser
description: |
  Normalize a crashdump (ACD/Crash Log JSON or text) or an MCE/MCA bank summary into a
  structured, machine-readable summary for GNR / SRF / CWF (RDT & UPI) triage — platform,
  stepping, signature, MCA bank, subsystem, severity. Use when the input is a crashdump or
  machine-check log and you need structured evidence before handbook/KB lookup.
tools:
  - read_file
  - run_in_terminal
---

# Crash Parser — RDT & UPI

## Purpose
Turn raw crash evidence into a stable summary that feeds `handbook-rag` and the report.

## When to use
- ACD / Crash Log JSON with MCA banks, signature, or platform fields.
- Text crash / serial logs containing machine-check bank summaries.
- Any flow needing structured crash evidence before handbook/KB retrieval.

## Extracted fields
`platform`, `stepping`, `crash_signature`, `error_type`, `subsystem`, `primary_bank`,
`all_banks`, `timestamp`, `node_id`, `socket_id`, `raw_signature`.

## Optional Python helper (bundled)
```python
from src.crashdump_router import parse_crashdump
from pathlib import Path
summary = parse_crashdump(Path("crashdump.json"))
print(summary.to_dict())
```
Prefer structured JSON; fall back to text parsing when fields are incomplete.

## MCA/MCE bank mapping (RDT/UPI quick reference)
Map the decoded bank to the likely subsystem, then hand off to `handbook-rag`:
| Bank(s) | Typical subsystem |
|---|---|
| IFU/DCU/DTLB core banks | Core |
| IMC / memory-controller banks | IMC (DDR/HBM) |
| CHA / LLC banks | CHA / cache-home-agent |
| **UPI / KTI link banks** | **UPI link/PHY (RDT/UPI focus)** |
| IIO / PCIe banks | IIO |

From `MCi_STATUS` capture: valid/UC/PCC/poison bits, error code (MCACOD/MSCOD),
and `MCi_ADDR` when the ADDRV bit is set.

## Output
A single JSON object with the fields above plus a one-line `severity`
(fatal / uncorrected / corrected / info) and a plain-English `summary`. Keep it
machine-readable and stable so downstream skills can consume it.
