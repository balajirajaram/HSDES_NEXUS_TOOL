# Automatic NEXUS Self-Check

The periodic checker is `tools/nexus_auto_check.py` with PowerShell wrapper `tools/run_nexus_check.ps1`.

Run manually:

```powershell
.\tools\run_nexus_check.ps1 -Strict
```

The checker validates:

- `/api/health`
- `/api/me`
- `/api/products`
- `/api/kb`
- Required-field validation for `/api/analyze`
- Required-field validation for `/api/autohsd/triage`
- Required-field validation for `/api/hsd/update`
- Required-field validation for `/api/chat`
- Python compilation of the checker
- Full regression suite
- Presence of the release checklist, candidate pipeline, AutoHSD profile generator, and enterprise design

It does not execute SUT commands, run live HSD analysis, write HSDES, promote Golden Cases, or modify the repository.

## Periodic Scheduling

Use Windows Task Scheduler to run:

```text
powershell.exe -ExecutionPolicy Bypass -File <repo>\tools\run_nexus_check.ps1 -Strict
```

Recommended frequency: daily or after dependency/code updates. Store the output in the Task Scheduler history or redirect it to an approved audit-log location.
