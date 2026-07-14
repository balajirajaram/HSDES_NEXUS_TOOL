# Auto HSD Analyser — Option D (Run locally in GitHub Copilot)

The **zero-setup, zero-token** way to use the HSD Analyser. Every engineer runs it
**inside VS Code with GitHub Copilot (GHCP)** on their own laptop. Because Copilot uses
each person's **own** Intel MCP authentication, there is **nothing to share** — no
tokens, no server, no deployment.

This is a **hybrid triage-and-debug** tool: the `/auto-hsd-analyser` prompt orchestrates a
set of **BugScout-derived skills** to triage ANY reported HSD across **all GNR/SRF/CWF
domains** (core, CHA/uncore, IMC/memory, mesh/fabric, UPI/KTI, IIO/PCIe/CXL, power/PM,
accelerators, security, RDT, boot/RAS), suggest the possible root cause, and hand the
engineer an **exact list of commands** to collect the next-step data. It emits both an
A–H markdown report and a BugScout-style **HTML report**.

```
option-d-copilot/
├─ .github/prompts/auto-hsd-analyser.prompt.md   ← auto-discovered orchestrator (hybrid)
├─ auto-hsd-analyser.prompt.md                    ← same file, for easy viewing
├─ .copilot/skills/                               ← BugScout skills, all GNR/SRF/CWF domains
│   ├─ hsd-triage/        ← multi-phase triage + debug plan WITH commands + report emit
│   ├─ handbook-rag/      ← self-learning KB recall + handbook & command grounding
│   ├─ log-search/        ← index/grep RPT, .elog.gz, serial/PythonSV logs
│   ├─ live-debug/        ← iterative hypothesis loop when you have live/PythonSV access
│   └─ crash-parser/      ← normalize crashdump / MCE-MCA bank summaries
├─ docs/
│   ├─ command_library.md ← ALL-DOMAIN PythonSV/cscripts/OS/BMC command catalog
│   └─ handbooks/         ← rdt_upi_debug_steps.md (+ acd_debug_steps.md) pattern grounding
├─ templates/auto-hsd-report-template.html        ← BugScout HTML report template
├─ src/                   ← OPTIONAL Python engine (large-log indexer, batch pipeline)
├─ schemas/               ← live-debug input schema
└─ README.md                                       ← you are here
```

### What's integrated from BugScout
| BugScout piece | How it's used here |
|---|---|
| `hsd-triage` skill | Adapted to **all GNR/SRF/CWF domains**; **HSDTool/HSDIndexTool primary** (co-design `ask-hsd-agent` is fallback only — it cancels in some environments). Outputs root cause + exact next-step commands. |
| `handbook-rag` + KB | Backed by the co-design debug **memory KB** (self-learning) + `docs/handbooks/` patterns + `docs/command_library.md` (all-domain commands). |
| `log-search` | Copilot-native (`grep_search`/`read_file`) by default; optional Python `src/cache_log_search` for huge logs. |
| `live-debug` | Iterative PythonSV debug loop with confirmation gates. |
| `crash-parser` | MCE/MCA + crashdump normalization with an RDT/UPI bank map. |
| HTML report template | `templates/auto-hsd-report-template.html`, filled per run. |

---

## What each user needs (one-time)

1. **VS Code** (latest).
2. **GitHub Copilot + Copilot Chat** extensions, signed in with an account that has
   Copilot enabled at Intel.
3. The **Intel MCP tools** that back the analysis, available in Copilot Chat:
   - `HSDTool` / `HSDIndexTool` — **primary** HSDES access (keyword/SQL + semantic)
   - `codesign-debug-search-in-memories` / `codesign-debug-store-memory` (the learning KB)
   - `codesign-ask-hsd-agent-mcp` — optional fallback for HSD lookups

   These come from the Intel Geni / co-design Copilot plugin. If a teammate doesn't
   have them, they install the same plugin you use (see your team's Geni onboarding),
   then run the `acquire-tokens` step once so `HSDIndexTool` can authenticate **as
   them**.

No HSDES token is copied or shared — each person authenticates through their own
Copilot session.

---

## Install the prompt (pick one)

### Option 1 — Use this folder as the workspace (simplest)
1. Open the `option-d-copilot` folder in VS Code (`File ▸ Open Folder…`).
2. VS Code auto-discovers `.github/prompts/auto-hsd-analyser.prompt.md`.
3. Done — skip to **Run it**.

### Option 2 — Add it to your own project
Copy the prompt into your repo's prompt folder:
```powershell
New-Item -ItemType Directory -Force .github\prompts | Out-Null
Copy-Item path\to\option-d-copilot\.github\prompts\auto-hsd-analyser.prompt.md .github\prompts\
```

### Option 3 — Make it available in every workspace (personal)
Copy it to your VS Code user prompts folder so it's always available:
```powershell
Copy-Item .github\prompts\auto-hsd-analyser.prompt.md "$env:APPDATA\Code\User\prompts\"
```

---

## Run it

1. Open **Copilot Chat** (`Ctrl+Alt+I`).
2. Set the chat mode to **Agent** (dropdown at the top of the chat box).
3. Type:
   ```
   /auto-hsd-analyser
   ```
   (or open the `.prompt.md` file and press the ▶ **Run** button).
4. Enter the two inputs when prompted:
   - **HSD ID** — e.g. `1234567890`
   - **Symptoms** — e.g. `UPI CRC error, MCE bank 5, GNR B0, bucket=upi_link_retrain`

The agent produces the full A–H triage report (target-HSD summary, KB recall, similar
HSDs, ranked root causes, PythonSV debug plan, data-to-collect, learning summary,
known-issue verdict), writes the case back into the learning KB, and emits a filled
HTML report to `output/hsd_<id>_<timestamp>/session_report.html`.

### Other entry points (skills)
- **Live debug:** `live-debug HSD <id> ... max 5 iterations` — iterative PythonSV loop.
- **Log search:** `search logs in <path> for UPI CRC credit` — grep with context.
- **Crash parse:** point crash-parser at a crashdump JSON / MCE text dump.

### Optional Python engine
For very large logs or batch runs, `src/` ships the BugScout pipeline
(`cache_log_search` indexer, `parse_and_triage.py`, handbook builder). It is **optional** —
the skills work without it. Requires a local Python 3 with the repo on `PYTHONPATH`.

---

## Why this needs no shared token
- Copilot's MCP servers run **locally, inside each user's VS Code**, authenticated as
  that user.
- The prompt calls those tools; every user's queries hit HSDES/KB **as themselves**.
- Result: same capability as the hosted web tool, but nothing to distribute or secure.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/auto-hsd-analyser` doesn't appear | Ensure the file is in a discovered prompts location (Option 1/2/3). Reload VS Code. |
| "Tool not found" / no HSDES data | The Intel Geni/co-design MCP plugin isn't installed or not authenticated. Install it and run the `acquire-tokens` step. |
| Tool calls show **"cancelled"** (you didn't cancel) | Two causes: (a) MCP tools were called in a **parallel batch** and one failed input validation — the tool now calls them one at a time; (b) `codesign-ask-hsd-agent-mcp` cancels in some environments — the tool uses **`HSDTool` as primary** instead. |
| KB tool error `cluster_stepping must not be empty` | The KB tools need a non-empty `cluster_stepping` + `bucket`; the tool derives these from the HSD first. Provide the stepping if the ticket lacks one. |
| Auth errors on `HSDIndexTool` | Tokens expired — re-run `acquire-tokens`. |
| Report has no similar HSDs | KB is empty and/or HSDES returned nothing; try richer symptom terms (unit, bucket, MCE bank, stepping). |

---

## Sharing this with the team
Just point teammates at this folder (or the repo) and this README. Each person installs
Copilot + the Intel MCP plugin once, drops in the prompt, and runs `/auto-hsd-analyser`.

Intel Internal Use Only.
