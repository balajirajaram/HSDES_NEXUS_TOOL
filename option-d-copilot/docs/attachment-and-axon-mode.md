# Attachment and AXON Evidence Mode

Note: This behavior is now the default in `auto-hsd-analyser.prompt.md`.

This mode upgrades analysis from comment-only interpretation to evidence-backed triage.

## Why Use It

Use this mode when you need:
- stronger confidence on root-cause statements
- proof from attached logs/dumps
- fleet-level trend validation through AXON

## How To Run (VS Code Copilot)

1. Open the prompt file:
  - `auto-hsd-analyser.prompt.md` (default)
  - or `auto-hsd-analyser-logs.prompt.md` (explicit evidence-focused variant)
2. Trigger the prompt mode.
3. Provide HSD id and optional context.
4. Ensure the run includes all of these:
   - HSD read (summary/description/comments/history/links)
   - Attachment listing and classification
   - Attachment extraction attempt (or explicit metadata-only fallback)
   - AXON query and correlation summary

## Expected Report Enhancements

In addition to A-H sections, report should include:
- Attachment Evidence Summary
- AXON Correlation Summary
- Evidence Confidence Matrix

## Interpreting Confidence

- Low:
  - conclusions based mostly on ticket text/comments
- Medium:
  - comments plus partial attachment evidence or AXON trend support
- High:
  - attachment log signatures and AXON trends both support the same hypothesis

## Known Limitations

- Attachment extraction depends on environment support for download/read path.
- If download path is unavailable, report should explicitly state metadata-only attachment review.
- AXON access requires valid token and entitlement.

## Team Review Checklist

- Confirm report states what was actually parsed vs inferred.
- Confirm AXON section includes latest returned Axon link.
- Confirm verdict wording matches evidence confidence.
