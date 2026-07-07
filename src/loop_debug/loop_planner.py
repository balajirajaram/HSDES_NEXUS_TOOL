"""
loop_planner.py — Planner Role (Contract Negotiation)
═══════════════════════════════════════════════════════════════════════════════
Principle II: Separate the roles.
Principle III: Negotiate the contract first.

The Planner:
  - Receives HSD context, initial symptoms, similar HSDs (RAG)
  - Proposes 3-5 hypotheses with initial confidence
  - Writes contract.md: what evidence confirms/disconfirms each hypothesis
  - Never touches log collection or evidence grading

The contract is what gets evaluated — not the code. This is the single
change that moves debug sessions from wandering to purposeful.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .loop_config import LoopConfig

logger = logging.getLogger(__name__)

# ─── System Prompt for Planner Role ───────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """\
You are the PLANNER in a loop-engineered debug system. Your job is to produce
a clear debug contract BEFORE any logs are collected.

You will receive:
- HSD symptom description and component information
- Initial logs (if any were collected before this session)
- Similar closed HSDs with their confirmed root causes (RAG context)
- The log taxonomy (available categories)

Your output MUST be a JSON object with:
1. "hypotheses" — array of 3-5 ranked hypotheses, each with:
   - "id": "H1", "H2", etc.
   - "statement": clear root cause statement
   - "confidence": initial confidence (0.0-1.0)
   - "reasoning": why you suspect this
2. "contract" — array matching each hypothesis, each with:
   - "hypothesis_id": "H1", etc.
   - "confirming_evidence": what specific log patterns/values WOULD confirm this
   - "disconfirming_evidence": what WOULD rule this out
   - "required_categories": which log taxonomy categories are needed (1-3)
   - "estimated_iterations": how many collection rounds needed (1-3)

CRITICAL RULES:
- Be SPECIFIC about confirming/disconfirming evidence (register values, error codes, patterns)
- Each hypothesis must be FALSIFIABLE — if you can't describe what would disprove it, drop it
- Prefer hypotheses that are distinguishable by different log categories
- Order hypotheses by prior probability (most likely first)
- DO NOT recommend collecting ALL categories — be surgical
"""

# ─── Main Planner Functions ───────────────────────────────────────────────────


def build_planner_prompt(
    hsd_context: dict[str, Any],
    initial_logs: list[dict[str, Any]],
    similar_hsds: list[dict[str, Any]],
    log_taxonomy: str,
) -> str:
    """
    Build the user-facing prompt for the planner GENI call.

    Args:
        hsd_context:   Parsed HSD record {hsd_id, title, component, symptom, ...}
        initial_logs:  Any logs already collected [{category, content_snippet}]
        similar_hsds:  RAG-retrieved similar closed HSDs [{hsd_id, root_cause, logs_used}]
        log_taxonomy:  Full log taxonomy markdown text
    """
    # Format HSD context
    hsd_section = (
        f"## HSD Under Debug\n"
        f"- **HSD ID**: {hsd_context.get('hsd_id', '?')}\n"
        f"- **Title**: {hsd_context.get('title', '?')}\n"
        f"- **Component**: {hsd_context.get('component', '?')}\n"
        f"- **Accelerator**: {hsd_context.get('accelerator_type', '?')}\n"
        f"- **Symptom**: {hsd_context.get('symptom', hsd_context.get('initial_symptom', '?'))}\n"
        f"- **Failure Mode**: {hsd_context.get('failure_mode', '?')}\n"
        f"- **Testcase Type**: {hsd_context.get('testcase_type', '?')}\n"
    )

    # Format initial logs
    if initial_logs:
        log_lines = []
        for log in initial_logs:
            cat = log.get("category", "unknown")
            snippet = log.get("content_snippet", "")[:300]
            log_lines.append(f"### {cat}\n```\n{snippet}\n```")
        initial_section = f"## Initial Logs Already Collected\n\n" + "\n\n".join(log_lines)
    else:
        initial_section = "## Initial Logs Already Collected\n\nNone — this is a fresh session."

    # Format similar HSDs (RAG context)
    if similar_hsds:
        rag_lines = []
        for h in similar_hsds[:5]:  # cap at 5
            rag_lines.append(
                f"- **{h.get('hsd_id', '?')}**: Root cause = {h.get('root_cause', '?')}. "
                f"Useful logs: {', '.join(h.get('logs_used', []))}"
            )
        rag_section = "## Similar Closed HSDs (for reference)\n\n" + "\n".join(rag_lines)
    else:
        rag_section = "## Similar Closed HSDs\n\nNone available."

    # Taxonomy section
    taxonomy_section = f"## Available Log Categories\n\n{log_taxonomy}"

    return "\n\n".join([hsd_section, initial_section, rag_section, taxonomy_section])


def parse_planner_response(response_text: str) -> dict[str, Any]:
    """
    Parse the planner's JSON response into structured hypotheses and contract.

    Returns:
        dict with keys "hypotheses" and "contract"
    """
    # Try to extract JSON from response (may be wrapped in markdown code blocks)
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Planner response not valid JSON, attempting recovery")
        # Attempt to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
        else:
            raise ValueError(f"Could not parse planner response as JSON:\n{text[:500]}")

    return {
        "hypotheses": parsed.get("hypotheses", []),
        "contract": parsed.get("contract", []),
    }


def write_hypotheses_md(hypotheses: list[dict], output_path: Path) -> None:
    """Write hypotheses.md — the current hypothesis set with confidence."""
    lines = [
        "# Hypotheses",
        "",
        f"*Last updated: {datetime.now().isoformat(timespec='seconds')}*",
        "",
    ]
    for h in hypotheses:
        conf = h.get("confidence", 0.0)
        bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
        lines += [
            f"## {h.get('id', '?')}: {h.get('statement', '?')}",
            f"",
            f"- **Confidence**: {conf:.2f} [{bar}]",
            f"- **Reasoning**: {h.get('reasoning', '—')}",
            f"",
        ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", output_path)


def write_contract_md(contract: list[dict], output_path: Path) -> None:
    """Write contract.md — per-hypothesis confirming/disconfirming evidence criteria."""
    lines = [
        "# Debug Contract",
        "",
        "Negotiated before log collection begins. The evaluator grades evidence against this.",
        "",
        f"*Established: {datetime.now().isoformat(timespec='seconds')}*",
        "",
    ]
    for c in contract:
        lines += [
            f"## {c.get('hypothesis_id', '?')}",
            f"",
            f"### Confirming Evidence (would prove this hypothesis)",
            f"{c.get('confirming_evidence', '—')}",
            f"",
            f"### Disconfirming Evidence (would rule this out)",
            f"{c.get('disconfirming_evidence', '—')}",
            f"",
            f"### Required Log Categories",
            f"{', '.join(c.get('required_categories', []))}",
            f"",
            f"### Estimated Iterations: {c.get('estimated_iterations', '?')}",
            f"",
            "---",
            "",
        ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", output_path)


def write_progress_md(config: LoopConfig, phase: str, iteration: int = 0,
                      notes: str = "") -> None:
    """Write/update progress.md — what's done, what's next, current state."""
    lines = [
        "# Progress",
        "",
        f"**Session**: {config.session_id}",
        f"**HSD**: {config.hsd_id}",
        f"**Phase**: {phase}",
        f"**Iteration**: {iteration}",
        f"**Autonomy**: {config.autonomy_mode.value}",
        f"**Last Updated**: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    if notes:
        lines += ["## Notes", "", notes, ""]

    config.progress_path.write_text("\n".join(lines), encoding="utf-8")


def append_log_md(config: LoopConfig, role: str, action: str, detail: str = "") -> None:
    """Append to log.md — audit trail of all role actions."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"## [{ts}] {role} | {action}\n"
    if detail:
        entry += f"\n{detail}\n"
    entry += "\n"

    # Append (create if missing)
    log_path = config.log_path
    if log_path.exists():
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    else:
        log_path.write_text(f"# Debug Loop Audit Log\n\n{entry}", encoding="utf-8")
