---
name: axon-fetcher
description: |
  Downloads all content objects (crashdumps, serial logs, kernel logs, etc.) from an Axon
  failure record into Axon_Records/<record_id>/ using the Axon REST API (Azure AD Bearer token).
  Also supports searching Axon for records linked to an HSD ticket via --hsd-id.
  Use when asked to "fetch Axon record", "download Axon logs", "get Axon data for <id>",
  "find Axon records for HSD <id>", or as a pre-step when local Axon content is missing.
---

# Axon Record Fetcher

## What is Axon?

Axon (https://axon.intel.com) is Intel's failure-record storage service.  It stores
structured test failure records — crashdumps, serial logs, kernel crash logs, and other
debug artefacts — indexed by a string record ID.  Records may also carry metadata fields
such as `hsd_id`, `platform`, and `testcase` that link them back to HSD tickets.

## Trigger

Say any of:
- `"fetch Axon record <id>"`
- `"download Axon logs for <id>"`
- `"get Axon data for HSD <hsd_id>"`
- `"search Axon for HSD <hsd_id>"`
- When `hsd-triage` or `live-debug` needs supplementary data not in `HSD_Logs_Details/`

## What This Skill Does

1. (First time) Authenticates with Azure AD via MSAL device-code flow and exchanges the
   Azure token for an Axon API token (`GET /api/v2/token`).  Subsequent calls use the
   cached token (`~/.bugscout/axon_token_cache.bin`).
2. **Direct fetch**: calls `GET /api/v1/record/{id}` to get metadata, then
   `GET /api/v1/record/{id}/content` to list attached content types, then
   `GET /api/v1/record/{id}/content/{type}/object` to download each file.
3. **HSD-linked search**: executes a query (`POST /api/v1/query/execute`) filtering
   on `hsd_id` to find matching Axon records, then downloads all of them.
4. Saves files to `Axon_Records/<record_id>/` (relative to BugScout root).
5. Skips files already present unless `--no-skip` is passed.
6. Prints a download summary (downloaded / skipped / errors).

---

## Authentication Setup (first-time)

Axon uses Azure AD Bearer tokens.  Set the following environment variables before the
first run:

```
AXON_AAD_CLIENT_ID=<Axon AAD application ID>   # contact axon.support@intel.com
AXON_AAD_TENANT_ID=46c98d88-e344-4ed4-8496-4ed7712e255d  # Intel tenant (default)
AXON_AAD_SCOPE=api://axon.intel.com/.default   # default scope (override if needed)
```

On the first run the script will print a device-code URL.  Open it in a browser,
sign in with your Intel credentials, and the token will be cached automatically.

---

## AUTONOMOUS EXECUTION INSTRUCTIONS

### Fetch a specific Axon record

```bash
cd "C:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python axon_record_fetcher.py <record_id>
```

### Fetch only specific content types

```bash
python axon_record_fetcher.py <record_id> --content-types crashdump serial_log
```

### Find and download all Axon records linked to an HSD ticket

```bash
python axon_record_fetcher.py --hsd-id <hsd_id>
```

### Force re-download of existing files

```bash
python axon_record_fetcher.py <record_id> --no-skip
```

### Machine-readable output (for scripting)

```bash
python axon_record_fetcher.py <record_id> --json
```

### Custom output directory

```bash
python axon_record_fetcher.py <record_id> --output-dir "C:\path\to\output"
```

---

## Step 2 — Interpret the summary

After the run, report to the user:
- How many files were downloaded and their names
- The record metadata (platform, testcase, hsd_id if present)
- How many were skipped (already present)
- Any errors
- The full output path

If Axon records were found via `--hsd-id`, list the record IDs discovered before
reporting per-record download results.

---

## Programmatic Usage (import)

```python
from axon_record_fetcher import fetch_axon_record, fetch_axon_records_for_hsd

# Download a specific record
result = fetch_axon_record("axon-abc123")

# Find + download all records for an HSD ticket
results = fetch_axon_records_for_hsd(hsd_id=15012329795)
```

---

## Source Files

| File | Purpose |
|---|---|
| `src/axon_client.py` | `AxonClient` — auth, token exchange, all REST calls |
| `src/axon_record_fetcher.py` | Download orchestrator + CLI entry point |
| `.copilot/skills/axon-fetcher/SKILL.md` | This file |

## See Also

- `hsd-log-fetcher` — downloads HSD ticket attachments (complementary skill)
- `hsd-triage` — invokes both `hsd-log-fetcher` and `axon-fetcher` as pre-steps
- `live-debug` — uses locally cached logs for iterative debug sessions
