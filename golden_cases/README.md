# NEXUS Golden Corpus

Ground-truth, engineer-validated HSDs used to score NEXUS production metrics and
prevent regressions as RCA logic evolves. A broad HSDES saved query is a
candidate pool, never validation evidence. Each case is one JSON file placed
under the folder for its validated platform/domain:

```
golden_cases/
  GNR/    CWF/    DMR/    COR/
```

## Case schema (`_schema.json`)

```json
{
  "hsd_id": "16031704251",
  "platform": "GNR",
  "validation_level": "LEVEL_3_REPRODUCED",
  "expected_owner": "DCU",
  "expected_first_error": "",
  "expected_verdict": "WORKING HYPOTHESIS",
  "min_confidence": 0,
  "evidence": {
    "source": "HSD attachment and validated RCA",
    "validated_by": "named engineer",
    "validation_source": "specific reproduction or fix evidence",
    "fix_validated": false
  },
  "notes": "DCU load-poison consumption; source upstream unproven"
}
```

- **Production eligibility** — only `LEVEL_3_REPRODUCED` and
  `LEVEL_4_FIX_VALIDATED` cases with `evidence.validated_by` and
  `evidence.validation_source` count toward production qualification. Open,
  rejected, duplicate, transferred-only, workaround-only, product-change-only,
  or unknown-RCA cases must not be promoted.
- **expected_owner** — the owning IP the validation engineer concluded (required).
- **expected_first_error** — first-error source unit, if one was captured (optional).
- **expected_verdict** — CONFIRMED / LIKELY / WORKING HYPOTHESIS (optional).
- **min_confidence** — floor the tool's confidence should meet (optional, 0 = skip).
- **notes** — free text (optional).

The expanded schema also supports expected reporting/originating IP, bank,
socket, MCACOD, MSCOD, root cause, disposition, fix, validator, validation
date, and evidence source. Missing expectations are reported as `n/a`, not
silently counted as passes.

## Discovery provenance

The supplied saved-query pools were:

- `16026853717` (GNR candidate pool)
- `16027811005` (SRF candidate pool)
- `16022833305` (duplicate link/query)
- `14012297882` (additional broad candidate pool)

These pools include open, rejected, presighting, transferred, workaround, and
product-change records. Every candidate must be read with comments/history and
evidence before acceptance. If provenance is unknown, reject the candidate.

## Run the benchmark

```powershell
python -m tools.rca_benchmark                 # all cases, fetch attachments
python -m tools.rca_benchmark --no-attachments --dir golden_cases/CHA
```

## Metrics (targets)

| Metric | Target |
|--------|--------|
| First-error accuracy | > 90% |
| Owning-IP accuracy | > 80–85% |
| Confidence calibration | no systematic overconfidence |
| Contradiction detection | < 5% misses |
| False-attribution rate | < 10% |

Run the strict loader to count only production-qualified cases:

```powershell
.\.venv\Scripts\python.exe -c "from tools.rca_benchmark import _load_cases; from pathlib import Path; print(len(_load_cases(Path('golden_cases'))))"
```

The current two fixtures are safety/regression fixtures and do not constitute
30 production-qualified cases until their Level 3/4 provenance is recorded.
