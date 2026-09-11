# NEXUS Management Summary

Generated: 2026-09-10

## Executive Status

**Current status: NOT APPROVED for production RCA or autonomous write-back.**

NEXUS has a functioning deterministic RCA, evidence-safety, historical-mining, AutoHSD recommendation, and qualification framework. Production qualification remains gated by validated corpus data and source provenance.

## Current Capability

- Offline deterministic HSD triage and RCA report generation.
- MCA fatality classification with UC/PCC safety handling.
- Multi-bank and socket provenance tracking.
- First-error versus reporting-owner conflict detection.
- Decoder ambiguity detection and post-gate blocking.
- Comment and KB evidence isolation.
- KB validation states and safe recall controls.
- Source provenance inventory and strict audit tooling.
- Candidate Golden Case scoring and approval-gated promotion.
- RCA knowledge graph and historical consensus mining.
- Reference Corpus ranking and qualification-only benchmarking.
- AutoHSD evidence-collection recommendations.
- Non-destructive API self-check and 56-test regression suite.

## Future Capability

Planning or qualification work still pending:

- 30 human-approved Level 3/Level 4 Golden Cases.
- Validated RCA owner labels separate from HSD article owners.
- Complete platform normalization, including DMR and COR coverage.
- Authoritative provenance for nine decoder/knowledge resources.
- Benchmark accuracy measurements from qualified cases.
- Shared VM deployment with role-based access, audit trail, and shared KB.
- Measured production telemetry for time saved and engineer-hour savings.
- Controlled AutoHSD re-analysis loop after approved evidence collection.
- Production HSDES write-back and enterprise operations approval.

## Engineer Time Saved

Current measured time-saved telemetry: **n/a**.

The repository does not yet contain production measurements for baseline RCA time, assisted RCA time, number of engineer interventions, or completed HSD throughput. These values must be collected before claiming time savings.

Recommended telemetry fields:

| Measure | Current value |
|---|---:|
| Baseline median RCA minutes | n/a |
| NEXUS-assisted median RCA minutes | n/a |
| AutoHSD recommendation turnaround | n/a |
| HSDs analyzed | 60 candidate records in current sample |
| Engineer hours saved | n/a |
| Human review minutes per candidate | n/a |

## NEXUS Workflow

```text
HSDES HSD
  -> Ticket and machine-evidence extraction
  -> MCA/BIOS/POST/IERR decoding
  -> Evidence separation
  -> Ownership and contradiction analysis
  -> Confidence and verdict generation
  -> KB/reference retrieval with provenance
  -> Draft RCA report
  -> Auto-post gate
  -> Human-controlled HSDES write-back
```

The write-back path remains gated. Contradictions, ambiguity, weak verdicts, and unproven ownership remain draft-only.

## AutoHSD Workflow

```text
HSD symptom/title
  -> Failure-domain classification
  -> Missing-evidence audit
  -> PythonSV recommendation generation
  -> StatusScope recommendation generation
  -> MCA/PCIe/UPI/memory collection recommendations
  -> Engineer-approved collection
  -> Re-analysis with new evidence
  -> Confidence/verdict comparison
```

AutoHSD currently generates recommendations only. It does not execute commands or automatically modify the target system.

## Reference Corpus Statistics

Current exploratory Reference Corpus:

| Statistic | Value |
|---|---:|
| Reference cases | 50 |
| Knowledge graph nodes | 88 |
| Knowledge graph edges | 421 |
| Discovered validation signals | 44 |
| Consensus candidates | 88 |
| Historical mining candidates | 88 |
| Strict Golden Cases | 0/30 |
| Gold recommendations | 0 |
| Platinum recommendations | 0 |
| Reference benchmark owner accuracy | 0.0%, not interpretable |
| Reference RCA similarity | n/a |
| Reference evidence coverage | 0.0% |

The Reference Corpus is exploratory only. Its owner field currently reflects HSD article ownership rather than normalized RCA ownership, so it must not be presented as a production accuracy benchmark.

## Release Gates Remaining

1. Resolve unknown source provenance for nine resources.
2. Normalize unknown platform records.
3. Obtain and approve 30 Level 3/4 cases.
4. Re-run blind comments/KB isolation on approved cases.
5. Run the production benchmark and verify thresholds.
6. Capture real engineer-time telemetry.
7. Complete shared deployment/security review before rollout.

## Management Decision

NEXUS is ready for internal engineering evaluation, draft RCA review, historical mining, and recommendation-only AutoHSD demonstrations. It is not yet ready for broad production RCA, autonomous posting, or production qualification claims.
