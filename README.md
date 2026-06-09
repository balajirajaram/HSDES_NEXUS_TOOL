# BugScout 🔍

> AI-powered hardware bug triage and live debug skills for Intel silicon validation.

BugScout packages two Copilot CLI skills — **hsd-triage** and **live-debug** — as installable `.copilot/skills/` packages, alongside the full source pipeline, report templates, schemas, and reference samples.

---

## Skills

| Skill | Description |
|---|---|
| `hsd-triage` | Fetches an HSD ticket, classifies the bug, queries related past HSDs, recommends fix paths, and patches HSD fields. |
| `live-debug` | Iterative log analysis loop — reads available logs, forms hypotheses, requests new logs, confirms root cause, and generates a verified HTML debug report. |

---

## Install

Copy the `.copilot/skills/` directory into any repo where you want these skills available:

```sh
cp -r .copilot/skills/ /path/to/your/project/.copilot/skills/
```

Or clone BugScout directly and open it in the Copilot CLI — skills in `.copilot/skills/` are automatically discovered.

---

## Usage

### Quick start

1. Open a terminal in a repo that has the skills installed (or open BugScout itself).
2. Invoke the Copilot CLI.
3. Provide an HSD ticket number and (optionally) a path to log files:

```
New HSD for triage — 22022566949 and debug logs in /path/to/logs
```

The agent will:
- Fetch the HSD from the Co-Design HSD MCP
- Decode and analyze all log files
- Run iterative hypothesis refinement
- Generate a fully verified HTML debug report

---

## Repository Structure

```
BugScout/
│
├── .copilot/
│   └── skills/
│       ├── hsd-triage/
│       │   └── SKILL.md          # hsd-triage skill definition
│       └── live-debug/
│           └── SKILL.md          # live-debug skill definition
│
├── src/                          # Pipeline Python scripts
│   ├── live_debug_runner.py      # Main live-debug orchestrator
│   ├── parse_and_triage.py       # HSD parser & triage logic
│   ├── write_single_response.py  # Single-turn HSD writer
│   ├── write_batch_responses.py  # Batch HSD writer
│   ├── patch_fields.py           # HSD field patcher
│   └── _write_hsd.py             # HSD write helpers
│
├── templates/
│   ├── bugscout_report_template.html      # ★ CANONICAL template (v1.0) — use for all new reports
│   ├── live_debug_report_template.html    # Previous Jinja2-style template (reference)
│   ├── rca_report_template.html           # RCA-only report template
│   └── report_template.html               # Generic single-iteration report
│
├── schemas/
│   └── live_debug_input.schema.json       # JSON schema for live-debug runner inputs
│
├── docs/
│   └── log_taxonomy.md                    # Log file taxonomy and decoding notes
│
├── samples/
│   ├── QAT_LM_segfault_22022566949/
│   │   └── session_report.html            # Reference report — HSD 22022566949 (2026-06-01)
│   │                                      # Iter 1–4 · 90% confidence (Iter 4 root cause subsequently revised)
│   │                                      # First report using bugscout_report_template.html v1.0
│   └── QAT_LM_segfault_22022566949_r2/
│       └── session_report_r2.html         # 2nd Regression report — HSD 22022566949 (2026-06-09)
│                                          # Iter 5 · 85% confidence · Engineer correction applied
│                                          # vtd_interrupt_remap_msi invalidated; kernel regression identified
│                                          # Key finding: vfio-pci reset-done absent on kernel 6.18.8.4.9
│
└── README.md                              # This file
```

---

## Report Template

All new debug reports should use **`templates/bugscout_report_template.html`** (v1.0).

### Key features of the template
- Dark-mode crash evidence block with colour-coded log spans
- Hypothesis evolution timeline with animated confidence bars
- Collapsible per-iteration accordion (last iteration auto-expanded)
- Root cause card (confirmed vs. active/hypothesis mode)
- **Log Recommendations** section — placeholder for follow-up log collection commands
- Field corrections / triage notes card (amber)
- Dual accuracy checks: log-evidence cross-validation + architectural spec validation
- Related past HSDs table
- Responsive CSS with CSS custom properties for easy theming

### Placeholder convention
Every piece of instance-specific data uses `{{PLACEHOLDER_NAME}}` syntax.
Repeating blocks are wrapped in `<!-- BLOCK_START: X -->` / `<!-- BLOCK_END: X -->` comments.

See the top-of-file comment block in the template for the full placeholder quick reference.

---

## Accuracy Verification

Every report produced by the live-debug skill includes two automated verification passes:

| Check | What it validates |
|---|---|
| **Check #2 — Log Evidence** | Each key finding is cross-validated against the raw log files |
| **Check #3 — Arch Spec** | Claims are validated against architecture specs, kernel docs, and HSD database |

Reports are not considered complete until both checks pass (WARN is acceptable with explanation).

---

## Supported Log Formats

| Format | Decoder |
|---|---|
| RTF (`.rtf`) | `System.Windows.Forms.RichTextBox` COM object (PowerShell) |
| Plain text (`.log`, `.txt`) | Direct read |
| GZIP compressed (`.log.gz`) | `zcat` / PowerShell Expand-Archive |
| Structured JSON | Native Python json parser |

See `docs/log_taxonomy.md` for the full taxonomy.

---

## Contributing

1. Fork `intel-sandbox/BugScout`
2. Add new skill definitions to `.copilot/skills/<skill-name>/SKILL.md`
3. Add source scripts to `src/`
4. Add a sample report to `samples/` to verify the template renders correctly
5. Open a pull request

---

## License

Intel Internal — see your org's standard open-source policy before sharing externally.

---

*BugScout was seeded from [intel-sandbox/project-c3](https://github.com/intel-sandbox/project-c3) · hsd-triage module · First report: HSD 22022566949 (QAT Live Migration Segfault, DMR, 2026-06-01)*
