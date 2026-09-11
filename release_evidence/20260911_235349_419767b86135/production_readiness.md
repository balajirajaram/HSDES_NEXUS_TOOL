# NEXUS Release Readiness

Status: NOT APPROVED

Git branch: nexus-tool-import
Commit: 419767b8613523f9c839dc4af8c6ecbf18784a2a
Dirty tree: True
Python: 3.14.3
Tests: 97 (exit 0)
Provenance: PASS
Reference cases: 50
Strict Golden cases: 47/30
AutoHSD integration: PASS
Benchmark gate policy: normalized_owner_accuracy_with_all_other_checks_strict
Cases passed (strict): 0/47
Cases passed (normalized): 0/47
First-error accuracy: 2.7%
First-error accuracy measures a different, harder question (earliest register to raise an error) than owner accuracy (which physical unit owns the failure) -- do not average these into one score.
Benchmark: FAIL (0/47)
HSD post-gate: evaluated by existing _post_gate in integration/test paths

## Blockers
- Golden Case benchmark failed
