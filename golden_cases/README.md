# RCA Regression Corpus (golden cases)

Ground-truth, engineer-validated HSDs used to score NEXUS ownership accuracy and
prevent regressions as the RCA logic evolves. Each case is one JSON file placed
under the folder for its **validated owning IP**:

```
golden_cases/
  CHA/    UPI/    PCIe/    IMC/    BIOS/    CORE/
```

## Case schema (`_schema.json`)

```json
{
  "hsd_id": "16031704251",
  "platform": "GNR",
  "expected_owner": "DCU",
  "expected_first_error": "",
  "expected_verdict": "WORKING HYPOTHESIS",
  "min_confidence": 0,
  "notes": "DCU load-poison consumption; source upstream unproven"
}
```

- **expected_owner** — the owning IP the validation engineer concluded (required).
- **expected_first_error** — first-error source unit, if one was captured (optional).
- **expected_verdict** — CONFIRMED / LIKELY / WORKING HYPOTHESIS (optional).
- **min_confidence** — floor the tool's confidence should meet (optional, 0 = skip).
- **notes** — free text (optional).

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

Add the 20–30 validated HSDs here (one file each) before the MCACOD/MSCOD
knowledge-graph work, so the graph is founded on validated causality.
