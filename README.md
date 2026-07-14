# Auto HSD Analyser (Server Platforms)

A self-learning **HSD-ES triage tool** for Intel **server platforms** — works across **any
domain**: CPU/silicon RAS (MCA/MCE/IERR/CATERR), UPI/coherency, memory (DDR/DIMM/training),
IO (PCIe/CXL), power & sleep states (S3/S4/S5/Sx, ACPI), BIOS/IFWI/BMC/CPLD and boot/hang,
OS/driver (Windows/Linux), and manageability. It is **not** tied to any single unit like
RDT or UPI. It ships in **two forms**:

1. **Web app** (this repo's `app/`) — a browser UI + Python backend that runs the
   triage itself: recalls from a local learning KB, reads the HSD, calls an LLM to
   reason, and writes findings back to the KB.
2. **VS Code Copilot prompt** ([prompts/auto-hsd-analyser.prompt.md](prompts/auto-hsd-analyser.prompt.md)) —
   the same agent spec, runnable inside Copilot Chat with the Intel MCP tools.

> Scope: **any Intel server-platform HSD**, across all domains and platforms
> (GNR, SRF, CWF, SPR, EMR, Eagle Stream, Birch Stream, and beyond).

---

## What it does

For a given **HSD ID** + **symptoms**, it produces a structured report (sections A–H):
target-HSD summary, KB recall confidence, similar cases, ranked root-cause hypotheses,
an ordered PythonSV debug plan, data-to-collect, a learning summary, and a
known-issue verdict. Every run **grows the Knowledge Base** so future queries with the
same signature are answered faster.

```
Step 0 RECALL      -> search local KB, score confidence (High/Medium/Low/None)
Step 1 DECIDE      -> High = KB-first; else HSDES fallback
Step 2 INVESTIGATE -> fetch target HSD + similar HSDs
Step 3 WRITE-BACK  -> upsert KB entry (confirmed vs hypothesis)
Step 4 REPORT      -> A-H markdown report
```

---

## Run the web tool (UI)

### Prerequisites
- Python 3.10+
- (Optional but recommended) an HSDES REST API token and an OpenAI-compatible LLM
  endpoint. Without them the tool runs in **OFFLINE mode** (deterministic report,
  KB still learns the signature).

### Start it (Windows PowerShell)
```powershell
# from the repo root
./run.ps1
```
This creates a venv, installs dependencies, copies `.env.example` -> `.env` on first
run, and serves the UI at **http://127.0.0.1:8000**.

### Manual start (any OS)
```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env          # then edit .env
uvicorn app.main:app --reload
```

### Configure full mode
Edit `.env`:
```
HSDES_API_TOKEN=<your token>          # enables live HSDES lookups
LLM_BASE_URL=<openai-compatible url>  # e.g. Azure OpenAI / internal gateway
LLM_API_KEY=<key>
LLM_MODEL=gpt-4o
```
The status badges at the top of the UI show whether HSDES / LLM are active.

> The HSDES field mapping in [app/hsdes_client.py](app/hsdes_client.py) is best-effort;
> adjust `_normalize` / `search_similar` to match your tenant's actual REST contract.

---

## Use the VS Code Copilot prompt (alternative)

1. Open this folder in VS Code with GitHub Copilot Chat enabled (Agent mode).
2. Run `/auto-hsd-analyser` in chat, or open
   [prompts/auto-hsd-analyser.prompt.md](prompts/auto-hsd-analyser.prompt.md) and press ▶.
3. Enter the **HSD ID** and **Symptoms** when prompted.

This path uses the Intel MCP tools (`codesign-debug-*`, `codesign-ask-hsd-agent` /
`HSDIndexTool`) instead of the built-in HSDES/LLM clients.

---

## Repository layout

| Path | Purpose |
|------|---------|
| [app/](app/) | FastAPI backend + browser UI (the runnable tool). |
| [app/analyzer.py](app/analyzer.py) | The self-learning loop orchestration. |
| [app/kb_store.py](app/kb_store.py) | SQLite learning Knowledge Base (recall + write-back). |
| [app/hsdes_client.py](app/hsdes_client.py) | HSDES REST client (best-effort). |
| [app/llm_client.py](app/llm_client.py) | OpenAI-compatible chat client. |
| [app/static/](app/static/) | HTML / CSS / JS single-page UI. |
| [prompts/auto-hsd-analyser.prompt.md](prompts/auto-hsd-analyser.prompt.md) | VS Code Copilot prompt version. |
| [docs/AGENT_SPEC.md](docs/AGENT_SPEC.md) | Full human-readable agent spec. |
| [docs/KB_SCHEMA.md](docs/KB_SCHEMA.md) | KB entry schema. |
| [docs/SHARING.md](docs/SHARING.md) | How to publish and share this repo. |
| [run.ps1](run.ps1) | One-command launcher. |

---

## API (for automation)

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/api/health` | Mode + HSDES/LLM/KB status. |
| `POST` | `/api/analyze` | Body `{ "hsd_id": "...", "symptoms": "..." }` -> full result JSON. |
| `GET` | `/api/kb` | List all learned KB entries. |

Example:
```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"hsd_id":"1234567890","symptoms":"UPI CRC error, MCE bank 5, GNR B0"}'
```

---

## Guardrails

- Never invents HSD IDs, register names, root causes, or commands.
- HSDES is the source of truth; conflicting KB entries are corrected and re-tagged.
- Every KB entry is tagged **confirmed** vs **hypothesis**, with provenance + timestamp.
- Raw silicon data (RPT, waveforms, dumps) is `.gitignore`d and must never be committed.

---

## Sharing

See [docs/SHARING.md](docs/SHARING.md). This is **Intel Internal** — host on Intel
Innersource or another approved internal Git server.
