# NEXUS Production Readiness Checklist

Canonical release gate for HSDES NEXUS. When asked to run the NEXUS release checklist, audit the current implementation against this file and report, for every item:

- Status: `NOT_STARTED`, `PARTIAL`, `COMPLETE`, or `FAILED_VALIDATION`
- Source file and function
- Test name or executable validation
- Incomplete items that are production blockers only

Do not treat feature presence as validation. A control is `COMPLETE` only when its behavior is covered by a focused test or an auditable validation artifact.

## Status Legend

- `NOT_STARTED`: no implementation or validation
- `PARTIAL`: implementation or coverage exists, but the stated contract is incomplete
- `COMPLETE`: implementation and focused validation satisfy the item
- `FAILED_VALIDATION`: validation was run and failed

## Phase 1 - Evidence Integrity

### 1.1 Evidence Separation

- [ ] Ticket facts separated
- [ ] Machine evidence separated
- [ ] Human claims separated
- [ ] Historical knowledge separated
- [ ] No merged full-text RCA path

Validation: run the same HSD with comments disabled and enabled. Machine RCA must have identical ownership, confidence, and verdict.

### 1.2 Machine-Only RCA Path

- [ ] RCA runs with comments disabled
- [ ] RCA runs with KB disabled
- [ ] RCA runs with only logs
- [ ] Root cause is generated from machine evidence only

## Phase 2 - Comment Isolation

### 2.1 Human Claim Model

- [ ] Comments stored as claims
- [ ] Author preserved
- [ ] Timestamp preserved
- [ ] Validation status stored
- [ ] Confidence contribution is zero

### 2.2 Comment Cannot Influence RCA

- [ ] Comment cannot increase confidence
- [ ] Comment cannot change ownership
- [ ] Comment cannot change verdict
- [ ] Comment cannot produce `CONFIRMED ROOT CAUSE`
- [ ] Comment cannot pass the post gate

Validation: when a comment claims UPI but machine evidence indicates PCIe, machine RCA remains PCIe and the human claim is marked contradicted or unvalidated.

## Phase 3 - MCA Correctness

### 3.1 Fatality Consistency

- [ ] Single MCA classifier exists
- [ ] `UC=1` and `PCC=1` is always fatal
- [ ] `UC=1` and `PCC=1` is never corrected
- [ ] All report sections agree

Validation input: `0xBA00000C4A000402`. Expected everywhere: `UNCORRECTED_FATAL`.

### 3.2 Multi-Bank Analysis

- [ ] Bank 4 preserved
- [ ] Bank 6 preserved
- [ ] All MCA banks analyzed
- [ ] Primary versus secondary is justified
- [ ] No silent bank discard

Validation: a Bank 4 plus Bank 6 fixture produces two MCA entries.

### 3.3 Socket Consistency

- [ ] Socket provenance model exists
- [ ] Socket conflicts detected
- [ ] No Socket 0 defaulting
- [ ] Commands use the proven socket

Validation: a Socket 1 ticket must not generate Socket 0 commands.

## Phase 4 - Ownership Engine

### 4.1 Reporting Versus Originating IP

- [ ] Reporting IP tracked
- [ ] Victim IP tracked
- [ ] Source IP tracked
- [ ] Ownership ambiguity detected

### 4.2 First Error Handling

- [ ] First IERR extracted
- [ ] First MCERR extracted
- [ ] First error influences ownership
- [ ] Conflicts reported

Validation: PUNIT first IERR plus CCF MCA produces an ownership conflict and never CCF `CONFIRMED ROOT CAUSE`.

## Phase 5 - Noise Filtering

### 5.1 Register Noise

- [ ] Zero-value registers ignored
- [ ] Headings ignored
- [ ] Register descriptions ignored
- [ ] Configuration messages ignored

Validation: `Poisoned TLP = 0` is not reported as a failure.

### 5.2 Informational Noise

- [ ] WHEA disabled ignored
- [ ] Kernel panic prevention ignored
- [ ] KTI initialization ignored
- [ ] PCIe headings ignored

## Phase 6 - Decoder Quality

### 6.1 Ambiguity Detection

- [ ] Conflicting decoders detected
- [ ] Ambiguous MSCOD supported
- [ ] Ambiguity lowers confidence
- [ ] Ambiguity blocks confirmed RCA

Validation: competing `TOR_TIMEOUT`, `ADDR_PARITY_ERROR`, and `SAD_NON_CORRUPTING_ERR_OTHER` interpretations produce `AMBIGUOUS_DECODER`, not a single asserted cause.

### 6.2 Knowledge Applicability

- [ ] Platform-aware
- [ ] Bank-aware
- [ ] MCACOD-aware
- [ ] MSCOD-aware

Validation: MCACOD `0x0402` does not receive unrelated `0x0800` guidance.

## Phase 7 - Timeline Engine

### 7.1 Event Classification

- [ ] Runtime event
- [ ] Snapshot
- [ ] Post-failure capture
- [ ] Informational event
- [ ] Configuration event

### 7.2 Ordering

- [ ] Timestamps drive order
- [ ] Snapshots are not treated as runtime events
- [ ] Crashdump is not treated as a timeline event
- [ ] Unknown ordering is reported

## Phase 8 - Confidence Engine

### 8.1 Confidence Rules

- [ ] Machine-only confidence
- [ ] Comments contribute zero
- [ ] KB contributes zero proof
- [ ] Confidence ceilings implemented

### 8.2 Confidence Ceilings

- [ ] Unresolved ownership maximum 60
- [ ] Unresolved source/victim maximum 65
- [ ] Decoder ambiguity maximum 65
- [ ] No first error maximum 60
- [ ] No attachments maximum 20

Validation: an active conflict never produces 95% confidence.

## Phase 9 - Verdict State Machine

- [ ] `INSUFFICIENT_EVIDENCE`
- [ ] `WORKING HYPOTHESIS`
- [ ] `LIKELY ROOT CAUSE`
- [ ] `CONFIRMED ROOT CAUSE`

Validation: comment-only evidence never produces `CONFIRMED ROOT CAUSE`.

## Phase 10 - Auto-Post Gate

- [ ] Contradiction blocks posting
- [ ] Ambiguity blocks posting
- [ ] Ownership conflict blocks posting
- [ ] Comment-derived RCA blocks posting
- [ ] Working hypothesis blocks posting

Validation: an unresolved conflict produces draft-only output.

## Phase 11 - KB Safety

### 11.1 Validation States

- [ ] `OBSERVATION_ONLY`
- [ ] `UNVALIDATED_HYPOTHESIS`
- [ ] `MACHINE_SUPPORTED`
- [ ] `VALIDATED_ROOT_CAUSE`
- [ ] `FIX_VALIDATED`
- [ ] `CURATED_GOLDEN_CASE`

### 11.2 Safe Recall

- [ ] Unvalidated entries cannot boost confidence
- [ ] Observations cannot become RCA
- [ ] Comments cannot become KB truth

Validation: comment-only RCA is `UNVALIDATED_HYPOTHESIS` and is ineligible for root-cause recall.

## Phase 12 - Report Quality

### Executive Summary

- [ ] Reporting IP
- [ ] Source IP
- [ ] Human claim
- [ ] Claim validation
- [ ] Confidence
- [ ] Missing evidence

### Duplicate Elimination

- [ ] Only one RCA section
- [ ] No repeated hypotheses
- [ ] No repeated ownership analysis

## Phase 13 - Regression Suite

### Core Tests

- [ ] Comment-only RCA
- [ ] Comment contradiction
- [ ] Comment support
- [ ] No comments
- [ ] KB contamination
- [ ] Ownership conflict
- [ ] Socket conflict
- [ ] Decoder ambiguity
- [ ] UC/PCC fatality
- [ ] Zero-value noise
- [ ] No attachments

### Golden Cases

- [ ] CHA
- [ ] UPI
- [ ] PCIe
- [ ] CXL
- [ ] IMC
- [ ] Memory
- [ ] BIOS
- [ ] False-positive MCA
- [ ] Minimum 30 validated cases

Golden cases must preferably be closed, root-cause validated, and fix validated. Each case should record expected owner, reporting IP, first error, bank, socket, MCACOD, MSCOD, verdict, disposition, fix, validation level, validator, validation date, and evidence source.

## Phase 14 - Production Validation

### Benchmark Thresholds

- [ ] Owning-IP accuracy greater than 85%
- [ ] Ownership precision greater than 85%
- [ ] Ownership recall greater than 80%
- [ ] First-error accuracy greater than 90%
- [ ] Socket accuracy greater than 95%
- [ ] False attribution less than 10%
- [ ] Contradiction misses less than 5%
- [ ] False confirmed RCA equals 0

## Final Production Gate

Release only when all of the following are true:

- [ ] All safety tests pass
- [ ] All regression tests pass
- [ ] At least 30 validated golden cases exist
- [ ] Ownership accuracy exceeds 85%
- [ ] False confirmed RCA is zero
- [ ] Comment isolation is validated
- [ ] KB safety is validated
- [ ] Decoder ambiguity is handled
- [ ] Auto-post gate is validated

## Audit Output Contract

When this checklist is run, report:

1. Every checklist item with status, source file, function, and test or validation command.
2. Production blockers only in the incomplete-items section.
3. Exact counts and measured metrics, not estimates.
4. Any unavailable HSDES or fixture data as an explicit validation gap.
5. No future enhancements unless they are required by a checklist item.
