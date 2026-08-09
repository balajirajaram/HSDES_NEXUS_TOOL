---
name: live-debug
description: |
  Interactive live debug agent for HSD sightings where the engineer has live server access.
  Drives an iterative loop: enable logs → run test → collect output → analyze → form hypotheses
  → present findings → wait for confirmation → repeat until root cause found.
  Handles PythonSV and non-PythonSV testcases (custom tools, Python scripts, shell commands).
  Use when asked to "live-debug HSD", "debug HSD <id>", "interactive debug", or "run live debug session".
---

# HSD Live Debug Agent

## Trigger

Say any of the following — all parameters are **optional** and expressed in plain English:

```
live-debug HSD <id>
debug HSD <id>
interactive debug HSD <id>
run live debug session for <id>
```

All session parameters can be included inline in the same prompt using natural language:

| Parameter | NLP example |
|-----------|-------------|
| **HSD ID** (required) | `"live-debug HSD 14027419708"` |
| **Execution mode** | `"using SSH"` / `"run commands locally"` / `"manual mode"` / `"auto"` |
| **Server hostname** | `"on server mylab.intel.com"` / `"via mylab.intel.com"` |
| **SSH username** | `"as user jsmith"` / `"ssh user jsmith"` |
| **Max iterations** | `"max 5 iterations"` / `"stop after 3 rounds"` |
| **Initial logs path** | `"initial logs in /path/to/initial_logs.json"` / `"logs already collected at ..."` |
| **Initial symptom override** | `"symptom is: <text>"` |

**Full examples:**

```
live-debug HSD 14027419708 using SSH on server mylab.intel.com as user smeenak1

debug HSD 14027419708 run commands locally, max 5 iterations

live-debug HSD 14027419708 manual mode, initial logs in C:\debug\initial_logs.json

interactive debug HSD 14027419708 via mylab.intel.com ssh user jdoe, stop after 3 rounds, symptom is: hang during DMA operation
```

The agent **extracts all parameters from the prompt** before starting Phase LD-0.
Parameters not specified fall back to defaults: `execution_mode=manual`, `max_iterations=10`.

## What This Skill Does

Drives an **iterative, interactive debug loop** for a single open HSD. Unlike the batch
triage skill (which recommends logs from symptoms alone), this skill:

1. Analyzes logs **already collected** (initial state)
2. Decides what to **enable and collect next** based on hypotheses
3. **Executes** log collection (or generates commands for manual execution)
4. **Analyzes new evidence** with GENI and Co-Design
5. **Presents findings** + next steps with rationale to the user
6. **Waits for confirmation** before proceeding
7. **Repeats** until root cause is confirmed or user stops the session

If the CLI bootstrap wrote `session_init.json`, the runner reads that file first and merges it with any prompt-derived parameters. The `--initial-logs` payload is also stored in session state and surfaced in the session report, so bootstrap evidence stays available throughout the session.

---

## Inputs

Parameters are resolved in this priority order: **NLP prompt → `session_init.json` (CLI) → HSD/NGA MCP → defaults**.

| Field | NLP phrase | CLI equivalent | Default |
|-------|-----------|----------------|---------|
| `hsd_id` | `"HSD 14027419708"` (required) | `--hsd-id` | — |
| `execution_mode` | `"using SSH"` / `"run locally"` / `"manual"` / `"auto"` | `--execution-mode` | `manual` |
| `server` | `"on server mylab.intel.com"` / `"via mylab.intel.com"` | `--server` | — |
| `ssh_user` | `"as user jsmith"` / `"ssh user jsmith"` | `--ssh-user` | OS user |
| `max_iterations` | `"max 5 iterations"` / `"stop after 3 rounds"` | `--max-iterations` | `10` |
| `initial_logs_path` | `"initial logs in /path/to/file.json"` | `--initial-logs` | — |
| `initial_symptom` | `"symptom is: <text>"` | (in `--initial-logs` file) | from HSD MCP |
| `testcase_name` | — | (in `--initial-logs` file) | from NGA MCP |
| `testcase_command` | — | (in `--initial-logs` file) | from NGA MCP |
| `enrichment_mode` | `"raw blind"` / `"phase-a only"` / `"no enrichment"` | `--enrichment-mode` | `phase-b` |
| `exclude_hsd_ids` | `"exclude HSD 15018590736"` | `--exclude-hsd` (repeatable) | `[]` |

> **Enrichment default is `phase-b`** — MCP enrichment runs automatically for all new sessions.
> Pass `--enrichment-mode none` (or say "raw blind run") to disable enrichment for a pure
> Phase A baseline evaluation. Always pair with `--exclude-hsd` for every HSD used to design
> the repro script (ground truth labels must not feed BugScout).

> **Bootstrap logs are persisted.** When `--initial-logs` is provided, the session runner stores the collected logs in session state and includes them in the generated markdown/HTML reports.

> **CLI session pre-init is optional.** If `session_init.json` exists (created by
> `python parse_and_triage.py --mode live-debug --hsd-id <id> [options]`),
> the agent loads it as the base configuration; NLP parameters override any field in it.
> If the file does not exist, the agent runs entirely from NLP-extracted parameters.

---

## AUTONOMOUS EXECUTION INSTRUCTIONS

When triggered, execute phases LD-0 through LD-5 **automatically in order**.
**Stop after each iteration's Phase LD-4 step 5 to present findings and wait for user confirmation.**
Do NOT proceed to the next iteration without explicit user go-ahead.

**Validation skills used conditionally** (do NOT invoke unless conditions are met):
- `codesign_validation-rtl-scenario-analysis` — in Phase LD-2c and LD-4 Step 3 (Conditional A): only when `model_path` is available and hypothesis names specific RTL signals
- `codesign_validation-constraint-scan` — in Phase LD-4 Step 3 (Conditional B): only when hypothesis language implies a chicken bit, config knob, or defeature gate
- `handbook-rag` — in Phase LD-2a and LD-4 Step 2 (Conditional C): when `component` contains `dsa`, `iaa`, `qat`, `mce`, `imc`, or `upi` AND initial symptom includes hang, crash, fatal, or MCA keywords. Use `HandbookRAG.from_default_root().triage_retrieve(parsed)` to retrieve the top 4 matching handbook sections and include them in the GENI analysis prompt to ground the hypothesis in known ACD root-cause patterns.

---

### Phase LD-0 — Session Initialization

**Step LD-0a**: Extract parameters from the user's NLP prompt.

Parse the trigger phrase and extract the following fields using pattern matching:

| Pattern to match | Field | Example |
|---|---|---|
| `HSD \d+` | `hsd_id` | `HSD 14027419708` → `"14027419708"` |
| `(using SSH\|via SSH\|ssh mode)` | `execution_mode = "ssh"` | `"using SSH"` |
| `run.*local(ly)?` | `execution_mode = "local"` | `"run locally"` |
| `manual mode` | `execution_mode = "manual"` | `"manual mode"` |
| `auto(matic)? (mode\|execution)?` | `execution_mode = "auto"` | `"auto"` |
| `(on server\|via) ([\w.\-]+)` | `server` | `"on server mylab.intel.com"` |
| `(as user\|ssh user) (\w+)` | `ssh_user` | `"as user jsmith"` |
| `(max\|stop after) (\d+) (iter\|round)` | `max_iterations` | `"max 5 iterations"` |
| `initial logs in (.+?)(?:\s|$)` | `initial_logs_path` | `"initial logs in /tmp/logs.json"` |
| `symptom is[:\s]+(.+)` | `initial_symptom_override` | `"symptom is: hang during DMA"` |

Store all extracted values as the **NLP parameter set**.

**Step LD-0a.5**: Auto-fetch HSD attachments (hsd-log-fetcher).

Before loading any logs, check whether `HSD_Logs_Details/HSD_<hsd_id>/` already contains files.
If it is **empty or does not exist**, run:

```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python hsd_log_fetcher.py <hsd_id>
```

- If files are downloaded successfully, set `initial_logs_path` to the output directory
  (overrides any `--initial-logs` absence) so LD-0c can reference the files.
- If the ticket has **no attachments**, continue without blocking — note
  "No HSD attachments found; proceeding with manual/SSH log collection" in the session report.
- If auth fails (Kerberos error), skip this step and remind the user:
  ```
  Kerberos ticket expired. Run: kinit <idsid>
  Proceeding without HSD attachment pre-fetch.
  ```
- If `HSD_Logs_Details/HSD_<hsd_id>/` already has files, skip this step entirely.

**Step LD-0a.6**: Auto-parse StatusScope reports (statusscope-parser).

After attachments are fetched, check whether a StatusScope `*-intel-svtools-report-v1.json`
is present and, if so, extract its insights into the initial evidence:

```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python statusscope_ingest.py --dir "HSD_Logs_Details\HSD_<hsd_id>"
```

- If no report is found the command exits non-zero with "No StatusScope report found" —
  **treat this as benign and continue** (StatusScope data is optional).
- If `initial_logs_path` points at a directory or zip, also scan it (`--dir`/`--zip`).
- If a report is found:
  - Add its **priority-sorted insights** (`HW.KNOWN_ISSUE` / `HW.CFG.ERR` first, then
    `SW.FW.ERR`) and any decoded **error / sideband / mca** tables to the iteration-0 evidence.
  - Mark the collector categories it already covers (namednodes, error, sideband, mca) as
    **already collected** so the debug loop does not re-request them.
  - Record its **HSD links** as correlation candidates.

**Step LD-0b**: Load CLI `session_init.json` if it exists (optional baseline).

Check if `output/live_debug_<hsd_id>_*/session_init.json` exists (created by CLI):
```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\project-c3\hsd-triage"
python -c "
import json
from pathlib import Path
hsd_id = '<hsd_id>'
hits = sorted(Path('output').glob(f'live_debug_{hsd_id}_*/session_init.json'))
if hits:
    print(hits[-1].read_text(encoding='utf-8'))
else:
    print('{}')
"
```

**Merge rule**: Start with `session_init.json` fields as base, then **override with any NLP-extracted parameter** that was explicitly present in the prompt. NLP always wins over the file.

If neither source provides a value, apply defaults:
- `execution_mode` → `"manual"`
- `max_iterations` → `10`
- `server`, `ssh_user`, `initial_logs_path` → empty/none

Create session state in memory: `session_id = <hsd_id>_<YYYYMMDD_HHMMSS>`.

**Step LD-0c**: Load initial logs if `initial_logs_path` is set.

```bash
python -c "
import json
data = json.loads(open('<initial_logs_path>', encoding='utf-8').read())
print(json.dumps(data.get('initial_logs_collected', []), indent=2))
"
```

**Step LD-0d**: Fetch HSD details via Co-Design HSD MCP.

Call `mcp_co-design_codesign-ask-hsd-agent`:
```
Fetch HSD ID: {hsd_id}
tenant_subjects: ["sighting_central.sighting", "server_platf.bug"]

Return as JSON:
{
  "hsd_id": "...",
  "title": "...",
  "component": "...",         // e.g. hw.dsa, hw.iaa, sw.driver.idxd
  "status": "...",
  "priority": "...",
  "initial_symptom": "...",   // first-reported symptom, NO root cause
  "description_summary": "...",
  "related_hsds": []          // IDs of similar past HSDs if mentioned
}
```

Store as `session.hsd_context`. If HSD is inaccessible, use title/symptom from `--initial-logs`.

**Step LD-0e**: Consolidate initial logs.

Merge logs from two sources (if present):
- `initial_logs_collected` from `initial_logs_path` file (loaded in LD-0c)
- `initial_logs_collected` from `session_init.json` (loaded in LD-0b)
- StatusScope insights/tables from Step LD-0a.6 (if any)

Record the merged set as:
- `iteration_0_logs = <merged list>`
- Mark each category as already collected (do NOT re-request in subsequent iterations)

---

### Phase LD-1 — Test Case Context (NGA MCP)

**Same as existing Phase 2 in skill.md** — use `mcp_intel_ngai_plan_and_execute` to resolve
the NGA UUID to TestLine details.

**Additional step for non-PythonSV tests**: After NGA lookup, classify testcase type:

| Signal | Testcase Type |
|--------|--------------|
| Command contains `rocket` or `atlas` | `rocket` |
| Command contains `python` or ends in `.py` | `python-script` |
| Command is a shell binary/script (no rocket/python) | `shell` |
| NGA step Type = `Test` with `CommandType = Script` | `shell` |
| `nga_os` = `Svos` + no NGA steps | `pythonsv-manual` |

Store as `session.testcase_type`. This controls which enablement commands the agent generates.

---

### Phase LD-2 — Initial Analysis

**MCP Tools**: `mcp_intel_geni_pr_DebugAssistantAgentTool` + `mcp_co-design_codesign-ask-hsd-agent`

**Step LD-2a** — GENI: analyze initial symptom + any initial logs.

Call `mcp_intel_geni_pr_DebugAssistantAgentTool`:
```
Component: {component}
HSD ID: {hsd_id}
Initial symptom: {initial_symptom}
Testcase: {testcase_name} ({testcase_command})
Testcase type: {testcase_type}

{if initial_logs_collected}
Logs already collected:
{for each log: category + content_snippet}
{endif}

You are starting a live debug session. No root cause is known.

1. What does the initial symptom suggest about the failure class?
   (hang / error / corruption / init-failure / performance / other)
2. Based on ANY logs already collected, what do they reveal?
   What questions do they leave unanswered?
3. Provide a ranked list of 2–4 initial hypotheses (most likely first).
   For each: hypothesis statement, confidence (0.0–1.0), supporting evidence.
4. What log categories should be enabled BEFORE the next test run?
   (Standard baseline from taxonomy + testcase-specific overrides)

Output as JSON:
{
  "failure_class": "...",
  "initial_analysis": "...",
  "hypotheses": [
    {"statement": "...", "confidence": 0.N, "evidence": "..."},
    ...
  ],
  "logs_to_enable": [
    {"category": "...", "enablement_commands": ["..."], "purpose": "..."},
    ...
  ]
}
```

**Step LD-2b** — Co-Design HSD: find related past HSDs.

Call `mcp_co-design_codesign-ask-hsd-agent`:
```
Component: {component}, symptom: {initial_symptom}
Find past HSDs with similar symptoms in this component.
Return: hsd_id, symptom_match, root_cause, fix_pattern, logs_that_helped
```

Store `related_hsds` list for Phase LD-5 report.

**Step LD-2c** — RTL Scenario Analysis *(conditional — skip if `model_path` not available)*

**Condition**: Run this step ONLY if **both** are true:
1. A VSCode workspace is open with an RTL model (`model_path` is inferrable from the workspace root)
2. The top hypothesis from Step LD-2a references specific RTL signals, register names, or microarchitectural state

**If condition met**, invoke the `codesign_validation-rtl-scenario-analysis` skill with:
- `ip` = `{component}` (e.g., `dsa`, `iaa`, `idxd`)
- `model_path` = inferred workspace root
- In place of coverage point identifiers, pass the signal/register names extracted from the top hypothesis as the search seed
- Skip the skill's "Mandatory Context Gathering" blocking step — the RTL context is the hypothesis statement

```
Invoke skill: codesign_validation-rtl-scenario-analysis
ip: {component}
model_path: {workspace_root}
Context: Top hypothesis is "{top_hypothesis.statement}".
          Extract RTL signal names from this hypothesis and trace them 3–5 levels deep.
          Build the cycle-level scenario required for this failure mode to occur.
```

Store the returned RTL scenario as `session.rtl_scenario`. Use it in Phase LD-3 to refine the enablement plan (target specific modules/signals) and in Phase LD-4 to focus log collection on the predicted signal chain.

If condition is NOT met: set `session.rtl_scenario = null`. The debug loop proceeds without it.

---

### Phase LD-3 — Log Enablement Plan

**MCP Tool**: `mcp_intel_geni_pr_DebugAssistantAgentTool`

Present the enablement plan to the user BEFORE any test run:

```
══════════════════════════════════════════════════
 Phase LD-3: Log Enablement Plan
 HSD: {hsd_id} | Test: {testcase_name}
══════════════════════════════════════════════════

The following logs should be ENABLED before running the test:

STANDARD BASELINE (always enable):
{for each standard enablement step: command + purpose}

TEST-SPECIFIC ({testcase_type}):
{for each test-specific step: command + purpose}

To enable all of the above, run:
  (execution_mode = manual)  → commands printed below for manual execution
  (execution_mode = local)   → agent will run them automatically
  (execution_mode = ssh)     → agent will SSH to {server} and run them

[Print all enablement commands in a single code block]

After enabling, run the testcase:
  {testcase_command}

Then collect the initial log set (commands in Phase LD-4 Iteration 1).
══════════════════════════════════════════════════
```

**Testcase-type-specific enablement**:

| Testcase Type | Enablement Actions |
|---|---|
| `rocket` / `atlas` | Add `--loglevel debug`, `--verbose` flags; enable kernel ftrace for iommu/dma events |
| `python-script` | Add `--log-level DEBUG` or set `LOG_LEVEL=DEBUG`; enable driver dynamic debug |
| `shell` | Wrap with `script` or `unbuffer ... | ts`; enable `dynamic_debug` for relevant modules |
| `pythonsv-manual` | PythonSV `sv.` commands run live — no enablement needed; just collect registers post-hang |
| `custom-tool` | GENI infers from tool name + flags; ask user if unknown |

If `execution_mode` is NOT `manual`, run the enablement commands via the adapter before proceeding.

---

### Phase LD-4 — Iterative Debug Loop

**Repeat the following steps until user says "stop", "root cause confirmed", or max_iterations reached.**

---

#### LD-4 Step 1: Recommend next log collection

Call `mcp_intel_geni_pr_DebugAssistantAgentTool`:
```
HSD: {hsd_id} | Iteration: {N}
Component: {component} | Testcase type: {testcase_type}
Current top hypothesis: {top_hypothesis.statement} (confidence: {top_hypothesis.confidence})

Logs ALREADY COLLECTED (do NOT re-request):
{cumulative_collected_categories}

From the log taxonomy (pasted below), what specific logs should be collected
in this iteration to confirm or reject the top hypothesis?

Rules:
- Recommend ONLY logs NOT already collected (no duplicates)
- Start with the most targeted logs for the current hypothesis (Tier 1)
- Include the specific commands adapted for testcase type: {testcase_type}
  (use shell/custom-tool commands where PythonSV is not applicable)
- If a hypothesis was REJECTED by previous iteration's logs, focus on #2 hypothesis

Output as JSON:
{
  "rationale": "...",
  "logs_to_collect": [
    {"category": "...", "commands": ["..."], "reveals": "...", "hypothesis_target": "..."},
    ...
  ]
}

LOG TAXONOMY:
{log_taxonomy_content}
```

#### LD-4 Step 2: Execute log collection

Based on `execution_mode`:
- **manual**: Print all commands in a code block; ask user to paste output
- **local**: Run via `subprocess` through `live_debug_runner.LocalAdapter`
- **ssh**: Run via SSH through `live_debug_runner.SSHAdapter`
- **auto**: Try local first; fall back to manual

For each collected log, store via `live_debug_runner.ingest_log_output()`:
```python
log_record = ldr.ingest_log_output(raw_output, category, out_dir)
# → saves full content to file, returns {category, content_snippet, full_path}
```

#### LD-4 Step 3: Analyze new evidence

Call `mcp_intel_geni_pr_DebugAssistantAgentTool`:
```
HSD: {hsd_id} | Iteration: {N}
Component: {component}

New logs collected this iteration:
{for each new_log: category + content_snippet}

Previous hypotheses:
{ranked_hypotheses_list}

Analyze the new evidence:
1. What do the new logs reveal about the failure?
2. Which hypotheses does this evidence SUPPORT? (raise confidence)
3. Which hypotheses does this evidence REJECT? (lower confidence to < 0.1)
4. Update the hypothesis list with new confidence scores.
5. Is there a hypothesis with confidence >= 0.85? If so, is root cause confirmed?
6. What critical questions remain unanswered?

Important: if the same warning or log fragment is present in both the passing and failing scenarios, treat it as non-discriminating evidence and discard it as a root-cause candidate.

Output as JSON:
{
  "new_evidence_summary": "...",
  "updated_hypotheses": [
    {"statement": "...", "confidence": 0.N, "evidence": "..."},
    ...
  ],
  "root_cause_confirmed": false,
  "confirmed_root_cause": "",
  "unanswered_questions": ["..."]
}
```

If `mcp_co-design_codesign-ask-specs-and-wikis` is available, cross-check the top hypothesis:
```
Component: {component}
Top hypothesis: {top_hypothesis.statement}
Evidence: {new_evidence_summary}
Does this hypothesis align with the architectural spec for {component}?
Is there a known register or microarchitectural state that would definitively confirm this?
```

**Conditional A — RTL Scenario Deep-Dive** *(run at most once per session)*

Run if ALL of the following are true:
- Top hypothesis confidence >= 0.6
- Hypothesis names a specific RTL signal, register, or microarchitectural structure
- `session.rtl_scenario` is null (not yet produced in Phase LD-2c)
- `model_path` is available in the VSCode workspace

```
Invoke skill: codesign_validation-rtl-scenario-analysis
ip: {component}
model_path: {workspace_root}
Context: Iteration {N}. Top hypothesis is "{top_hypothesis.statement}" with {confidence*100:.0f}% confidence.
          Trace the RTL signal chain 3–5 levels deep to build the cycle-level scenario
          required for this failure to occur. Focus on signals mentioned in: {top_hypothesis.evidence}
```

Store result as `session.rtl_scenario`. Use it in subsequent LD-4 Step 1 GENI calls to
narrow log collection to the predicted signal chain.

**Conditional B — Constraint Scan** *(run when hypothesis language triggers it)*

Run if the top or second hypothesis statement contains any of these indicators:
> "chicken bit", "defeature", "config knob", "feature disabled", "feature gated",
> "not enabled", "hard constraint", "blocked by", "preload", "force override"

```
Invoke skill: codesign_validation-constraint-scan
ip: {component}
model_path: {workspace_root}
Coverage context: The failing scenario requires "{top_hypothesis.statement}".
                  Scan all 7 constraint mechanisms to determine if this path is
                  structurally blocked: hard constraints, custom macros, config knobs,
                  chicken bits/defeature registers, preloads, force/override directives,
                  disabled/excluded flows.
                  Deliver a CONSTRAINED / NOT CONSTRAINED verdict with file:line evidence.
```

If the verdict is **CONSTRAINED**: treat it as high-confidence root cause evidence.
Raise the matching hypothesis confidence to >= 0.85 and surface as confirmed root cause
in the next iteration's LD-4 Step 3 analysis. Skip the constraint scan in all subsequent
iterations for this session.

#### LD-4 Step 4: Persist iteration state

Call `live_debug_runner.write_iteration()` with:
```python
ldr.write_iteration(db_path, session_id, iteration_number, {
    "hypotheses": updated_hypotheses,
    "logs_requested": logs_to_collect,
    "logs_collected": [log_record, ...],
    "geni_analysis": new_evidence_summary,
    "next_steps": next_steps_list,   # from Step 5 below
    "user_input": "",                # filled after user confirms
})
```

#### LD-4 Step 5: ── PRESENT TO USER AND WAIT ──

**MANDATORY STOP.** Present the following summary and wait for user response:

```
══════════════════════════════════════════════════════════════
 ITERATION {N} FINDINGS  |  HSD {hsd_id}
══════════════════════════════════════════════════════════════

📋 LOGS COLLECTED THIS ITERATION:
{for each log: ✓ category — one-line description of what was found}

🔬 ANALYSIS:
{new_evidence_summary}

🎯 HYPOTHESIS RANKING (updated):
  1. [{confidence*100:.0f}%] {hypothesis_1.statement}
     Evidence: {hypothesis_1.evidence}
  2. [{confidence*100:.0f}%] {hypothesis_2.statement}
     Evidence: {hypothesis_2.evidence}
  ...

{if root_cause_confirmed}
✅ ROOT CAUSE CONFIRMED (confidence {top_confidence*100:.0f}%):
   {confirmed_root_cause}
{endif}

📌 RECOMMENDED NEXT STEPS:
  1. {next_step_1.step}
     Why: {next_step_1.rationale}
     Commands: {next_step_1.commands}
  2. {next_step_2.step}
     ...

❓ UNANSWERED QUESTIONS: {unanswered_questions}

──────────────────────────────────────────────────────────────
Reply with:
  • "go" or "confirmed" → proceed with recommended next steps
  • "stop" → end session and generate reports
  • Any additional context or corrections you want the agent to consider
══════════════════════════════════════════════════════════════
```

After user replies:
- Update `user_input` in the iteration DB record via `write_iteration()`
- If user says "stop" or root cause confirmed → go to Phase LD-5
- If user provides additional context → incorporate into next GENI call
- Otherwise → increment iteration counter and return to LD-4 Step 1

**If max_iterations reached**: Notify user, present best hypothesis, proceed to LD-5.

---

### Phase LD-5 — Final Root Cause Report

**MCP Tools**: `mcp_intel_geni_pr_DebugAssistantAgentTool` + `mcp_co-design_codesign-ask-specs-and-wikis`

**Step LD-5a** — GENI: synthesize all iterations into final diagnosis.

Call `mcp_intel_geni_pr_DebugAssistantAgentTool`:
```
HSD: {hsd_id} | Component: {component}
Debug session complete after {N} iterations.

Hypothesis history (all iterations):
{for each iteration: iteration_number, top_hypothesis, confidence, key_logs}

Confirmed root cause: {confirmed_root_cause or best_hypothesis}

1. Provide a definitive root cause statement (1–3 sentences, plain English).
2. Build an evidence chain: which specific log/register/output in which iteration
   confirmed the root cause. Format: [{iteration, log_category, finding}]
3. What is the recommended fix or workaround?
4. What should be added to log_taxonomy.md based on this debug session?
   (new categories, new interpretation patterns)

Output as JSON:
{
  "root_cause_statement": "...",
  "evidence_chain": [{"iteration": N, "log_category": "...", "finding": "..."}],
  "recommended_fix": "...",
  "taxonomy_additions": "..."
}
```

**Step LD-5b** — Co-Design Specs: validate fix against architectural spec.

Call `mcp_co-design_codesign-ask-specs-and-wikis`:
```
Component: {component}
Root cause: {root_cause_statement}
Proposed fix: {recommended_fix}

1. Is this fix consistent with the architectural specification?
2. Which spec section defines the expected behavior?
3. Are there side effects or spec-defined constraints for this fix?
```

**Step LD-5c** — Generate HTML report directly.

**The agent writes the HTML report itself** using the template structure in `templates/live_debug_report_template.html`.
Do NOT rely on an external Python runner. Follow these steps:

1. **Create the output directory** (PowerShell):
```powershell
New-Item -ItemType Directory -Path "src/output/live_debug_{session_id}" -Force
```

2. **Write `live_debug_report.html`** to `src/output/live_debug_{session_id}/live_debug_report.html`.

   The report **must** include the following sections in order, populated with all evidence from the session:
   - `<div class="banner">` — HSD title, platform, mode, confidence
   - `<div class="meta-row">` — HSD link, component badge, confidence, stepping, log count
   - Stats row (iterations, log sources, confidence, failure type, failing unit)
   - `<div class="rc-box">` — green root cause summary box with classification badge
   - **Phase card LD-0** — session parameters table
   - **Phase card LD-1** — symptom, reproduction steps, log file descriptions
   - **Phase card LD-2** — before/after comparison table + ranked hypotheses with `.conf-bar-wrap`
   - **Phase card LD-3** — log enablement plan table
   - **Phase card LD-4** (one `<div class="card">` per iteration) — dark `.log-box` excerpts,
     `.mca-table` for MCA decodes, `.finding-box` variants, hypothesis update table
   - **Phase card LD-5** — `.ev-chain`/`.ev-step` numbered evidence chain, `.finding-box` fix cards,
     session timeline, logs analyzed & gaps table
   - `<div class="corrections-card">` — Field Feedback & Triage Corrections
     (discarded indicators with `.discard-list`, confirmed indicators with `.unchanged-list`,
     recommended HSD field updates)
   - `<div class="rootcause-card active">` — structured root cause card with `.rootcause-grid`:
     left column = evidence chain (`.evidence-chain` list with `.ev-iter` labels),
     right column = recommended fix + spec reference
   - `<div class="related-card">` — Related Past HSDs table (`.related-table`) with HSD links,
     component, symptom, root cause, fix pattern; include HSD search suggestions if no exact related HSDs are known
   - `<footer>` — generated timestamp, session ID, template version, BugScout framework

   **CSS**: All required CSS classes are defined in `templates/live_debug_report_template.html`.
   Copy the full `<style>` block from that template into the generated report's `<head>`.
   Key classes for agent-generated content:
   - `.log-box` with `.err`/`.warn`/`.ok`/`.cmd`/`.info`/`.key` spans — dark terminal excerpts
   - `.finding-box.finding-confirmed/.finding-mechanism/.finding-topology/.finding-fix` — evidence boxes
   - `.mca-table` with `.field-set`/`.field-zero` — MCA register decode tables
   - `.ev-chain`/`.ev-step`/`.ev-num`/`.ev-body`/`.ev-arrow` — numbered evidence chain
   - `.discard-list`/`.unchanged-list` — corrections card lists
   - `.iter-label` — gradient sub-section header within phase cards
   - `.rootcause-card.active` + `.rootcause-grid`/`.rc-section` — final root cause
   - `.related-card`/`.related-table` — related HSDs
   - `.corrections-card` — field feedback

3. **Write `session_report.md`** to the same directory — a concise Markdown version of the root cause, evidence chain, and fix recommendation.

This generates these files in `src/output/live_debug_{session_id}/`:
- `live_debug_report.html` — full interactive HTML report (primary output)
- `session_report.md`      — Markdown debug trail (secondary output)

**Step LD-5d** — Update session status.

```python
ldr.update_session(db_path, session_id,
    status="root_cause_found",  # or "abandoned"
    title=session.hsd_context.title,
    component=session.hsd_context.component,
)
```

**Step LD-5e** — Report to user.

```
══════════════════════════════════════════════════════════════
 LIVE DEBUG SESSION COMPLETE  |  HSD {hsd_id}
══════════════════════════════════════════════════════════════

✅ ROOT CAUSE:
   {root_cause_statement}

🔧 RECOMMENDED FIX:
   {recommended_fix}

📐 SPEC REFERENCE:
   {spec_reference}

📊 SESSION SUMMARY:
   Iterations:      {N}
   Logs collected:  {total_log_sets}
   Session ID:      {session_id}

📁 REPORTS:
   HTML:     src/output/live_debug_{session_id}/live_debug_report.html
   Markdown: src/output/live_debug_{session_id}/session_report.md
══════════════════════════════════════════════════════════════
```

---

## MCP Tool Reference

| Phase | Tool | Purpose |
|-------|------|---------|
| LD-0 | `mcp_co-design_codesign-ask-hsd-agent` | Fetch HSD details + related past tickets |
| LD-1 | `mcp_intel_ngai_plan_and_execute` | Resolve NGA UUID → TestLine details |
| LD-2a | `mcp_intel_geni_pr_DebugAssistantAgentTool` | Initial hypothesis generation + log enablement plan |
| LD-2b | `mcp_co-design_codesign-ask-hsd-agent` | Find related past HSDs for seeding hypotheses |
| LD-4 step 1 | `mcp_intel_geni_pr_DebugAssistantAgentTool` | Next log recommendation (excludes already-collected) |
| LD-4 step 3 | `mcp_intel_geni_pr_DebugAssistantAgentTool` | Evidence analysis + hypothesis update |
| LD-4 step 3 | `mcp_co-design_codesign-ask-specs-and-wikis` | Cross-check top hypothesis vs spec |
| LD-5a | `mcp_intel_geni_pr_DebugAssistantAgentTool` | Final diagnosis synthesis |
| LD-5b | `mcp_co-design_codesign-ask-specs-and-wikis` | Fix validation against spec |

---

## Execution Mode Reference

| Mode | Behavior |
|------|----------|
| `manual` (default) | Agent prints commands; user runs them and pastes output back |
| `local` | Agent runs commands directly via `subprocess` on the local machine |
| `ssh` | Agent runs commands on `--server` via SSH subprocess |
| `auto` | Agent tries `local` first; falls back to `manual` if local fails |

---

## Key Rules

1. **Never re-request already-collected logs.** Track `cumulative_collected_categories` across all iterations.
2. **Always explain WHY.** Every next-step recommendation must include a `rationale` tying it to the current hypothesis.
3. **Never skip user confirmation.** After every iteration, STOP and wait for explicit user go-ahead.
4. **Testcase type determines enablement.** Never suggest PythonSV enablement for a `shell` or `python-script` testcase.
5. **Hypothesis confidence drives priority.** Always address the highest-confidence unfalsified hypothesis first.
6. **Session state is always persisted.** Every iteration must be written to the DB before presenting to user.
7. **Shared pass/fail warnings are non-causal.** If a warning also appears in the passing scenario, do not promote it as a root-cause indicator.

---

## Files Used by This Skill

| File | Purpose |
|------|---------|
| `live_debug_skill.md` | This file — execution instructions |
| `live_debug_runner.py` | Session state, execution adapters, report generation |
| `live_debug_report_template.html` | Jinja2 HTML report template (versioned in repo) |
| `live_debug_input.schema.json` | Schema for `--initial-logs` input file |
| `log_taxonomy.md` | Log categories + collection commands + interpretation guide |
| `parse_and_triage.py` | CLI entry: `--mode live-debug` dispatches to this skill |
| `output/live_debug_<id>_<ts>/` | Session output folder (DB, logs, reports) |
