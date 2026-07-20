# Auto HSD Analyser (Server Platforms)

An **agentic HSD-ES triage assistant** for Intel server platforms. Give it an **HSD ID**
and it will:

1. **Read** the ticket fully from HSDES (title, description, and the whole comment thread),
2. **Compare** it against a self-learning Knowledge Base seeded from your product master
   queries (GNR / SRF / CWF today; DMR / COR ready to add),
3. **Report** a structured triage: summary, similar past issues **with their root cause and
   how they were resolved**, ranked hypotheses, and **domain-specific next steps + PythonSV
   commands**,
4. **Learn** — every ticket it sees is written back into the KB, so it gets smarter over time.

> Status: **validated live against real HSDES** using Intel Kerberos SSO (no password, no
> token). Works for any teammate on the Intel network/domain.

Scope: **any server-platform domain** — RAS/MCA, UPI/coherency, memory, PCIe/CXL,
power/S-states, BIOS/IFWI/BMC/boot-hang, OS/driver. Not tied to any single unit.

---

## Prerequisites (each user, one-time)

- **Windows on the Intel domain** (so Kerberos SSO to HSDES works with your existing login)
- **Python 3.10+** (`python --version`)
- Network access to `https://hsdes-api.intel.com`
- (Optional) an OpenAI-compatible LLM endpoint for full prose reasoning — the tool works
  fully without it in deterministic "offline" mode.

No HSDES token or password is needed — it authenticates as **you** via Kerberos.

---

## How to share this with your team

The whole tool is this folder. Share it any of these ways:

### Option 1 — Zip and send (simplest)
From the project's parent folder:
```powershell
# Exclude local/regenerated files so the zip stays small and clean
$exclude = @('.venv','kb\*.sqlite','.env','__pycache__')
Compress-Archive -Path '.\Auto_HSD_analyser_RDT and UPI\*' -DestinationPath '.\AutoHSDAnalyser.zip' -Force
```
Send `AutoHSDAnalyser.zip`. The recipient unzips it anywhere and follows **Setup & run** below.
(The `.venv`, `.env`, and `kb/*.sqlite` are per-machine and are recreated automatically.)

### Option 2 — Internal Git (best for updates)
Push to Intel Innersource / any internal Git, then teammates clone:
```powershell
git clone <internal-repo-url> auto-hsd-analyser
```
(See `docs/SHARING.md` for the exact publish steps.)

### Option 3 — Shared drive
Copy the folder to a shared location. Each user copies it **locally** before running
(don't run from the share, so each person gets their own `.venv`/`.env`/KB).

> Never commit or share `.env` or `kb/*.sqlite` — they're per-user and already git-ignored.

---

## Setup & run (Windows PowerShell)

```powershell
cd "auto-hsd-analyser"        # the folder you copied/cloned
./run.ps1
```
`run.ps1` will, on first run:
- create a virtual environment (`.venv`),
- install dependencies (incl. `requests-kerberos` for SSO),
- create `.env` from the template (defaults to `HSDES_AUTH_MODE=auto` — Kerberos),
- start the web app at **http://127.0.0.1:8000**.

If PowerShell blocks the script the first time:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then open **http://127.0.0.1:8000**, type an **HSD ID** + a short **symptom** line, and
click **Analyse**.

---

## Where your analysis is saved

**Every** analysis — whether run from the web UI or the command line — is saved as a
Markdown file in the **`output\`** folder inside the project:

```
<project>\output\hsd_<HSD_ID>_<YYYYMMDD_HHMMSS>.md
```

Example: `output\hsd_16030948515_20260720_143512.md`

- The web UI shows the saved path in the result header after each run.
- The CLI (`python -m app.summarize`) prints the saved path at the end.
- Files are timestamped, so re-analysing the same HSD keeps every version.
- `output\` is git-ignored (reports may contain HSD data) — it stays on your machine.

To open the folder quickly:
```powershell
explorer .\output          # or:  Get-ChildItem .\output\*.md
```

---

## Using it

### Web UI
- **Analyse tab** — enter HSD ID + symptoms → full A–H report.
- **Knowledge Base tab** — browse everything the tool has learned.

### Seed the Knowledge Base from your master queries (recommended)
The more it has learned, the better the "similar issues" comparison. Seed per product:
```powershell
python -m app.batch_learn --product GNR      # learns all GNR master-query tickets
python -m app.batch_learn --product SRF
python -m app.batch_learn --product CWF
python -m app.batch_learn --ids 16030948515 22022875184   # or specific IDs
```

### Command line (no browser)
```powershell
python -m app.summarize 16030948515                 # analyze + save report to output/
python -m app.summarize 14028261445 --log serial.log  # also scan an attached log
```

### Analyze attached logs
Paste a log (serial / PythonSV / BMC SEL / OS kernel / RPT) into the **Attached log** box
in the UI, or pass `--log <file>` on the CLI. The tool scans it for MCE/CATERR/IERR,
UPI/DDR/PCIe, boot-hang, and OS-panic signatures and adds an **"A2. Attached log
analysis"** section (severity-ranked, with the last POST checkpoint and **MCA decode** —
MCi_STATUS → flags/MCACOD/MSCOD) that feeds the root-cause hypotheses and next steps.

### Auto-fetch the logs already on the ticket
Tick **"Auto-fetch attachments"** in the UI, or pass `--fetch-attachments` on the CLI:
```powershell
python -m app.summarize 16030948515 --fetch-attachments
```
The tool downloads the ticket's attached resources (zip/gz/text) from HSDES, extracts the
logs, and analyzes them automatically — no manual download needed.

### HTTP API (for automation)
| Method | Route | Purpose |
|--------|-------|---------|
| `POST` | `/api/analyze` | `{ "hsd_id": "...", "symptoms": "..." }` → full result |
| `POST` | `/api/batch_learn` | `{ "product": "GNR" }` or `{ "query_id": "..." }` or `{ "hsd_ids": [...] }` |
| `GET`  | `/api/kb` | list learned cases |
| `GET`  | `/api/products` | list products + their master queries |
| `GET`  | `/api/health` | auth mode / KB size |

---

## Adding a product (e.g. DMR, COR)

Edit [app/products.json](app/products.json) — add the product's aliases, families, and the
saved **HSDES query id(s)**. No code change needed:
```jsonc
"DMR": {
  "display": "Diamond Rapids",
  "aliases": ["DMR", "Diamond Rapids"],
  "master_queries": ["<saved-query-id>"]
}
```

Current registry: **GNR** (2 queries), **SRF** (2), **CWF** (5), **DMR/COR** (placeholders).

---

## Optional: full LLM reasoning

Set these in `.env` to turn the deterministic report into full prose root-cause analysis:
```
LLM_BASE_URL=<openai-compatible endpoint>
LLM_API_KEY=<key>
LLM_MODEL=gpt-4o
```
Without them, the tool runs in **offline mode** (deterministic, still fully useful).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `run.ps1` blocked | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` |
| Auth/401 to HSDES | Ensure you're on the Intel domain and logged in; confirm `HSDES_AUTH_MODE=auto` in `.env` |
| `requests-kerberos` install fails | `pip install requests-kerberos` inside `.venv`; ensure Windows/Intel domain |
| Empty analysis / no ticket data | Check network to `hsdes-api.intel.com`; try the ID in a browser first |
| Query returns 0 tickets | The saved query may be in a scope your account can't read; try `--ids` directly |

---

## Notes
- **Intel Internal Use Only.** Do not commit `.env`, `kb/*.sqlite`, or raw silicon logs.
- An **SSO-hosted variant** (one shared web app, per-user Intel SSO) lives in `option-c-sso/`
  and will be finished later.
- A **VS Code Copilot prompt** version is in `option-d-copilot/` for those who prefer to run
  it inside GitHub Copilot chat.
