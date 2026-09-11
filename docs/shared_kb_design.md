# Shared KB Design

Planning artifact only.

## Data Classes

- RCA observations
- Machine evidence and decoded artifacts
- Human claims with author/time/provenance
- Validated historical references
- Golden Cases only after explicit approval

## Safety

- Every entry records source, trust, validation state, platform, and owner.
- Unvalidated observations cannot become root-cause truth.
- Reference Corpus entries remain separate from Golden Cases.
- Writes require role authorization and audit event.
- Recall may rank hypotheses but cannot independently prove RCA.
