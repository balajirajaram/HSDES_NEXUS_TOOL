# Demo Guide — Auto HSD Analyser

Step-by-step instructions to set up, run, and demo the tool. Target: a clean 5-minute
management demo using one real HSD.

---

## Part 1 — One-time setup

1. Install **VS Code** (latest).
2. Install **GitHub Copilot** + **GitHub Copilot Chat** extensions; sign in with an
   Intel-enabled Copilot account.
3. Ensure the **Intel Geni / co-design MCP plugin** is installed in Copilot Chat so these
   tools are available:
   - `HSDTool` / `HSDIndexTool` (HSDES access)
   - `codesign-debug-search-in-memories` / `codesign-debug-store-memory` (learning KB)
4. Open this folder in VS Code: **File ▸ Open Folder…** → select `option-d-copilot`.
5. VS Code auto-discovers the prompt at `.github/prompts/auto-hsd-analyser.prompt.md`.

**Verify setup (30 seconds):**
- Open Copilot Chat (`Ctrl+Alt+I`), set mode to **Agent**.
- Type `/` and confirm `auto-hsd-analyser` appears in the list.

---

## Part 2 — Run the tool (the core flow)

1. Open **Copilot Chat** (`Ctrl+Alt+I`).
2. Set chat mode to **Agent** (dropdown at top of the chat box).
3. Type:
   ```
   /auto-hsd-analyser
   ```
4. Enter the two inputs when prompted:
   - **HSD ID** — e.g. `16030948515`
   - **Symptoms** — e.g. `System hang after UPI degradation, KitPortDisable=1, GNR AP 2S`
5. Let the agent run. It will:
   - Recall the learned KB
   - Fetch the HSD from HSDES
   - Find similar past HSDs
   - Rank root-cause hypotheses
   - List exact next-step debug commands
   - Save an HTML report under `output/hsd_<id>_<timestamp>/session_report.html`

---

## Part 3 — The 5-minute management demo (script)

**Example case:** HSD `16030948515` — GNR AP 2S system hang after UPI degradation.
A pre-generated sample report already exists at
`output/hsd_16030948515_20260709/session_report.html`.

| # | Time | Do this | Say this |
|---|------|---------|----------|
| 1 | 0:00 | Open `README.md` | "This runs inside VS Code with Copilot — no server, no shared token. Each engineer uses their own Intel access." |
| 2 | 0:30 | Open `.github/prompts/auto-hsd-analyser.prompt.md` | "This prompt is the whole product. The engineer gives only an HSD ID and a few symptom words." |
| 3 | 1:00 | In Copilot Chat (Agent mode), run `/auto-hsd-analyser` with HSD `16030948515` | "Watch it recall similar cases, pull the ticket, and reason about root cause." |
| 4 | 2:30 | Scroll the response to the ranked hypotheses | "It separates confirmed facts from hypotheses — no fabrication." |
| 5 | 3:15 | Point to the exact-command section | "It never says 'collect more logs.' It gives the exact PythonSV / OS / BMC commands to run next." |
| 6 | 4:00 | Open `output/hsd_16030948515_20260709/session_report.html` | "Every run produces a shareable report. Here's the strongest analog — HSD 16024158116 — showing UPI0 disable is DFx-only; at least one UPI link must stay active." |
| 7 | 4:45 | Close | "Net effect: faster debug convergence, and every solved case makes the next one faster." |

**Backup plan (if live MCP is slow or unavailable):** demo directly from the saved report
at `output/hsd_16030948515_20260709/session_report.html` and walk through the same steps.

---

## Part 4 — Optional Python engine (only if asked)

The `src/` engine is optional — the skills work without it. Verified commands from the
repo root:

```powershell
# Show CLI help
python src/parse_and_triage.py --help

# Bootstrap a live-debug session (writes to output/live_debug_<session_id>/)
python src/parse_and_triage.py --mode live-debug --hsd-id 16030948515 --max-iterations 1

# Render HTML + Markdown + JSON reports for a session
python src/live_debug_runner.py --report-only <session_id>

# Quick code-health check
python -m compileall src
```

Report templates live in `templates/`:
- `auto-hsd-report-template.html` — batch triage report
- `live_debug_report_template.html` — live-debug session report

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/auto-hsd-analyser` not listed | Reload VS Code; confirm the file is under a discovered prompts folder. |
| "Tool not found" / no HSDES data | Intel MCP plugin not installed or not authenticated; install it and run `acquire-tokens`. |
| Tool calls show "cancelled" (you didn't cancel) | The prompt calls MCP tools one at a time and uses `HSDTool` as primary to avoid this. |
| `--report-only` can't find an old session | Older sessions may sit under `src/output/`; the code checks both legacy and current paths. |
| Report has no similar HSDs | Try richer symptom terms (unit, bucket, MCE bank, stepping). |

*Intel Internal Use Only.*
