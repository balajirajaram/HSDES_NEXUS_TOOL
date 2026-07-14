---
name: log-search
description: |
  Index and search post-silicon debug logs (RPT, .rpt.gz, .elog.gz, serial/BIOS, PythonSV
  dumps) for GNR / SRF / CWF triage. Copilot-native by default (grep_search + read_file);
  optional Python accelerator (src/cache_log_search) for very large logs.
  Use when asked to "search logs", "grep the log", "what errors are in <log>", or from
  hsd-triage / live-debug.
tools:
  - grep_search
  - read_file
  - run_in_terminal
---

# Log Search — RDT & UPI

## Purpose
Fast keyword/regex search with surrounding context across post-silicon logs, so hypotheses
can be grounded in raw evidence.

## Default path — Copilot-native (zero setup)
1. Locate logs with `file_search` / `grep_search`.
2. For `.gz` logs, decompress first (PowerShell): `Get-Content <file>` after
   `Expand-Archive`, or use `zgrep`/`zcat` if available in your shell.
3. Search with `grep_search` (set `isRegexp` appropriately). Use alternation to find
   multiple tokens at once, e.g. `error|fail|fatal|MCE|MCA|CRC|timeout|hang`.
4. Read ±N lines of context around hits with `read_file`.

### RPT field extraction (used to derive KB params)
From the failure's `.rpt` / `.rpt.gz`:
- `BUCKET NAME:` → `bucket`
- `CLUSTER:` → cluster
- `-stepping` in `TRIAGE CMD-LINE:` (or `PROJECT-STEPPING:`) → stepping
- `TEST RES PATH:` → failure_path
Combine cluster + stepping → `cluster_stepping`.

## Optional accelerator — Python cache index (large logs)
For multi-hundred-MB logs, use the bundled indexer for cached, repeatable search:
```python
from src.cache_log_search import index, search, get_cache_info
from pathlib import Path
f = Path("logs/combinedlog.txt")
if not get_cache_info(f): index(f)          # one-time index
results = search(f, keys=["UPI","CRC","credit","timeout"], lines=50)
```
`search` returns per-keyword `anchors` with line number, matched line, count, and a
±N-line context window. Do NOT import from `searcher.py`/`indexer.py` directly — use the
gated `from src.cache_log_search import ...` API.

## Common RDT/UPI search sets
| Goal | Keywords |
|---|---|
| UPI link/PHY | `UPI\|KTI\|PHY\|DRIFT\|retrain\|L0p\|credit\|VN0\|CRC` |
| MCE/MCA | `MCE\|MCA\|MCi_STATUS\|bank\|poison\|UCNA\|SRAR` |
| Hang / reset | `hang\|hung\|reset\|POST\|PC:0x\|watchdog\|3-strike` |
| Init/degradation | `KitPortDisable\|degrad\|topology\|link disable\|BIOS knob` |

## Output
Report per keyword: match count, top matching lines (line #, text), and the context window
you used to draw conclusions. Feed confirmed evidence into hypothesis ranking / the report.
