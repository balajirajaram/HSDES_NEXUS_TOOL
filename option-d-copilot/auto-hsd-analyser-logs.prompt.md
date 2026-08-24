---
mode: agent
description: Auto HSD analysis with mandatory attachment and AXON evidence correlation
---

# Auto HSD Analyser (Attachment + AXON Mode)

Use this prompt when user asks for deeper evidence than comments/description.

## Inputs

- HSD ticket id (required)
- Optional product/program context for AXON query narrowing

## Required Behavior

You must not stop at comment-only analysis.
You must collect and use:
- HSD summary/description/comments
- HSD attachment inventory
- AXON correlation findings

## Execution Steps

1. Read HSD core content
- Use `mcp_hsdes_config` once at session start.
- Use `mcp_hsdes_read` with `include: ["summary", "description", "comments", "history", "links"]`.

2. Enumerate HSD attachments
- Use `mcp_hsdes_attachments` with `response_format: "detailed"`.
- Build an evidence table with filename, type, size, and attachment id.
- Classify artifacts into:
  - likely logs (`.log`, `.txt`, `.gz`, `.zip`, `.rpt`, `.trace`, `.csv`)
  - binaries/dumps (`.bin`, `.dmp`)
  - other documents

3. Attempt attachment content extraction
- If attachment download endpoint is available in environment, use `mcp_hsdes_raw` with the relevant path for attachment retrieval and capture text snippets.
- If direct download is unavailable, explicitly mark extraction status as "metadata-only" and continue with best-effort analysis.
- Never claim to have parsed an attachment unless content was actually retrieved.

4. Run AXON correlation
- Acquire token via acquire-tokens skill for `axon`.
- Call `mcp_genivalidatio_AxonTool` with exact JSON message format.
- First call payload:
  - `exact_question`: user question
  - `history_enhanced_query`: include HSD id, failure signature, component, stepping, and time window
  - `AxonLink`: ""
  - `prior_tool_errors`: ""
- For follow-up calls, propagate latest Axon link and prior errors per tool contract.

5. Build evidence-backed verdict
- Separate evidence sources clearly:
  - ticket text/comments
  - attachment-derived facts
  - AXON findings
- If attachment extraction was not possible, include an explicit limitation note.

6. Output contract (A-H)
- A: Ticket summary
- B: KB recall
- C: Similar HSD
- D: Hypotheses
- E: Exact debug steps with source-tagged evidence
- F: Command block
- G: Learning summary
- H: Verdict with confidence level and open risks

## Guardrails

- Do not overstate root cause confidence without attachment or AXON confirmation.
- Use wording:
  - "comment-indicated cause" when evidence is only comments
  - "log-corroborated cause" when attachment content supports it
  - "axon-corroborated trend" when AXON confirms recurrence patterns
- Always include data gaps and next concrete steps.

## Final report additions

Include these sections in generated report:
- Attachment Evidence Summary
- AXON Correlation Summary
- Evidence Confidence Matrix (Low/Medium/High)
