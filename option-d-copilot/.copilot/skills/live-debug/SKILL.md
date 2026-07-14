---
name: live-debug
description: |
  Interactive, iterative live-debug loop for an open GNR / SRF / CWF HSD (ALL domains) when
  the engineer has live server / PythonSV access. Reads collected logs, forms ranked
  hypotheses, recommends the next logs/registers to collect WITH exact commands, waits for
  confirmation, and repeats until root cause is confirmed — then emits an HTML debug report.
  Use when asked to "live-debug HSD <id>", "debug HSD <id>", or "interactive debug".
tools:
  - HSDTool
  - HSDIndexTool
  - codesign-debug-search-in-memories
  - codesign-debug-store-memory
  - grep_search
  - read_file
  - create_file
  - run_in_terminal
---

# Live Debug — RDT & UPI

## Trigger
"live-debug HSD <id>", "debug HSD <id>", "interactive debug HSD <id>". Optional inline
params (plain English): `initial logs in <path>`, `max N iterations`, `symptom is: <text>`,
`stepping <gnr-b0|srf-a0|cwf-a0>`.

## Loop contract
Run phases LD-0…LD-5 in order. **After each iteration's findings, STOP and wait for the
engineer's confirmation** before the next iteration. Default `max_iterations = 10`.
Never call MCP tools in a parallel batch.

### LD-0 — Session init
- Extract params from the prompt.
- Fetch the HSD via `HSDTool` (fallback `HSDIndexTool`; `codesign-ask-hsd-agent-mcp` only
  if those fail). Store title, component, stepping, status, initial symptom (NO root cause).
- Derive `cluster`, `stepping`, `cluster_stepping`, `bucket`, `failure_class`
  (see `hsd-triage` Phase 1).
- Load any `initial logs` file; mark those categories already collected.
- KB recall (`codesign-debug-search-in-memories`) to seed hypotheses.

### LD-1 — Testcase context
Identify the failing test / PythonSV sequence from the HSD (command, unit, knobs). Classify:
`pythonsv-manual`, `python-script`, `shell`, or `rocket/atlas`.

### LD-2 — Initial analysis
Analyze the initial symptom + already-collected logs (`log-search`). Ground with
`handbook-rag` when applicable. Produce 2–4 ranked hypotheses, each with confidence
(0.0–1.0) and supporting evidence. Decide which logs/registers to enable next.

### LD-3 — Collect (execute or generate commands)
For each recommended item give the **exact** command, pulled from `docs/command_library.md`
for the matched domain (§ by domain + failure class):
- PythonSV/cscripts reads: `sv.socket<N>.<domain>.<reg>.show()` (UPI PHY/credits, CHA TOR,
  IMC retry, mesh credits, MCi_STATUS/ADDR, punit/PM, PCIe LTSSM, DSA/IAA WQ state…)
- MCA/MCE decode, RPT/serial greps, `dmesg`/`rdmsr`/`mcelog`/`lspci`, BMC `ipmitool`/POST capture.
In `auto`/`local`/`ssh` mode, run via `run_in_terminal`; in `manual` mode, print the
commands for the engineer to run and paste back. Mark each command **confirmed** or
**needs path confirmation** (give the `.show()`/`dir(...)` discovery command).

### LD-4 — Analyze new evidence
Re-search the new logs, update each hypothesis's confidence, confirm or eliminate.
Conditionally invoke validation skills:
- `codesign_validation-rtl-scenario-analysis` — when a hypothesis names specific RTL signals and a model path is available.
- `codesign_validation-constraint-scan` — when the hypothesis implies a chicken bit / config knob / defeature gate.
Present findings + next step + rationale, then **wait for confirmation**.

### LD-5 — Converge & report
When a hypothesis reaches high confidence (≥75%) or the engineer stops:
1. Write-back to the KB (`codesign-debug-store-memory`), tagged confirmed/hypothesis.
2. Fill `templates/auto-hsd-report-template.html` and write
   `output/hsd_<id>_<YYYYMMDD_HHMMSS>/session_report.html` via `create_file`.

## Accuracy checks (before the report is "done")
- **Log-evidence:** every key finding cross-validated against raw logs.
- **Arch-spec:** claims checked against specs/wikis and the HSD DB (WARN acceptable with explanation).

## Guardrails
- No invented registers/commands/HSD IDs. If unsure of a register path, say so and give the
  closest known path + how to confirm. Keep everything GNR/SRF/CWF + stepping scoped.
