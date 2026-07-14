---
name: hsd-triage
description: |
  HSD Triage & Log Recommendation Agent for DMR accelerator (and future domain) sightings.
  Analyzes initial HSD symptoms, retrieves testcase context via NGA MCP, verifies ground truth
  via GENI/Co-Design MCP, and recommends optimal first-pass debug logs.
  Use when asked to "triage HSD", "recommend debug logs", "analyze accelerator sighting",
  "what logs to collect for HSD", "first-pass triage", or "log recommendation for sighting".
---

> **Canonical copy.** This is the authoritative version of the hsd-triage skill.
> The copy at `project-c3/hsd-triage/skill.md` is a downstream mirror.

# HSD Triage & Log Recommendation Agent

## Trigger

Say any of: "run hsd-triage", "triage HSD", "recommend debug logs", "analyze accelerator sighting"

## What This Skill Does (Autonomous Execution)

When triggered, this skill **automatically** executes a complete 6-phase triage pipeline:
1. Parses the input HSD CSV to extract symptoms, NGA links, and test commands
2. Queries NGA MCP for test case details
3. Verifies ground truth via GENI + Co-Design MCP
4. Recommends optimal first-pass debug logs (using ONLY the symptom — no root cause)
5. Validates recommendations against known root cause
6. Generates comprehensive CSV + interactive HTML report

The repo now also contains a local crashdump route (`--mode crashdump`) plus handbook retrieval helpers (`crash-parser`, `handbook-rag`, `handbook-kb-builder`) for structured crash analysis when you need an offline first pass before MCP-backed validation.

**No manual prompts needed.** All MCP calls are made automatically.

---

## AUTONOMOUS EXECUTION INSTRUCTIONS

When this skill is triggered, execute ALL steps below **automatically, in order, without
stopping for user input**. The agent reads files, calls MCP tools, writes outputs, and
generates the final report — fully hands-off.

### Step 0.5: Auto-Fetch HSD Attachments (hsd-log-fetcher)

**Purpose**: Before parsing, auto-download any log files attached to HSD tickets so they
are available for analysis. Run this step for each HSD ID that does not already have files
in `HSD_Logs_Details/HSD_<id>/`.

```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python hsd_log_fetcher.py <hsd_id>
```

- Repeat for each HSD ID in the input CSV (extracted from the `id` column).
- If `HSD_Logs_Details/HSD_<id>/` already contains files, **skip that ticket** (files will not be re-downloaded).
- If no attachments exist on the ticket, continue — do not block the workflow.
- Collect any errors and surface them in the final report as "Logs not available via HSD API".

### Step 0.6: Auto-Parse StatusScope Reports (statusscope-parser)

**Purpose**: After attachments are fetched, check whether any StatusScope
`*-intel-svtools-report-v1.json` was downloaded and, if so, extract its high-value insights
to anchor the first-pass recommendation. Run for each HSD ID after Step 0.5.

```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python statusscope_ingest.py --dir "HSD_Logs_Details\HSD_<id>"
```

- The command auto-detects a `*-svtools-report*.json` in the fetched log directory. If none
  is present it prints "No StatusScope report found" and exits non-zero — **treat this as
  benign and continue** (StatusScope data is optional).
- If a report is found, feed its output into the triage context:
  - the **priority-sorted insights** (`HW.KNOWN_ISSUE` / `HW.CFG.ERR` first, then `SW.FW.ERR`),
  - the **HSD links** each insight references (candidates for correlation to the ticket),
  - any decoded **error / sideband / mca** and **known-sightings** tables.
- If the HSD has a linked Axon record and no local report, use
  `python statusscope_ingest.py --axon <record_id>` instead.
- Surface the extracted insights and HSD links in the final report before MCP validation.

### Step 1: Run Phase 1 (CSV Parsing)

Execute in terminal:
```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python parse_and_triage.py --input "c:\Users\smeenak1\OneDrive - Intel Corporation\Project Files\AI COE\pss-models\Accelerator HSDs\dmr_accelerator_full.csv" --mode prepare
```

If `output/` already contains a `run_*` folder with `triage_prompts.jsonl` inside, **skip this step**.
Otherwise the script creates `output/run_<YYYYMMDD_HHMMSS>/triage_prompts.jsonl`.
Note the run folder path printed — it is used in subsequent steps.

### Step 1.5: Phase 0 — HSD MCP Batch Enrichment (Co-Design HSD MCP)

**Purpose**: Clean up the three worst data-quality gaps in the CSV: blank `component` (~31%),
empty `actual_root_cause` (~78%), and empty `actual_logs_collected` (~49%) — all caused by
unreliable regex extraction from HTML-heavy HSD descriptions. Phase 0 calls the Co-Design HSD
MCP directly per ticket to get structured, clean data.

**MCP Tool**: `mcp_co-design_codesign-ask-hsd-agent`
**Tenant-subjects**: ALWAYS pass `["sighting_central.sighting", "server_platf.bug"]` — never empty.

**Execution workflow:**

1. Load `triage_prompts.jsonl` to get all HSD IDs (same as Step 2 below).

2. Create a SQL tracking table in the session DB:
   ```sql
   CREATE TABLE IF NOT EXISTS phase0_results (
       hsd_id TEXT PRIMARY KEY,
       hsd_component TEXT, hsd_root_cause TEXT, hsd_fix TEXT,
       hsd_actual_logs TEXT, hsd_conclusion TEXT,
       status TEXT DEFAULT 'pending'
   );
   -- Insert all HSD IDs as pending
   INSERT OR IGNORE INTO phase0_results (hsd_id) SELECT hsd_id FROM ...;
   ```

3. Query Co-Design HSD MCP in **batches of ~15 HSDs** per call. Prompt format:
   ```
   For each of the following HSD IDs, return a JSON array. Each element must have:
   hsd_id, hsd_component, hsd_root_cause (plain-English root cause - no HTML),
   hsd_fix (fix or workaround), hsd_actual_logs (what debug data was collected),
   hsd_conclusion.
   HSDs: <comma-separated IDs>
   ```

4. Save each batch result to SQL (`status='done'` or `status='no-data'` if all fields null).
   - no-data HSDs (inaccessible tenants, size limits): fall back to CSV values during finalize.

5. After all batches complete, run:
   ```bash
   python gen_phase0_dict.py
   ```
   This reads the SQL phase0_results table (all `status='done'` rows) and injects the
   `PHASE0_RESULTS` dict into `patch_fields.py`.

6. Apply the patch to `responses.jsonl`:
   ```bash
   python patch_fields.py --run-dir output/<RUN_DIR> --apply
   ```
   Then finalize and report:
   ```bash
   python patch_fields.py --run-dir output/<RUN_DIR> --finalize
   ```

**Expected fill rates after Phase 0:**
- `component`: ≥ 90%
- `actual_root_cause`: ≥ 85%
- `actual_logs_collected`: ≥ 90%

**Phase 3 prompt update**: Phase 3 now uses `hsd_root_cause` from Phase 0 (clean MCP data)
instead of `actual_root_cause` from regex extraction. This is handled automatically in
`parse_and_triage.py::build_phase3_prompt()` which uses `phase0_hsd.hsd_root_cause` if present.

**Error handling:**
- If a ticket belongs to an inaccessible tenant (e.g., `server__bugeco`): mark `no-data`
- If batch times out: retry the same batch
- If MCP is unavailable: skip Phase 0; CSV regex values will be used

---

### Step 2: Load prepared data (automated — use read_file tool)

Find the latest `output/run_*/triage_prompts.jsonl` from this folder. Parse each JSON line into memory.
Each record contains:
- `hsd_id`, `parsed.title`, `parsed.component`, `parsed.domain`
- `parsed.accelerator_type`, `parsed.failure_modes`, `parsed.initial_symptom`
- `parsed.nga_uuids`, `parsed.rocket_commands`, `parsed.logs_already_present`
- `parsed.actual_root_cause`

### Step 3: Load log taxonomy (automated — use read_file tool)

Read `log_taxonomy.md` from this folder. Store the full content as `{log_taxonomy_content}`
for use in Phase 4 prompts.

### Step 4: Process each HSD through Phases 2–5

For each record in the loaded data, execute these MCP tool calls sequentially.
**Do not ask for permission between records — process them all automatically.**

---

#### Phase 2 — Test Case Details (NGA MCP + Description Parsing)

**MCP Tool**: `mcp_intel_ngai_plan_and_execute` (NGA MCP)

**IF** the record has `nga_uuids` (non-empty list):

**Step 2a — Resolve UUID to TestLine via TestRunComposite:**

Call `mcp_intel_ngai_plan_and_execute` with:
```
Query TestRunComposite in dmr_fv where TestRunId eq {nga_uuid}.
Select: TestRunId, TestLineId, TestLineRevisionNumber, State, ResultCode,
        ResultDescription, TestStartDateTime, TestEndDateTime, SubmittedBy.
Expand: Failure($select=SightingId),
        TestLine($select=TestLineId,TestLineName,TestLineRevisionNumber,TestSuiteId,
                          TestGroupId,OperatingSystem,ConfigId,SoftwareConfig;
                 $expand=TestSuite($select=TestSuiteId,TestSuiteName),
                         TestGroup($select=TestGroupId,TestGroupName),
                         Config($select=ConfigId,ConfigName)).
```

This resolves the UUID to its TestLine identity and run metadata.

**Step 2b — Get step definitions via LatestTestLineTestStep:**

Using the `TestLineId` from step 2a, call `mcp_intel_ngai_plan_and_execute` with:
```
Query TestLine in dmr_fv where TestLineId eq {testline_id}.
Select: TestLineId, TestLineName, TestLineRevisionNumber, OperatingSystem.
Expand: LatestTestLineTestStep(
          $select=TestLineId,TestLineRevisionNumber,TestStepId,StepPosition;
          $expand=TestStep(
            $select=TestStepId,TestStepName,Command,Type,SystemRole,
                    TimeoutMinutes,CommandType,DefaultFlowFlag)).
```

From the returned `latestTestLineTestStep` array, sort by `StepPosition` and
classify each step by its `Type`:
- **PreTest** → header (setup before the test runs)
- **Test** → main test body
- **PostTest / Cleanup / PostFailure** → footer (teardown after pass or fail)

**Step 2c — Check DefaultFlow at suite/group/validation-group levels (if no steps found):**

If `LatestTestLineTestStep` returns zero steps, check DefaultFlow at each parent level
using `EntityId` in this order: TestSuiteId → TestGroupId → ValidationGroupId.
```
Query DefaultFlow in dmr_fv where EntityId eq {entity_id}.
Expand: LatestDefaultFlowTestStep(
          $expand=TestStep($select=TestStepName,Command,Type,SystemRole,TimeoutMinutes)).
```
Stop at the first level that returns results.

**IF** no NGA UUIDs but `rocket_commands` exist:

Parse the rocket command directly:
- Test name = target from `-v` flag (e.g., `dsa_focus_tests`, `cpm_variant_dmr`)
- Test domain = `--hw` flags (e.g., `dram,dsa` → DSA data streaming)
- Parameters = content inside `[]` brackets

**IF** neither is available:

Infer from title tags: `[QAT][SVOS]` → QAT silicon validation, SVOS framework.

Store results as:
- `testcase_name`
- `testcase_command`
- `testcase_parameters`
- `testcase_domain_focus`
- `nga_testline_id` — TestLineId UUID
- `nga_testline_name` — TestLineName (e.g., `dmr-ap_vv_a0_acc_fdu4a_0058`)
- `nga_testsuite_name` — TestSuiteName (e.g., `dmr-ap_vv_a0`)
- `nga_testgroup_name` — TestGroupName (e.g., `dmr-ap_vv_flow`)
- `nga_config` — Config name (e.g., `FDU4`)
- `nga_os` — OperatingSystem (e.g., `Svos`)
- `nga_run_result` — ResultCode from the run (e.g., `Failed`)
- `nga_run_submitted_by` — SubmittedBy (email of engineer who ran it)
- `nga_header_steps` — semicolon-separated "StepName (Type): Command" for PreTest steps
- `nga_test_steps` — semicolon-separated for Test-type steps
- `nga_footer_steps` — semicolon-separated for PostTest/Cleanup/PostFailure steps

**Note on DefaultFlow availability:**
For SVOS manual-execution tests the DefaultFlow is often empty — pre/post setup is
handled inside the `rocket` framework itself, not as separate NGA flow steps.
In this case record `nga_header_steps` and `nga_footer_steps` as empty and note
`"Manual Execution — no NGA flow steps defined"` in `testcase_parameters`.

**⚠️ NGA Session Limit — Batch Extraction for all HSDs:**
The NGA CosmosDB backend allows only ~2 plan/execute cycles per CLI session before hitting
`PreconditionFailed (412)`. For bulk extraction of NGA fields across all HSDs with UUIDs:

1. Process 1-2 batches of 10 UUIDs via `Intel-NGAi-plan_and_execute`
2. Save results to `output/<RUN_DIR>/nga_results.json` (keyed by UUID)
3. When 412 errors begin, run `python patch_nga_fields.py` to apply collected results
4. Start a **new CLI session** and continue from the next unprocessed UUID
5. Repeat until all UUIDs in `nga_uuid_map.json` are covered

`nga_results.json` accumulates results across sessions. `patch_nga_fields.py` is idempotent.

---

#### Phase 3 — Ground Truth Verification (GENI + Co-Design HSD + Co-Design Specs)

**MCP Tools**:
- `mcp_intel_geni_pr_DebugAssistantAgentTool` (GENI) — silicon failure mechanism + register analysis
- `mcp_co-design_codesign-ask-hsd-agent` (Co-Design HSD) — search related past HSDs for patterns
- `mcp_co-design_codesign-ask-specs-and-wikis` (Co-Design Specs) — architectural spec validation

**Step 3a** — Call `mcp_intel_geni_pr_DebugAssistantAgentTool` with:
```
HSD {hsd_id}, component: {component}, domain: {domain}.
Symptom: {initial_symptom}
Reported fix: {actual_root_cause}

1. What is the actual failure mechanism in silicon/firmware?
2. What register state or data path condition causes this?
3. Is the reported fix consistent with the failure mechanism?
4. What specific registers would show the failure state at time of failure?
```

**Step 3b** — Call `mcp_co-design_codesign-ask-hsd-agent` to find related past HSDs:
```
Find HSDs related to: {component} on DMR (Diamond Rapids).
Symptom: {initial_symptom}
Reported root cause: {actual_root_cause}

1. Are there prior HSDs with the same or similar root cause in this component?
2. Were there earlier debug trails that identified this class of bug?
3. What fix patterns were used for similar issues?
4. What adjacent subsystems have had related sightings?
```

**Step 3c** — Call `mcp_co-design_codesign-ask-specs-and-wikis` for architectural spec context:
```
Component: {component} on DMR (Diamond Rapids).
Operation: {testcase_domain_focus}
Reported root cause: {actual_root_cause}

1. What architectural element is involved and which spec defines expected behavior?
2. Is this behavior a known limitation or a bug against the spec?
3. What are the spec-defined constraints for this component/operation?
4. What adjacent subsystems interact with this path per the architecture spec?
```

Store results as:
- `verified_problem_statement`
- `verified_root_cause`
- `verified_fix`
- `related_hsds` (from Co-Design HSD agent — IDs of similar past tickets)
- `architectural_element` (from Co-Design Specs)

---

#### Phase 3.5 — ACD Handbook Verification (GENI + Co-Design Specs MCP)

**Purpose**: Validate the failure mechanism against known ACD-captured root causes
*before* recommending logs. Uses BugScout's bundled debug handbook
(`docs/handbooks/acd_debug_steps.md`) as grounding evidence for the MCP queries.

**MCP Tools**:
- `mcp_intel_geni_pr_DebugAssistantAgentTool` — match failure against known ACD patterns
- `mcp_co-design_codesign-ask-specs-and-wikis` — validate ACD collection coverage for the component

**Execution workflow**:

For each HSD, call GENI with the `phase_acd_verify` prompt (already generated by
`parse_and_triage.py --mode prepare`). The prompt includes handbook context for the
component + failure mode combination.

GENI is asked to:
1. Identify the MCA bank range that would capture the failure
2. Match the symptom against known ACD root-cause patterns from the handbook
   (DSA translation-queue deadlock, UBR VN0 credit loss, SFI poison passthrough,
   DSA gather-copy completion buffer exhaustion, etc.)
3. Confirm whether the failure is in a component covered by ACD collection
4. Identify any documented workaround if the pattern is recognized

Save the response as `phase_acd_verify` in the responses JSONL.
`mode_finalize` will merge `acd_verification_summary` into the `acd_verification` column.

**Expected JSON output keys**:
```json
{
  "acd_coverage": "covered|partial|not-covered",
  "acd_mca_bank_range": "10-13",
  "acd_subsystem": "IMC",
  "handbook_match": "exact|partial|none",
  "matched_pattern": "DSA Hang — Translation Queue Arbitration Deadlock",
  "handbook_confidence": 0.9,
  "acd_verification_summary": "...",
  "recommended_acd_registers": ["MCI_STATUS", "MCI_ADDR"],
  "known_workaround": "Limit Reduce/ReduceDC to ≤448KB"
}
```

**Error handling**: If GENI is unavailable or the handbook directory is missing, skip this
phase gracefully — `acd_verification` column will be empty in the output CSV.

---

#### Phase 4 — Log Recommendation (GENI MCP)

**MCP Tool**: `mcp_intel_geni_pr_DebugAssistantAgentTool` (GENI Debug Assistant)

**CRITICAL RULE: Use ONLY {initial_symptom} and {testcase_name}. Do NOT pass the root cause
or Phase 3 results. This simulates triaging a NEWLY OPENED HSD.**

Call `mcp_intel_geni_pr_DebugAssistantAgentTool` with:
```
You are triaging a NEW accelerator sighting. No root cause is known yet.

Component: {component}
Accelerator: {accelerator_type}
Initial symptom: {initial_symptom}
Test running: {testcase_name} ({testcase_command})
Failure mode: {failure_modes}

From the following log taxonomy, recommend debug data to collect:
{log_taxonomy_content}

Organize into:
- Tier 1 (CRITICAL): Logs that directly expose the most likely failure mechanisms
- Tier 2 (LIKELY NEEDED): Broader context if Tier 1 inconclusive
- Tier 3 (EXTENDED): Cross-domain, edge cases

For each: category name, specific commands, what it reveals, why relevant.
Also suggest any logs NOT in taxonomy (internal silicon state a field engineer
wouldn't typically collect but would accelerate root cause).
```

Store results as:
- `recommended_log_categories` (comma-separated)
- `recommended_commands` (semicolon-separated)
- `beyond_sme_recommendations`

---

#### Phase 5 — Cross-Domain Validation (Co-Design Specs + Co-Design HSD)

**MCP Tools**:
- `mcp_co-design_codesign-ask-specs-and-wikis` (Co-Design Specs) — architectural spec-based validation
- `mcp_co-design_codesign-ask-hsd-agent` (Co-Design HSD) — cross-reference debug patterns from similar past HSDs

**Step 5a** — Call `mcp_co-design_codesign-ask-specs-and-wikis` with:
```
HSD {hsd_id}: {title}
Component: {component}
Test domain: {testcase_domain_focus}
Verified root cause (Phase 3): {verified_root_cause}
Recommended logs (Phase 4): {recommended_log_categories}

1. Does testcase domain match root cause domain? (same-domain / adjacent / cross-domain)
2. How does the test encounter this defect? (direct / side-effect / stress)
3. Would Phase 4 recommended logs surface the root cause per the spec? Explain diagnostic path.
4. Are there spec-defined diagnostic registers or sequences not in the log taxonomy?
```

**Step 5b** — Call `mcp_co-design_codesign-ask-hsd-agent` to cross-reference debug patterns:
```
For HSD {hsd_id} (component: {component}, root cause: {verified_root_cause}):
Related past HSDs from Phase 3: {related_hsds}
Recommended logs (Phase 4): {recommended_log_categories}

1. In the related past HSDs, what logs were most effective at surfacing the root cause?
2. Were the Phase 4 recommended logs sufficient or were additional logs needed?
3. What iteration savings were seen in comparable past debug trails?
4. Estimated iteration savings for this HSD if Phase 4 logs were collected first-pass?
```

Store results as:
- `how_testcase_encounters_defect`
- `root_cause_domain`
- `domain_relationship` (same-domain | adjacent | cross-domain)
- `recommendation_accuracy` (high | medium | low)
- `recommendation_rationale` (synthesized from both Specs + HSD agent)
- `iteration_savings` (integer, cross-validated against historical HSD debug trails)

---

### Step 5: Write responses using write_batch_responses.py

Responses are written using the **reusable helper script** `write_batch_responses.py`.
Do NOT generate ad-hoc `python -c` commands for this — use the script.

**Workflow:**
1. After collecting Phase 2–5 results for a batch of HSDs, populate the `BATCH` dict in
   `write_batch_responses.py` with the new responses.
2. Set `RUN_DIR` at the top of the script to the current run folder (auto-detect the latest
   `output/run_*/` if not already set).
3. Run:
   ```bash
   cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
   python write_batch_responses.py
   ```
4. The script skips already-written HSD IDs (idempotent — safe to re-run).

**Adding new batch responses:**
Open `write_batch_responses.py` and append new entries to the `BATCH` dict:
```python
BATCH["<hsd_id>"] = {
    "phase2_nga": { "testcase_name": "...", "testcase_command": "...",
                    "testcase_parameters": "...", "testcase_domain_focus": "..." },
    "phase3_verify": { "verified_problem_statement": "...", "verified_root_cause": "...",
                       "verified_fix": "...", "architectural_element": "...",
                       "failure_registers": [...], "adjacent_subsystems": [...],
                       "related_hsds": [...],          # from Co-Design HSD agent (Phase 3b)
                       "spec_reference": "..." },      # from Co-Design Specs agent (Phase 3c)
    "phase4_recommend": { "tier1": [...], "tier2": [...], "tier3": [...], "beyond_sme": [...] },
    "phase5_validate": { "how_testcase_encounters_defect": "...", "root_cause_domain": "...",
                         "domain_relationship": "...", "recommendation_accuracy": "...",
                         "recommendation_rationale": "...", "iteration_savings": "N" }
}
```
Then run the script. It appends only new entries and reports a summary.

### Step 6: Generate Final Outputs (automated — run in terminal)

Execute in terminal (replace `<RUN_DIR>` with the actual run folder path):
```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python parse_and_triage.py --mode finalize --responses <RUN_DIR>/responses.jsonl --output-dir <RUN_DIR>
```

---

### Step 6.5: ⚠️ MANDATORY Quality Gate — CSV Self-Check (DO NOT SKIP)

**This step is required before generating the report. Never skip it.**

Run the following audit script to detect gaps between `responses.jsonl` and `triage_results.csv`:

```bash
cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python -c "
import csv, json, sys
from pathlib import Path

run_dir = sorted(Path('output').glob('run_*'), key=lambda d: d.name, reverse=True)[0]
csv_path = run_dir / 'triage_results.csv'
jsonl_path = run_dir / 'responses.jsonl'
prompts_path = run_dir / 'triage_prompts.jsonl'

# Critical fields that must be populated
REQUIRED = ['testcase_name', 'verified_root_cause', 'recommended_log_categories',
            'recommendation_accuracy', 'iteration_savings']

# Load source data
source = {}
with open(jsonl_path, encoding='utf-8', errors='replace') as f:
    for line in f:
        r = json.loads(line)
        hid = r.get('hsd_id')
        resp = r.get('responses') or r
        has_phase = any(k in resp for k in ('phase2_nga','phase3_verify','phase4_recommend','phase5_validate'))
        source[hid] = has_phase

# Load CSV and audit
total = 0; gap_ids = []; field_counts = {k: 0 for k in REQUIRED}
with open(csv_path, newline='', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        total += 1
        hid = row['hsd_id']
        missing = [k for k in REQUIRED if not row.get(k,'').strip()]
        for k in REQUIRED:
            if row.get(k,'').strip(): field_counts[k] += 1
        if missing and source.get(hid):
            gap_ids.append((hid, missing))

print(f'Total rows: {total}')
print('Fill rates:')
for k in REQUIRED:
    pct = field_counts[k]*100//total
    flag = '' if pct >= 95 else '  ← BELOW 95% THRESHOLD'
    print(f'  {k}: {field_counts[k]}/{total} ({pct}%){flag}')

if gap_ids:
    print(f'\n❌ GAPS DETECTED: {len(gap_ids)} HSDs have source data in responses.jsonl but empty CSV fields')
    for hid, missing in gap_ids[:20]:
        print(f'  {hid}: missing {missing}')
    if len(gap_ids) > 20:
        print(f'  ... and {len(gap_ids)-20} more')
    print('\nAction required: investigate format mismatch in responses.jsonl for these HSDs')
    print('Then re-run: python parse_and_triage.py --mode finalize ...')
    sys.exit(1)
else:
    print('\n✅ Quality gate passed — no gaps between source data and CSV output')
"
```

**Interpret results:**
- **`sys.exit(1)` / ❌ GAPS DETECTED** → Do NOT generate the report yet. Investigate the listed HSDs:
  1. Open `responses.jsonl` and inspect the raw record for each gap HSD
  2. Check if format differs (nested `"responses"` key? Different field names?)
  3. Fix `parse_and_triage.py` finalize logic to handle the variant, or re-write the response entry
  4. Re-run finalize, then re-run this quality gate until it passes
- **Fill rate below 95%** → Check if the low-fill HSDs genuinely had no MCP data written (not a code bug)
- **✅ Quality gate passed** → Proceed to Step 7

**Quality thresholds (must all pass):**
| Field | Minimum fill rate |
|-------|------------------|
| `testcase_name` | ≥ 95% |
| `verified_root_cause` | ≥ 95% |
| `recommended_log_categories` | ≥ 90% |
| `recommendation_accuracy` | ≥ 95% |
| `iteration_savings` | ≥ 95% |

---

### Step 7: Generate Per-HSD RCA Reports (MANDATORY — one per HSD)

**This step is required for every HSD processed.** For each HSD in the batch, generate an
individual RCA HTML report using `rca_report_template.html`. These are the primary deliverable
for reviewing engineers — they capture the full analysis lifecycle in a single self-contained file.

Execute in terminal:
```bash
python parse_and_triage.py --mode rca-reports --input <RUN_DIR>/triage_results.csv --output-dir <RUN_DIR>
```

This generates one file per HSD: `output/<RUN_DIR>/HSD_<id>_rca_report.html`

**Template**: `rca_report_template.html` — all variables below MUST be populated.
Unpopulated / null variables must render as empty string (`""`) — never `None` or `null`.

#### Template Variable Reference

| Variable | Source | Required |
|---|---|---|
| `hsd_id` | CSV / Phase 0 | ✅ |
| `hsd_title` | CSV / Phase 0 | ✅ |
| `component` | Phase 0 / CSV | ✅ |
| `priority` | CSV | ✅ |
| `priority_num` | Extracted from priority ("2-high" → `2`) | ✅ |
| `status` | CSV / Phase 0 | ✅ |
| `release` | Phase 0 | ✅ |
| `owner` | Phase 0 | ✅ |
| `submitted_date` | Phase 0 | ✅ |
| `related_bug_ids` | Phase 0 — comma-separated clone/bug IDs | optional |
| `nga_tr_url` | CSV nga_uuids resolved to full NGA URL | optional |
| `analysis_date` | Generated at runtime (YYYY-MM-DD) | ✅ |
| `run_id` | Current run folder name | ✅ |
| `key_takeaways` | **list** — 3–5 bullet strings (synthesized from Phase 3+5) | ✅ |
| `initial_symptom` | Phase 1 parsed symptom | ✅ |
| `error_output` | Phase 0 / CSV — verbatim error log excerpt | optional |
| `failing_commands` | Phase 0 / Phase 2 — failing rocket/test commands | optional |
| `testcase_name` | Phase 2 | ✅ |
| `testcase_domain_focus` | Phase 2 | ✅ |
| `testcase_command` | Phase 2 | ✅ |
| `testcase_parameters` | Phase 2 | optional |
| `nga_testline_id` | Phase 2 | optional |
| `nga_testline_name` | Phase 2 | optional |
| `nga_testsuite_name` | Phase 2 | optional |
| `nga_testgroup_name` | Phase 2 | optional |
| `nga_config` | Phase 2 | optional |
| `nga_os` | Phase 2 | optional |
| `nga_run_result` | Phase 2 | optional |
| `nga_run_submitted_by` | Phase 2 | optional |
| `nga_header_steps` | Phase 2 — **list** of step strings | optional |
| `nga_test_steps` | Phase 2 — **list** of step strings | ✅ if available |
| `nga_footer_steps` | Phase 2 — **list** of step strings | optional |
| `how_testcase_encounters_defect` | Phase 5 | ✅ |
| `verified_problem_statement` | Phase 3 | ✅ |
| `verified_root_cause` | Phase 3 | ✅ |
| `key_evidence` | Phase 3 — key register/log evidence string | ✅ |
| `verified_fix` | Phase 3 | ✅ |
| `architectural_element` | Phase 3 | ✅ |
| `spec_reference` | Phase 3c | optional |
| `failure_registers` | Phase 3 — **list** of register name strings | optional |
| `adjacent_subsystems` | Phase 3 — **list** | optional |
| `related_hsds` | Phase 3b — **list** of HSD ID strings | optional |
| `tier1_logs` | Phase 4 — **list** of `{category, commands[], reveals, relevance}` | ✅ |
| `tier2_logs` | Phase 4 — **list** of `{category, commands[], reveals, relevance}` | ✅ |
| `tier3_logs` | Phase 4 — **list** of `{category, commands[], reveals, relevance}` | optional |
| `beyond_sme_logs` | Phase 4 — **list** of `{description, commands[], why}` | optional |
| `actual_logs_collected` | Phase 0 / CSV | ✅ |
| `domain_analysis` | Phase 5 | ✅ |
| `recommendation_rationale` | Phase 5 | ✅ |
| `root_cause_domain` | Phase 5 | ✅ |
| `domain_relationship` | Phase 5 (same-domain / adjacent / cross-domain) | ✅ |
| `recommendation_accuracy` | Phase 5 (high / medium / low) | ✅ |
| `iteration_savings` | Phase 5 | ✅ |
| `prior_run_id` | Latest previous `run_*/` folder that has this HSD's report; `"N/A"` if none | ✅ |
| `prior_root_cause` | Loaded from prior run's `triage_results.csv` row; `""` if no prior run | optional |
| `agree_disagree` | `"AGREE"` / `"DISAGREE"` / `"N/A"` — compare prior vs current root cause | ✅ |
| `agree_class` | `"agree"` / `"disagree"` / `"na"` (lowercase, for CSS class) | ✅ |
| `delta_analysis` | 1–2 sentence summary of what changed between runs | optional |
| `key_registers_evidence` | Phase 3 — verbatim register dump / code evidence block | ✅ |
| `register_table` | Optional **list** of `{register, field, value, meaning}` dicts | optional |
| `references` | **list** of `{label, url}` — HAS, spec pages, related HSDs, Axon links | ✅ |

#### Prior-Run Comparison Logic

When generating per-HSD RCA reports, check for a prior run that analyzed the same HSD:
```python
# Pseudo-code — implement in parse_and_triage.py
prior_runs = sorted(output_dir.glob("run_*/triage_results.csv"), reverse=True)
prior_root_cause = ""
prior_run_id = "N/A"
for prior_csv in prior_runs:
    if prior_csv.parent.name == current_run_id:
        continue   # skip self
    rows = load_csv(prior_csv)
    match = next((r for r in rows if r["hsd_id"] == hsd_id), None)
    if match and match.get("verified_root_cause", "").strip():
        prior_root_cause = match["verified_root_cause"]
        prior_run_id = prior_csv.parent.name
        break

# Determine AGREE/DISAGREE by semantic similarity
if not prior_root_cause:
    agree_disagree, agree_class = "N/A", "na"
else:
    # Use simple keyword overlap or cosine sim; AGREE if >70% overlap
    agree_disagree = "AGREE" if root_causes_agree(prior_root_cause, current_root_cause) else "DISAGREE"
    agree_class = agree_disagree.lower()
```

#### Key Takeaways Generation

Synthesize 3–5 concise bullets from Phase 3 and Phase 5 data:
- Bullet 1: Core failure mechanism (1 sentence, specific — component + what failed)
- Bullet 2: Silicon/firmware root cause classification (erratum / SW bug / config issue / etc.)
- Bullet 3: Fix or workaround (what must be done)
- Bullet 4: Test case relationship (how the test exposed the defect)
- Bullet 5 (optional): Cross-domain or adjacent subsystem note if relevant

---

### Step 7.5: Generate HTML Summary Report (only after quality gate passes)

Execute in terminal:
```bash
python parse_and_triage.py --mode report --input <RUN_DIR>/triage_results.csv --output-dir <RUN_DIR>
```

### Step 8: Report Completion

Tell the user:
- Total HSDs processed
- Quality gate result (fill rates per field, any gaps found and resolved)
- Accuracy summary (% where Tier 1 logs would find root cause)
- Path to HTML report
- Open the HTML report in browser

---

## Batch Size Control

- **Default**: Process ALL records in `triage_prompts.jsonl`
- If user says "pilot" or "test batch": Process only the first 5 records
- If user specifies an HSD ID: Process only that single record
- If user says "continue": Resume from last record in latest `output/run_*/responses.jsonl`

---

## Live Mode (Single Open HSD — Triage Only)

If the user says "triage HSD <id>" or provides a single HSD ID **without** live server access:

1. Fetch the HSD via `hsd-live-fetcher` (if not in CSV):
   ```bash
   cd "c:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\project-c3\hsd-live-fetcher"
   python fetch_hsds.py --eql "select id,title,status,owner,priority,component,description where sighting_central.sighting.id = '<hsd_id>'"
   ```
2. Parse the fetched record (same extraction as Phase 1)
3. Skip Phase 3 (no ground truth for open HSDs)
4. Execute Phase 2 (NGA via `mcp_intel_ngai_plan_and_execute`) and Phase 4 (GENI via `mcp_intel_geni_pr_DebugAssistantAgentTool`)
5. Output: recommended logs in tiered format directly to the user

---

## Live Debug Mode (Interactive — with Live Server Access)

If the user wants to iteratively collect logs and converge on root cause with live server access,
route to one of two sibling skills based on the trigger phrase:

| Trigger | Skill | When to use |
|---------|-------|-------------|
| `live-debug HSD <id>` | `live-debug` | First time debugging this failure; need full human control after every iteration; non-PythonSV testcases |
| `loop-debug HSD <id>` | `loop-debug` | Have an initial hypothesis already; want agent autonomy with contract + adversarial evaluator; overnight autonomous runs |

**`live-debug`** — human-pause-per-iteration, no pre-committed contract:
```
Trigger: "live-debug HSD <id>"
Skill:   live-debug
CLI:     python parse_and_triage.py --mode live-debug --hsd-id <id> [options]
```

**`loop-debug`** — Planner/Generator/Evaluator with configurable autonomy and on-disk state:
```
Trigger: "loop-debug HSD <id>"
Skill:   loop-debug
Module:  src/loop_debug/ (loop_orchestrator, loop_planner, loop_generator, loop_evaluator)
```

All session parameters can be passed inline in the NLP prompt — no CLI step required:
```
live-debug HSD 14027419708 using SSH on server mylab.intel.com as user smeenak1 max 5 iterations
debug HSD 14027419708 run commands locally
live-debug HSD 14027419708 manual mode, initial logs in C:\debug\logs.json, symptom is: hang during DMA
```

Key differences from triage-only mode:
- Runs an **iterative debug loop** (not a one-shot recommendation)
- Agent **enables logs, runs tests, collects output** on a live server
- Pauses after every iteration for user confirmation and additional inputs
- Handles non-PythonSV testcases (custom tools, Python scripts, shell commands)
- Outputs: JSON session file + Markdown debug trail + HTML interactive report

---

## Error Handling

- If NGA MCP (`mcp_intel_ngai_plan_and_execute`) is unavailable: Skip Phase 2, use title/description parsing for test context
- **NGA CosmosDB 412 / session limit**: The NGA backend persists session state in CosmosDB (ETag-based). Only **~2 successful plan/execute cycles** are possible per CLI session before the session document enters a conflicted state (`PreconditionFailed 412`). After that, the tool returns "Not connected".
  - **Workaround**: After hitting the 412 limit, run `patch_nga_fields.py` with what was collected, then start a **fresh CLI session** and continue from the next unprocessed UUID in `nga_uuid_map.json`.
  - `nga_results.json` (in the run folder) accumulates results across sessions — re-running `patch_nga_fields.py` is idempotent and will merge new results with existing ones.
- If GENI MCP (`mcp_intel_geni_pr_DebugAssistantAgentTool`) is unavailable: Report error, cannot proceed (GENI is required for log recommendations)
- If Co-Design MCP is unavailable:
  - If `mcp_co-design_codesign-ask-hsd-agent` is unavailable: Skip Phase 3b and Phase 5b; note missing related HSD cross-reference in output
  - If `mcp_co-design_codesign-ask-specs-and-wikis` is unavailable: Skip Phase 3c and Phase 5a; note missing spec validation in output
  - If both Co-Design tools are unavailable: Skip full Phase 3 Co-Design steps and Phase 5; proceed with GENI-only results
- If a single HSD fails: Log the error, continue to next HSD (do not abort batch)

---

## MCP Tool Reference

| Phase | Tool Name | Purpose |
|-------|-----------|---------|
| 0 | `mcp_co-design_codesign-ask-hsd-agent` | Batch enrich component/root-cause/logs fields directly from HSD tickets |
| 2 | `mcp_intel_ngai_plan_and_execute` | Query NGA for test case details |
| 3a | `mcp_intel_geni_pr_DebugAssistantAgentTool` | Verify silicon failure mechanism + registers |
| 3b | `mcp_co-design_codesign-ask-hsd-agent` | Search related past HSDs for bug patterns |
| 3c | `mcp_co-design_codesign-ask-specs-and-wikis` | Validate against architectural specs + wikis |
| 4 | `mcp_intel_geni_pr_DebugAssistantAgentTool` | Recommend debug logs (symptom-only) |
| 4 | `mcp_intel_geni_pr_CodeWithRegistersTool` | Get specific register details if needed |
| 5a | `mcp_co-design_codesign-ask-specs-and-wikis` | Spec-based cross-domain validation |
| 5b | `mcp_co-design_codesign-ask-hsd-agent` | Cross-reference debug patterns from past HSDs |

---

## Files in This Folder

| File | Purpose |
|------|---------|
| `skill.md` | This file — autonomous execution instructions |
| `log_taxonomy.md` | Debug log categories with commands (input to Phase 4) |
| `rca_report_template.html` | **Per-HSD RCA report template** (Step 7) — mandatory one-per-HSD output; Jinja2 variables cover all 6 phases: metadata, symptom, NGA test case, ground truth verification, log recommendations, cross-domain validation, prior-run comparison, register evidence, references |
| `report_template.html` | Aggregate HTML summary report template (Step 7.5) — all-HSDs table view with filters/sort |
| `parse_and_triage.py` | CSV parser, prompt builder, report generator |
| `patch_fields.py` | **Phase 0 patcher** — injects HSD MCP enrichment into `responses.jsonl`; contains `PHASE0_RESULTS` dict populated by agent |
| `gen_phase0_dict.py` | **Phase 0 helper** — reads SQL session DB `phase0_results` table and injects into `patch_fields.py` |
| `write_batch_responses.py` | **Reusable helper** — appends Phase 2–5 responses to `responses.jsonl`; idempotent |
| `Readme.md` | Usage documentation |
| `output/` | All generated outputs (each run in a `run_<timestamp>/` subfolder) |

---

## Helper Scripts

These scripts live permanently in the hsd-triage folder and are reused across runs.
Do **not** regenerate them — edit and extend them in place.

### `write_batch_responses.py`

**Purpose**: Write MCP-derived Phase 2–5 responses into `responses.jsonl` for a batch of HSDs.

**How it works**:
- Reads `triage_prompts.jsonl` to get all parsed records
- Reads existing `responses.jsonl` to find already-written HSD IDs (idempotent)
- Writes only new entries from the `BATCH` dict to `responses.jsonl`
- Prints a count of newly written vs already-done records

**To use for a new batch run**:
1. Update `RUN_DIR` at the top to the current run folder path
2. Populate the `BATCH` dict with new HSD responses
3. Run: `python write_batch_responses.py`
4. All previously written HSDs are automatically skipped

**To extend for a new run folder** (when starting a fresh session):
```python
# Change just this line at the top of write_batch_responses.py:
RUN_DIR = Path(__file__).parent / "output" / "run_YYYYMMDD_HHMMSS"
```
The rest of the script works unchanged.

**Record format** (each `BATCH` entry):
- `phase2_nga`: testcase_name, testcase_command, testcase_parameters, testcase_domain_focus,
  nga_testline_id, nga_testline_name, nga_testsuite_name, nga_testgroup_name,
  nga_config, nga_os, nga_run_result, nga_run_submitted_by,
  nga_header_steps, nga_test_steps, nga_footer_steps
- `phase3_verify`: verified_problem_statement, verified_root_cause, verified_fix,
  architectural_element, failure_registers (list), adjacent_subsystems (list),
  related_hsds (list — from Co-Design HSD agent, Phase 3b),
  spec_reference (string — from Co-Design Specs agent, Phase 3c)
- `phase4_recommend`: tier1 (list), tier2 (list), tier3 (list), beyond_sme (list)
  — each tier item: {category, commands (list), reveals, relevance}
  — each beyond_sme item: {description, commands (list), why}
- `phase5_validate`: how_testcase_encounters_defect, root_cause_domain, domain_relationship,
  recommendation_accuracy, recommendation_rationale (synthesized from Specs + HSD agent),
  iteration_savings (string integer, cross-validated against historical debug trails)

## Domain Extensibility

This skill targets accelerator (DSA/IAA/QAT) as the first domain. To extend:
1. Add a new domain section to `log_taxonomy.md`
2. No other changes needed — the prompts adapt via `{component}` and `{domain}` parameters

Future domains: memory, I/O, compute, power, interconnect, CXL, PCIe.
