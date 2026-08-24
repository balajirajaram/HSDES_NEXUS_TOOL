---
mode: agent
description: Auto HSD analysis with default attachment extraction and AXON correlation
---

# Auto HSD Analyser (Default Team Mode)

This is the default mode for ticket analysis.

## Objective

Produce an evidence-backed A-H report for an HSD ticket by combining:
- HSD ticket fields and comments
- HSD attachments (metadata + content extraction when available)
- AXON trend/failure correlation

Do not provide a comment-only analysis unless all evidence channels fail.

## Required Inputs

- HSD ticket id (required)
- Optional platform/program hints for AXON filtering

## Mandatory Workflow

1. Start with HSD config discovery
- Call `mcp_hsdes_config` once per session.

2. Read core ticket context
- Call `mcp_hsdes_read` for:
  - `include: ["summary", "description", "comments", "history", "links"]`

3. Enumerate attachments (always)
- Call `mcp_hsdes_attachments` with `response_format: "detailed"`.
- Build an attachment table:
  - attachment id
  - filename
  - size
  - type/extension
  - extraction status

4. Attempt attachment extraction
- If environment supports raw attachment retrieval, use `mcp_hsdes_raw` to fetch content.
- Parse and capture the most relevant snippets/signatures.
- If retrieval is not supported, mark status as `metadata-only`.
- Never claim extraction happened unless content was actually retrieved.

5. Run AXON analysis (always attempt)
- Acquire AXON token via acquire-tokens skill.
- Call `mcp_genivalidatio_AxonTool` with exact required JSON payload fields:
  - `exact_question`
  - `history_enhanced_query`
  - `AxonLink`
  - `prior_tool_errors`
- First call uses empty AxonLink/prior errors.
- Follow-up calls must pass latest Axon link and prior AXON errors.

6. Generate A-H report
- A: Ticket Summary
- B: Prior KB Recall
- C: Similar HSD
- D: Root Cause Hypotheses
- E: Exact Debug Steps and Commands (source-tagged)
- F: Command Block
- G: Learning Summary
- H: Verdict + Confidence + Next Action

7. Add default evidence sections
- Attachment Evidence Summary
- AXON Correlation Summary
- Evidence Confidence Matrix

## Confidence Rules

Use explicit verdict wording based on evidence:
- `comment-indicated cause`: comments suggest cause, no independent evidence
- `log-corroborated cause`: attachment logs corroborate the cause
- `axon-corroborated trend`: AXON confirms recurrence pattern/trend

Confidence guide:
- Low: ticket text/comments only
- Medium: comments + partial attachment or AXON support
- High: attachment logs and AXON both support same hypothesis

## Reporting Guardrails

- Distinguish observed facts from hypotheses.
- Include open gaps and next concrete actions.
- If attachment extraction or AXON call fails, report failure mode explicitly and continue with best-effort analysis.

## Final Line

Always end with a one-line triage stance:
- `Stance: <root-cause maturity> | Confidence: <Low/Medium/High> | Next owner action: <exact action>`
