# Auto HSD Analyser (RDT and UPI) - Team Usage Guide

Note: This folder is now integrated into the unified root tool.

Preferred entrypoint from repository root:

    .\run_power_tool.ps1 --help

Direct merged commands:

    .\run_power_tool.ps1 serve --reload
    .\run_power_tool.ps1 optiond prepare --input C:\path\to\input.csv
    .\run_power_tool.ps1 optiond finalize --responses C:\path\to\responses.jsonl
    .\run_power_tool.ps1 optiond report --input C:\path\to\triage_results.csv

This keeps root workflows and OptionD workflows in one command surface.

This repository helps validation and debug teams generate structured HSD analysis reports for faster triage, knowledge reuse, and management-ready communication.

Default behavior now includes evidence-first analysis:
- HSD attachments are always enumerated and extraction is attempted
- AXON correlation is always attempted
- Any fallback (metadata-only attachments, AXON unavailable) is explicitly called out in the report

It supports two practical usage modes:
- Prompt-first mode in VS Code Copilot (main product flow)
- Local UI mode for browsing reports and demo assets

## 1. What This Tool Delivers

For each analyzed HSD, the workflow generates a session folder under output with:
- session_report.html (shareable report)
- analysis context and intermediate artifacts
- optional knowledge-base memory entries for future reuse

The report follows the A-H structure:
- A: Ticket Summary
- B: Prior Knowledge Recall
- C: Similar HSD References
- D: Root Cause Hypotheses
- E: Exact Debug Steps and Commands
- F: Command Block for Reuse
- G: Learning Summary
- H: Verdict and Next Action

## 2. Repository Layout

Key locations:
- src: Python support scripts and orchestrators
- docs: management flow, demo guide, handbooks
- templates: HTML templates used for report generation
- output: generated per-ticket analysis sessions

Useful docs:
- docs/management-overview.md
- docs/demo-guide.md
- docs/ui-mode.md
- docs/how-it-works-flowchart.html
- docs/how-it-works-flowchart.png

## 3. Prerequisites

- Windows environment (tested in VS Code)
- Python 3.10+ recommended
- Access to required Intel MCP tools for HSD retrieval (when running full live analysis)

## 4. Setup

From repository root:

    python -m venv .venv
    .venv\Scripts\activate
    python -m pip install --upgrade pip

If your team has a standard dependency file, install it here.
If not, keep using the currently validated environment used in VS Code.

## 5. Quick Start for Team Members

### Option A: UI Mode (Easiest for Demos and Review)

Run from repository root:

    run_ui_mode.bat

What opens:
- Local dashboard in browser
- One-click latest report
- List of all generated reports
- Links to flowchart and demo/management docs

Stop with Ctrl+C in terminal.

### Option B: Prompt-First Mode in VS Code (Default Analysis Mode)

1. Open this repository in VS Code.
2. Use the project prompt flow from:
    - auto-hsd-analyser.prompt.md
3. Provide HSD ticket id when asked.
4. Review generated report in output folder.
5. Confirm report includes:
    - Attachment Evidence Summary
    - AXON Correlation Summary
    - Evidence Confidence Matrix

## 6. Running a Fresh Analysis

Recommended operational flow:

1. Start from a clean ticket id.
2. Run the analysis workflow (prompt-first path).
3. Confirm the report is generated in output/hsd_<id>_<timestamp>/session_report.html.
4. Open and validate sections A-H.
5. Validate evidence sections for attachment/AXON status.
6. Compare report conclusions with latest live HSD details if needed.
7. Share the HTML report and key findings.

## 7. Share With Management

Use these assets directly:
- docs/how-it-works-flowchart.png (slides-friendly)
- docs/how-it-works-flowchart.html (interactive view)
- docs/management-overview.md (narrative)
- docs/demo-guide.md (step-by-step talk track)

Recommended demo sequence:
1. Explain workflow with flowchart.
2. Show one completed report in output.
3. Walk through A-H sections and verdict.
4. Show how similar tickets and memory improve repeat debugging.

## 8. Common Commands

Start UI mode:

    run_ui_mode.bat

Direct UI mode with Python:

    python src/ui_mode.py

Custom port:

    python src/ui_mode.py --port 9000 --host 127.0.0.1

Compile check:

    python -m compileall src

## 9. Troubleshooting

Issue: UI mode does not auto-open browser
- Copy dashboard URL shown in terminal and open manually.

Issue: No reports listed in UI
- Ensure reports exist under output and include session_report.html.

Issue: report-only rendering for old sessions
- Use the updated runner logic that supports both output and legacy src/output session paths.

Issue: MCP tool call failures or auth interruptions
- Retry after re-authentication and run analysis steps sequentially.

## 10. Team Operating Guidance

- Treat generated report wording as draft debug intelligence unless HSD status is formally resolved.
- Always verify final root-cause claims against the latest live ticket revision and comments.
- Keep report language explicit:
  - Cause identified, fix validation pending
  - Or Root cause confirmed and closed

## 11. Current Demo-Ready Outputs

Sample ready reports:
- output/hsd_16031306835_20260810_071240/session_report.html
- output/hsd_16030937086_20260810_084011/session_report.html

Flow and guide assets:
- docs/management-overview.md
- docs/demo-guide.md
- docs/how-it-works-flowchart.png
- docs/how-it-works-flowchart.svg

## 12. Next Recommended Improvements

- Add a small input form in UI mode to trigger new analysis directly.
- Add a single command that creates report and opens it automatically.
- Add a lightweight release checklist for team handoff quality.

---

If you are sharing this with new team members, start with section 5 (Quick Start) and section 7 (Share With Management).
