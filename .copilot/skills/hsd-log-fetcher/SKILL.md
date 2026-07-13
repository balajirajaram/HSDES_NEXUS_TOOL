---
name: hsd-log-fetcher
description: |
  Downloads all file attachments from an HSD ticket into HSD_Logs_Details/<hsd_id>/ using the
  HSDES REST API (Kerberos auth). Invoked directly by the user OR transparently by hsd-triage
  and live-debug when local logs are missing.
  Use when asked to "fetch logs for HSD", "download HSD attachments", "get logs from HSD <id>",
  or as a pre-step when HSD_Logs_Details/<hsd_id>/ is empty.
---

# HSD Log Fetcher

## Trigger

Say any of: "fetch logs for HSD <id>", "download attachments from HSD <id>",
"get logs from HSD <id>", or when called internally by hsd-triage / live-debug.

## What This Skill Does

1. Calls `GET /rest/article/<id>/children?child_subject=attachment` to list all attachments.
2. Downloads every attachment binary via `GET /rest/binary/<attachment_id>`.
3. Saves files to `HSD_Logs_Details/HSD_<id>/` (relative to BugScout root).
4. Uses `Content-Disposition` header to preserve original filenames.
5. Skips files already present unless `--no-skip` is passed.
6. Prints a download summary (downloaded / skipped / errors).

---

## AUTONOMOUS EXECUTION INSTRUCTIONS

### Step 1 — Run the fetcher

```bash
cd "C:\Users\smeenak1\OneDrive - Intel Corporation\Documents\GitHub\BugScout\src"
python hsd_log_fetcher.py <hsd_id>
```

**With a custom output directory:**
```bash
python hsd_log_fetcher.py <hsd_id> --output-dir "C:\path\to\output"
```

**Force re-download of existing files:**
```bash
python hsd_log_fetcher.py <hsd_id> --no-skip
```

**Machine-readable output (for scripting):**
```bash
python hsd_log_fetcher.py <hsd_id> --json
```

### Step 2 — Interpret the summary

After the run, report to the user:
- How many files were downloaded and their names
- How many were skipped (already present)
- Any errors (e.g., permission failures, missing attachment IDs)
- The full output path

If **no attachments were found** on the ticket, inform the user that logs must be
collected manually (e.g., via live-debug SSH) and are not present as HSD attachments.

If **errors occurred** (e.g., Kerberos auth failure), advise:
```
Kerberos auth failed. Ensure you are on the Intel network or VPN and have a valid ticket:
  klist          (verify existing ticket)
  kinit <idsid>  (refresh if expired)
```

---

## When Called Internally (by hsd-triage or live-debug)

When used as a transparent pre-step, the skill:
1. Checks whether `HSD_Logs_Details/HSD_<id>/` already contains files.
2. If the directory is empty or does not exist, runs the fetcher automatically.
3. Passes the resulting directory path as `--initial-logs` or as the local log
   source for the calling skill.
4. Does NOT block the workflow if no attachments exist — the calling skill proceeds
   with whatever is available and notes the gap.

**Integration check (Python snippet used internally):**
```python
from hsd_log_fetcher import fetch_hsd_logs
result = fetch_hsd_logs(hsd_id=<id>)
# result["output_dir"]  → pass to calling skill
# result["downloaded"]  → list of filenames available
# result["errors"]      → surface to user if non-empty
```

---

## Failure Modes & Fallbacks

| Failure | Behaviour |
|---|---|
| Kerberos auth error | Print auth instructions; do not block the calling workflow |
| No attachments on HSD | Report "no HSD attachments"; calling skill continues |
| Attachment download 403 | Skip the file; add to errors list; download others |
| Disk write failure | Add to errors list; continue with remaining files |

---

## Notes

- **Auth**: Kerberos only (requires Intel network / VPN). No password prompts.
- **SSL**: Automatically picks up Intel internal CA bundle from the corp share if available; falls back to `certifi` otherwise.
- **Filename safety**: Path traversal characters in `Content-Disposition` are stripped before writing.
- **Duplicates**: If a file already exists and `--no-skip` is set, the attachment ID is appended to avoid silent overwrites.
