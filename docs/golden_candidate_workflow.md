# Candidate Golden Case Workflow

NEXUS must not automatically promote HSDs into the production corpus. The candidate pipeline is intentionally separate from `golden_cases/`.

## Discovery Pools

Use the existing HSDES master queries:

- GNR: `16026853717`
- SRF: `16027811005`
- Additional pool: `16022833305`
- Additional pool: `14012297882`
- CWF presightings: `16027523187`
- Additional supplied pool: `16027357901`

Export the query results and run:

```powershell
.\.venv\Scripts\python.exe tools\build_golden_candidates.py `
  --input hsdes_candidates.json `
  --output golden_candidates.csv
```

The script creates only `golden_candidates.csv`. It never writes to `golden_cases/`.

It also creates three review queues under `golden_review/`:

- `rejected.csv` — open/rejected/non-terminal or otherwise disqualified records.
- `manual_review.csv` — candidates missing evidence or requiring expert review.
- `prequalified.csv` — deterministic score/tier candidates that still require explicit approval.

The bounded human-review outputs are also generated:

- `review_required.csv` — top 10 GNR, top 10 SRF, top 5 DMR, and top 5 COR.
- `candidate_summary.html` — compact approval cards for that bounded pool.

These quotas are a review reduction policy, not a qualification decision. A
candidate remains `PENDING` until a human approval decision is recorded.

## Candidate Tiers

- `REJECT`: open, rejected, duplicate, blocked, or non-terminal status.
- `BRONZE`: terminal candidate without documented root cause.
- `SILVER`: documented RCA, but evidence is only a human comment or lacks independent validation.
- `GOLD`: terminal case with documented RCA; reviewer must confirm RCA evidence.
- `PLATINUM`: reproduction/fix-validation signal; reviewer must confirm the evidence.

A `Root Cause Comment Only` candidate can never be treated as Gold or Platinum automatically.

## Explicit Promotion

Promotion is a separate, fail-closed command. The decision file must contain
`hsd_id`, `decision=APPROVE`, `validation_level`, `validated_by`, and
`validation_source`. Only Level 3/4, prequalified, owner-labeled candidates
can be written under `golden_cases/`:

```powershell
.\.venv\Scripts\python.exe tools\promote_golden_cases.py `
  --decisions golden_review/decisions.csv `
  --candidates golden_candidates.csv
```

Unapproved, ambiguous, contradictory, comment-only, or unknown-owner records
fail closed and are not written.

## Blind Isolation Comparison

Collect four local NEXUS result exports per approved case:

- A: comments disabled, KB disabled
- B: comments enabled, KB disabled
- C: comments disabled, KB enabled
- D: comments enabled, KB enabled

Compare machine fields with:

```powershell
.\.venv\Scripts\python.exe tools\blind_compare_cases.py `
  golden_staging\<platform>\<hsd_id>\blind_runs.json
```

The comparison fails if owner, reporting IP, bank, socket, MCACOD, MSCOD,
confidence, or verdict changes across runs.

## Required Human Review

For every approved case, verify:

- closed/non-rejected status;
- no duplicate or transferred-only disposition;
- logs and attachments are present;
- root cause is independently supported;
- owner/reporting IP/originating IP/bank/socket/MCACOD/MSCOD are explicit or intentionally unknown;
- validator and validation source are named;
- Level 3 reproduced or Level 4 fix validated evidence exists.

Set `human_approval` to `APPROVED` only after review. Then manually create the normalized JSON under `golden_cases/GNR`, `CWF`, `DMR`, or `COR`. Do not use the candidate CSV itself as benchmark input.
