# NEXUS Source Audit

Audit date: 2026-09-09

The machine-readable inventory is [app/knowledge/source_inventory.json](../app/knowledge/source_inventory.json). Run `python tools/verify_decoders.py` to audit coverage, duplicate JSON keys, and unknown trust. Use `--strict` when unknown trust must fail the release check.

## Trust Policy

| Tier | Trust | May prove RCA? | Examples |
|---|---:|---|---|
| Tier 0 | AUTHORITATIVE / 100 | Yes | EDS-R, architecture/RAS/register specifications, official ownership tables |
| Tier 1 | OFFICIAL_INTERNAL / 90 | Support only | Debug wiki, PythonSV and StatusScope documentation |
| Tier 2 | VALIDATED_HISTORICAL / 80 | Support only | Fix-validated HSDs and curated golden cases |
| Tier 3 | ENGINEER_KNOWLEDGE / 50 | Hypothesis only | Comments, email, Teams, manual notes |
| Tier 4 | LLM_INFERENCE / 20 | Suggestion only | Generated inference and similarity suggestions |
| Unknown | UNKNOWN / 0 | No promotion | Any resource without an auditable owner and source |

## Current Inventory Findings

- The inventory explicitly records owner, origin, source document, version, validation date, trust, and validation method.
- `mca_codes_database.json`, EWL, RC-Fatal, MCHECK, generic bank mappings, and `debug_kb.json` remain `UNKNOWN` until their authoritative origins are verified.
- The supplemental MCA table and CWF/GNR/SRF bank maps have recorded Intel source references, but their entries still require ongoing source/version review.
- Unknown decoder provenance is surfaced in the RCA as `SOURCE_PROVENANCE_UNKNOWN`; it caps confidence at 60%, prevents ownership proof, and prevents `LIKELY` or `CONFIRMED ROOT CAUSE`.
- Human comments and historical KB entries remain evidence/support, never authoritative proof.

## Required Review Record

For every decoder or knowledge resource, resolve `UNKNOWN` values before broad production rollout:

1. Named owner.
2. Origin and authoritative source document.
3. Source version or revision.
4. Last validation date.
5. Validation method and reviewer.
6. Duplicate-key and conflict scan result.
7. Platform/IP applicability.

A decoder entry with no source provenance must not be promoted into an authoritative RCA statement.
