---
name: hsd-triage
description: |
  HSD-ES triage AND debug for Intel GNR / SRF / CWF across ALL domains (core, CHA/uncore,
  IMC/memory, mesh/fabric, UPI/KTI, IIO/PCIe/CXL, power/PM, accelerators, security, RDT,
  boot/RAS). Fetches a target HSD, classifies the failure, recalls a self-learning KB,
  finds similar past HSDs, ranks root causes, and produces a next-step debug plan with the
  EXACT commands to collect the required data. Emits an A–H markdown report and an HTML report.
  Use when asked to "triage HSD", "debug HSD", "analyze HSD", "run hsd-triage", or via /auto-hsd-analyser.
tools:
  - HSDTool
  - HSDIndexTool
  - codesign-ask-hsd-agent-mcp
  - codesign-debug-search-in-memories
  - codesign-debug-get-memory
  - codesign-debug-store-memory
  - read_file
  - create_file
---

# HSD Triage &amp; Debug — GNR / SRF / CWF (all domains)

## Trigger
"triage HSD <id>", "analyze HSD <id>", "run hsd-triage", or the `/auto-hsd-analyser` prompt.

## Inputs
- `HSD_ID` (required) — target HSD-ES ticket.
- `SYMPTOMS` (optional) — key terms: unit, bucket, MCE bank, RIP, signal, error string, stepping.

## TOOL POLICY (environment-verified)
- **Primary HSD access:** `HSDTool` (SQL/keyword) and `HSDIndexTool` (semantic, needs an
  IBI token via the `acquire-tokens` skill). These are confirmed working.
- **Fallback only:** `codesign-ask-hsd-agent-mcp` — in some environments this tool
  cancels immediately; do NOT rely on it. If it returns "cancelled", switch to `HSDTool`.
- **KB tools** (`codesign-debug-*`) REQUIRE non-empty `cluster_stepping` and `bucket`.
  Derive them from the target HSD before calling (see Phase 1). Never pass empty strings.
- **Never call MCP tools in a parallel batch.** One failing call aborts its siblings
  (they show as "cancelled"). Call one at a time and wait for each result.

## PIPELINE (run all phases in order, autonomously)

### Phase 1 — Fetch & normalize the target HSD  (HSDTool)
Call `HSDTool`: "Retrieve HSD <id> and return title, component, release/stepping, status,
owner, priority, and description/failure signature."
Derive and store:
- `cluster` from component/unit → one of `core`, `cha`, `imc`, `mesh`, `upi`, `iio`, `pcie`,
  `cxl`, `power`, `dsa`, `iaa`, `qat`, `dlb`, `security`, `rdt`, `bios`, `system`.
- `stepping` from release/SoC (e.g. `gnr-b0`, `srf-a0`, `cwf-a0`); if absent, ask the user.
- `cluster_stepping = {cluster}_{stepping}` (e.g. `upi_gnr-ap`, `imc_srf-a0`).
- `bucket` = HSD failure bucket, or a normalized `<CLASS>::<unit>::<signature>` when none
  exists. Never blank.
- `failure_class` ∈ {hang, mce/mca, crc/link, data-corruption, init-failure, perf,
  thermal/power, other}.

### Phase 2 — KB recall  (codesign-debug-search-in-memories)
Call with the derived `cluster_stepping` + `bucket` and a query built from `SYMPTOMS`.
Report confidence: **High / Medium / Low / None**.
- High → answer primarily from KB; spot-check against HSDES.
- Medium/Low/None → run Phase 3 (full HSDES), then Phase 6 write-back.
Use `codesign-debug-get-memory` to pull full details of any strong match.

### Phase 3 — Similar-HSD search  (HSDTool, optionally HSDIndexTool)
Ask `HSDTool` for up to 8 sightings/bugs matching the symptom keywords for the same
family (Granite Rapids / Sierra Forest / Clearwater Forest). Return ID, title, status,
component, root cause / fix if present. For semantic matches use `HSDIndexTool`
(acquire an IBI token first). Rank the top 3–5.

### Phase 3.5 — Handbook + command grounding  (handbook-rag skill)
For the matched `cluster` and `failure_class`, retrieve the top handbook sections (see
`handbook-rag`) AND the corresponding command set from `docs/command_library.md` (§ by
domain + failure class). This grounds hypotheses in known patterns and provides the exact
commands used in Phase 5.

### Phase 4 — Rank root-cause hypotheses
Produce 2–4 ranked hypotheses, each tagged **confirmed** (from data) or **hypothesis**,
tied to supporting evidence (which similar HSD / handbook section / register).

### Phase 5 — Debug plan WITH commands
Numbered, specific next steps. For EACH step give:
- what to check and which hypothesis it proves/disproves;
- the **exact command(s)** to run — pulled from `docs/command_library.md` for the domain
  (PythonSV/cscripts `sv.socket0.<domain>.<reg>.show()`, MCA/MCE decode, OS
  `dmesg`/`rdmsr`/`mcelog`/`lspci`, BMC `ipmitool`/POST capture);
- a decision branch ("if X → conclusion, else → next step").
Mark each command **confirmed** or **needs path confirmation** (give the discovery command,
e.g. `sv.socket0.uncore.<block>.show()` / `dir(...)`, to confirm it). Only give commands
plausible for the named domain — never invent register paths.

### Phase 5b — Consolidated collection block
Emit one copy-pasteable command block (grouped by domain) the engineer can run immediately,
plus the metadata to capture: stepping, ucode/IFWI/BIOS rev, socket/cluster, bucket, POST
code, and RPT fields.

### Phase 6 — KB write-back  (codesign-debug-store-memory)
Store/update a KB entry: normalized symptom signature, similar HSD IDs + why they matched,
confirmed/likely root cause, useful debug steps + PythonSV commands, final resolution +
source HSD, provenance + timestamp + confidence tag (**confirmed** vs **hypothesis**).
If a matching entry exists, UPDATE it (reinforce / correct) rather than duplicating.
On any conflict, **HSDES is the source of truth**.

### Phase 7 — Emit reports
1. **Markdown** — the A–H report (see OUTPUT below).
2. **HTML** — fill `templates/auto-hsd-report-template.html`, replacing every
   `{{PLACEHOLDER}}` (see the quick-reference block at the top of that file). Write to
   `output/hsd_<id>_<YYYYMMDD_HHMMSS>/session_report.html` via `create_file`.

## OUTPUT (markdown, exact sections)
- **A. Target HSD summary**
- **B. KB recall result** (confidence + matched learned cases)
- **C. Similar HSDs table** (ID | Source: KB/HSDES | Similarity | Root cause | Status)
- **D. Ranked root-cause hypotheses** (each with supporting evidence, confirmed vs hypothesis)
- **E. Detailed next debug steps** (numbered, exact commands per step, decision branches)
- **F. Data & commands to collect** (consolidated copy-pasteable command block + metadata:
  RPT/rpt.gz fields, ucode/IFWI/BIOS rev, cluster, bucket, POST code)
- **G. Learning summary** (KB entry created/updated, confidence tag, how future queries answer)
- **H. Known-issue verdict** (known — cite HSD — or new sighting)

## GUARDRAILS
- Only cite HSD IDs that actually exist in KB or HSDES results. Never invent IDs,
  root causes, or commands.
- State assumptions explicitly; request missing data (stepping, bucket, ucode).
- Keep entries GNR/SRF/CWF-scoped and stepping-aware; do not cross-apply blindly.
