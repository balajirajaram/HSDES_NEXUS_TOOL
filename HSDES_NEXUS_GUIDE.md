# HSDES NEXUS — Team Guide

**HSD Triage & Root-Cause tool.** Give it an HSD ID; it reads the ticket + attached logs,
decodes the failure (MCA / BIOS / POST / Axon), and produces a root-cause report with
evidence, spec references, and next steps — as a web page, an HTML file, and a Markdown file.

Works on the Intel network using your Kerberos login — **no HSDES token or password needed.**

---

## 1. One-time setup

**Prerequisites**
- Windows on the Intel domain (Kerberos SSO to HSDES)
- Python 3.10+ (`python --version`)
- Network access to `https://hsdes-api.intel.com`

**Steps**
1. Copy/unzip the tool folder anywhere on your machine.
2. Open **PowerShell** in the tool folder.
3. Allow scripts for this shell:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
   ```

That's it. The launcher creates the virtual environment and installs dependencies on first run.

---

## 2. Quick start — Web UI (recommended)

```powershell
./run.ps1
```

Then open **http://127.0.0.1:8000** in your browser.

`run.ps1` automatically: creates `.venv`, installs requirements, refreshes the Axon token
(Kerberos, ~30-min validity), and starts the server. Stop it with **Ctrl+C**.

### Web UI tabs
| Tab | What it does |
|-----|--------------|
| **Analyse** | Enter an **HSD ID** + a short symptom → full root-cause report. Start here. |
| **Batch Learn** | Feed many HSDs (by product / query ID / list of IDs) into the self-learning Knowledge Base. |
| **Live Debug** | Bootstrap an interactive, iterative debug session for one open HSD (see §5). |
| **BugScout Batch** | Run the batch triage pipeline: **prepare → finalize → report** over a CSV of HSDs. |
| **Crashdump** | Parse a crashdump JSON into a readable summary. |
| **Log Search** | Index and keyword-search a large local log file. |
| **Handbook RAG** | Retrieve answers from the Silicon Handbook. |
| **Knowledge Base** | Browse what the tool has learned so far. |

**Typical first use:** open the **Analyse** tab → type an HSD ID (e.g. `16031274908`) and a
one-line symptom (e.g. `node hang / IERR`) → **Analyse**. The report appears on screen and is
also saved to the `output/` folder as `.html` and `.md`.

---

## 3. CLI usage

Everything the UI does is available from the command line through one entrypoint.

```powershell
./run_power_tool.ps1 <command> [options]
```

Run with no arguments to see all commands:
```powershell
./run_power_tool.ps1
```

### Analyse a single HSD
```powershell
./run_power_tool.ps1 summarize 16031274908 "node hang / IERR"
```
Options:
- `--log <path>` — also analyse a local log file (`.txt` / `.log` / `.gz`)
- `--no-attachments` — skip downloading HSDES attachments (faster, ticket-text only)
- `--no-transferred` — don't follow transferred sub-team tickets

Reports are written to `output/hsd_<id>_<timestamp>.md` and `.html`.

### Start the web server from the CLI
```powershell
./run_power_tool.ps1 serve --reload
```

### Teach the Knowledge Base in bulk
```powershell
./run_power_tool.ps1 batch-learn --product GNR --limit 50
./run_power_tool.ps1 batch-learn --ids 16031274908 16030948515
```

> Tip: the plain Python form works too, e.g. `python -m app.summarize 16031274908 "IERR"`.

---

## 4. BugScout batch pipeline (CLI)

For triaging a whole CSV of HSDs at once:

```powershell
# 1. Build the prompts from your input CSV
./run_power_tool.ps1 optiond prepare --input C:\temp\hsds.csv

# 2. Finalize after the model responses are collected
./run_power_tool.ps1 optiond finalize --responses C:\temp\responses.jsonl --output-dir C:\temp\out

# 3. Render the HTML report
./run_power_tool.ps1 optiond report --input C:\temp\hsds.csv --output-dir C:\temp\out

# List all previous batch + live-debug runs
./run_power_tool.ps1 optiond runs
```

You can also drive this from the **BugScout Batch** tab in the Web UI.

---

## 5. Live debugging

Live Debug runs an **interactive, iterative** session for a single open HSD — it proposes
hypotheses, tells you which logs/registers to collect, you feed results back, and it
converges on a root cause over several iterations.

### From the Web UI
Open the **Live Debug** tab → enter the HSD ID and options → start the session → follow the
per-iteration prompts. When done, render the session report from its session ID.

### From the CLI
```powershell
# Start a session (manual mode = you paste in the logs it asks for)
./run_power_tool.ps1 optiond live-debug --hsd-id 16031274908 --execution-mode manual --max-iterations 10

# Render the report for an existing session
./run_power_tool.ps1 optiond ui-mode        # optional: OptionD UI helper
```

Options for `live-debug`:
- `--execution-mode manual` — you supply logs interactively (default, no server access needed)
- `--server <host>` `--ssh-user <user>` — auto-collect logs over SSH (if you have access)
- `--initial-logs <file.json>` — logs already gathered, so it won't re-ask
- `--max-iterations <n>` — cap the debug loop

Live-debug reports are saved under the run/session folder and are branded **HSDES NEXUS —
Live-Debug**.

---

## 6. Reading the report

Each report has:
- **Header** — clickable HSD link, status/priority/owner, and a result badge.
- **Root-Cause box** — the headline conclusion (green = found; amber = dispositioned / needs data).
- **Session Parameters** — ticket, attachments scanned, log volume.
- **Boot / Stage Progress** — how far boot got (SEC → OS).
- **Ranked Hypotheses** — decoded candidates by severity.
- **Evidence From Attached Logs** — IERR/MCA decode, log excerpts, Axon signatures, last POST.
- **Final Root Cause** — evidence chain + recommended fix/next steps + **Spec References**.
- **Root-Cause Evidence** — which of the 10 key facts were decoded, and the exact commands to
  collect the ones still missing.
- **Related HSDs** — similar / clone / transferred tickets.

**Two things worth knowing:**
- If a ticket **booted to OS** and is already **rejected/implemented** (or is a
  display/config/frequency topic), the tool marks any machine-check as *incidental background
  telemetry* and leads with the ticket's real subject instead.
- "Log keyword mentions" style raw counts are **matching log lines**, not distinct hardware
  events — the confirmed signal is the **decoded MCA**.

---

## 7. Where things are saved
- Single-HSD reports → `output/`
- Batch / live-debug runs → `option-d-copilot/output/` (and the folder printed on screen)
- Learned cases → `kb/`

---

## 8. Troubleshooting

| Symptom | Fix |
|--------|-----|
| `running scripts is disabled` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` first. |
| Can't reach the page | Make sure `./run.ps1` is still running; open `http://127.0.0.1:8000`. |
| Report is thin / "attachment fetch incomplete" banner | Transient HSDES fetch hiccup — just re-run the analysis. |
| Axon signatures show "not fetched" | Re-run `./run.ps1` (it refreshes the ~30-min Axon token), or set `AXON_GENI_TOKEN` in `.env`. |
| 401 / "Please sign in" | Confirm you're on the Intel domain/network (Kerberos SSO); try again. |

---

**Questions or improvements?** Ping the tool owner. Happy triaging with **HSDES NEXUS**.
