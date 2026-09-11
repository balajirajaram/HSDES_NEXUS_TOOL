# Reference Corpus Mode

Reference Corpus mode is an exploratory benchmark for historical HSDs when a strict Level 3/Level 4 Golden Corpus is not yet available.

Run:

```powershell
.\.venv\Scripts\python.exe tools\build_reference_corpus.py `
  --mining historical_golden_candidates.csv `
  --consensus consensus_candidates.csv `
  --evidence discovered_validation_evidence.csv `
  --output reference_corpus.csv `
  --top 50
```

Rules:

- `reference_corpus.csv` is `REFERENCE_ONLY`.
- Reference cases do not count toward the 30-case production Golden Corpus.
- Reference confidence is a ranking signal, not validation proof.
- Blockers and platform uncertainty remain visible in `Limitations`.
- Reference cases must not be promoted automatically.
- Strict production qualification still requires approved Level 3/Level 4 Golden Cases.
