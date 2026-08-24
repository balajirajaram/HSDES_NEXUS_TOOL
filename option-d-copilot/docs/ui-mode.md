# UI Mode

Use UI mode to open generated reports and demo assets from a local dashboard.

## Quick Start (Windows)

From repository root, run:

```bat
run_ui_mode.bat
```

This will:
- start a local server
- auto-open your browser to the dashboard
- show latest report + report history + demo docs links

Stop UI mode with `Ctrl+C` in the terminal.

## Direct Python Command

```powershell
python src/ui_mode.py
```

Optional flags:

```powershell
python src/ui_mode.py --port 9000 --host 127.0.0.1 --no-browser
```

## What You Get

- One-click "Open latest report"
- List of all `output/**/session_report.html`
- Quick links to:
  - `docs/how-it-works-flowchart.html`
  - `docs/how-it-works-flowchart.png`
  - `docs/management-overview.md`
  - `docs/demo-guide.md`
