---
name: statusscope-parser
description: |
  Parses a StatusScope *-intel-svtools-report-v1.json report into a compact, AI-friendly
  record: priority-sorted HW/FW insights (with HSD links), platform/stepping/QDF/SKU metadata,
  tool versions, and decoded error/sideband/mca/known-sightings tables — stdlib only, no pandas.
  Resolves the report from a JSON file, a directory (e.g. HSD_Logs_Details/HSD_<id>/), a result
  zip, or an Axon record. Use when asked to "parse statusscope", "analyze svtools report",
  "read axon statusscope record", or when a *-svtools-report-v1.json is present in fetched logs.
---

# StatusScope Parser

## What is StatusScope?

StatusScope is Intel's PythonSV failure-time capture framework.  When a system-debug
capture runs, it produces a structured debug bundle whose canonical artefact is a single
JSON document, `*-intel-svtools-report-v1.json` (the HTML report is just a rendering of the
same object).  The report aggregates plugin/analyzer namespaces, each carrying tables,
markdown summaries, and — most importantly — **insights**: typed findings such as
`HW.CFG.ERR`, `HW.KNOWN_ISSUE`, and `SW.FW.ERR`, many linking to HSD articles.

## Trigger

Say any of:
- `"parse statusscope <path>"`
- `"analyze svtools report <path>"`
- `"read axon statusscope record <record_id>"`
- When `hsd-triage` or `live-debug` finds a `*-svtools-report-v1.json` in fetched logs

## What This Skill Does

1. Resolves the StatusScope report from one of four sources (JSON file, directory, zip, or
   Axon record).
2. Flattens the report's `sub_reports` into a namespace-keyed map.
3. Merges, normalizes, dedups and **priority-sorts insights** (HW issues before FW/SW).
4. Extracts metadata: platform, stepping, QDF, SKU, probe type, run command, run time, and
   the versions of triage-relevant tools.
5. Decodes pandas `orient=table` tables (schema.fields + data) using **stdlib only** — no
   pandas dependency.
6. Emits a **compact summary payload** (insights + key metadata + only the
   error/sideband/mca/known-sightings tables + HSD links) so the whole blob is never fed to
   a model.

> **DMR note:** On DMR the `mca` plugin is intentionally empty ("Crashlog collaterals not yet
> delivered for DMR") — the `error` analyzer namespace is the real error source.  The parser
> only surfaces table namespaces that are actually present in the run.

---

## AUTONOMOUS EXECUTION INSTRUCTIONS

### Parse a report JSON on disk (primary path)

```bash
cd "C:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python statusscope_ingest.py --json "<path>\<id>-intel-svtools-report-v1.json"
```

### Find + parse a report inside a directory (e.g. fetched HSD logs)

```bash
python statusscope_ingest.py --dir "HSD_Logs_Details\HSD_<hsd_id>"
```

### Parse a StatusScope result zip

```bash
python statusscope_ingest.py --zip "<path>\result.zip"
```

### Parse the svtools-report content from an Axon record

```bash
python statusscope_ingest.py --axon <record_id>
# optional: override the content-type name if auto-detection misses it
python statusscope_ingest.py --axon <record_id> --content-type <name>
```

### Human-readable summary instead of JSON

```bash
python statusscope_parser.py "<path>\<id>-intel-svtools-report-v1.json"
```

Add `--full` to `statusscope_ingest.py`/`statusscope_parser.py --json` to emit the full
record (all namespaces + decoded tables) instead of the compact summary.

---

## Interpreting the output

Report to the user:
- **Platform / stepping / QDF / SKU / probe** — the silicon + debug context
- **Insights**, in priority order — each with `type`, `ip_domain`, `message`, and HSD `url`
- **HSD links** — the unique set of referenced HSD articles (candidates for correlation)
- Any **error / sideband / mca** table rows present (real detected errors)
- **Known sightings** — issues matched with high confidence, with next-step guidance

Prioritize `HW.KNOWN_ISSUE` and `HW.CFG.ERR` insights: these are confirmed bugs or missing
workarounds and should anchor a first-pass hypothesis.

---

## Programmatic Usage (import)

```python
from statusscope_ingest import from_json, from_dir, from_zip, from_axon, bridge_to_crashdump

record = from_json("<id>-intel-svtools-report-v1.json")   # or from_dir/from_zip/from_axon
payload = record.to_summary_dict()                         # compact model-ready payload

# Bridge StatusScope error insights into the existing crashdump/handbook lane
bridge_to_crashdump(record)
```

`from_dir`, `from_zip`, and `from_axon` return `None` (non-blocking) when no StatusScope
report is present — callers should continue without failing.

---

## Source Files

| File | Purpose |
|---|---|
| `src/statusscope_parser.py` | `StatusScopeRecord` + report parsing, table decode, metadata/insight extraction |
| `src/statusscope_ingest.py` | Source resolver (json/dir/zip/axon) + crashdump bridge + CLI |
| `.copilot/skills/statusscope-parser/SKILL.md` | This file |

## See Also

- `axon-fetcher` — downloads Axon record content (source for `--axon`)
- `hsd-log-fetcher` — downloads HSD ticket attachments (source for `--dir`)
- `crash-parser` — the crashdump/handbook lane that `bridge_to_crashdump` feeds
- `hsd-triage` / `live-debug` — auto-invoke this skill when a StatusScope report is present
