"""
loop_generator.py — Generator Role (Log Selection & Collection)
═══════════════════════════════════════════════════════════════════════════════
Principle II: The generator writes everything and is forbidden from grading.

The Generator:
  - Reads the contract to decide which log category has highest discrimination value
  - Picks the hypothesis with most uncertainty that can be resolved cheaply
  - Selects specific commands from the log taxonomy
  - Collects output via the execution adapter
  - Writes raw findings to evidence.md
  - Never grades, never proposes hypotheses, never decides to stop
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .loop_config import LoopConfig

logger = logging.getLogger(__name__)

# ─── System Prompt for Generator Role ─────────────────────────────────────────

GENERATOR_SYSTEM_PROMPT = """\
You are the GENERATOR in a loop-engineered debug system. Your job is to select
and collect the MOST DISCRIMINATING log for the current state of the investigation.

You will receive:
- The debug contract (what confirms/disconfirms each hypothesis)
- Evidence already collected
- Current hypothesis confidence scores
- The log taxonomy (available categories + commands)
- Logs already collected (to avoid duplication)

Your decision process:
1. Find the hypothesis with most uncertainty (confidence closest to 0.5)
2. Look at the contract for that hypothesis — what evidence would move confidence?
3. Pick the log category from the taxonomy that provides that evidence
4. Select SPECIFIC commands (not all commands in the category)
5. Explain WHY this log will help discriminate

Your output MUST be a JSON object with:
{
  "target_hypothesis": "H1",
  "rationale": "why this hypothesis and this log will discriminate",
  "category": "register_dump",
  "commands": ["specific command 1", "specific command 2"],
  "expected_discriminating_pattern": "what to look for in the output that would confirm/disconfirm",
  "fallback_category": "optional — if primary yields nothing useful"
}

CRITICAL RULES:
- NEVER pick a category already collected (check the 'already_collected' list)
- NEVER pick all categories — pick ONE per iteration (surgical, not shotgun)
- Prefer categories that distinguish BETWEEN hypotheses (not just confirm one)
- If the contract says "register X at value Y confirms H1 but disconfirms H2" — that's ideal
- You are FORBIDDEN from grading evidence or changing confidence scores
"""


# ─── Main Generator Functions ─────────────────────────────────────────────────


def build_generator_prompt(
    contract_text: str,
    evidence_text: str,
    hypotheses: list[dict[str, Any]],
    log_taxonomy: str,
    already_collected: list[str],
    iteration: int,
) -> str:
    """
    Build the prompt for the generator GENI call.

    Args:
        contract_text:      Contents of contract.md
        evidence_text:      Contents of evidence.md
        hypotheses:         Current hypothesis list
        log_taxonomy:       Full log taxonomy markdown
        already_collected:  List of category names already collected
        iteration:          Current iteration number
    """
    hyp_section = "## Current Hypothesis Confidence\n\n"
    for h in hypotheses:
        hyp_section += (
            f"- **{h.get('id', '?')}** (conf={h.get('confidence', 0.0):.2f}): "
            f"{h.get('statement', '?')}\n"
        )

    collected_section = "## Already Collected (DO NOT re-collect)\n\n"
    if already_collected:
        collected_section += ", ".join(f"`{c}`" for c in already_collected)
    else:
        collected_section += "None yet — this is the first collection."

    return (
        f"## Debug Contract\n\n{contract_text}\n\n"
        f"## Evidence So Far\n\n{evidence_text or '(none yet)'}\n\n"
        f"{hyp_section}\n\n"
        f"{collected_section}\n\n"
        f"## Log Taxonomy\n\n{log_taxonomy}\n\n"
        f"## Iteration: {iteration}\n"
    )


def parse_generator_response(response_text: str) -> dict[str, Any]:
    """
    Parse the generator's JSON response.

    Returns:
        dict with target_hypothesis, rationale, category, commands, etc.
    """
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
        else:
            raise ValueError(f"Could not parse generator response:\n{text[:500]}")

    return {
        "target_hypothesis": parsed.get("target_hypothesis", ""),
        "rationale": parsed.get("rationale", ""),
        "category": parsed.get("category", ""),
        "commands": parsed.get("commands", []),
        "expected_discriminating_pattern": parsed.get("expected_discriminating_pattern", ""),
        "fallback_category": parsed.get("fallback_category", ""),
    }


def append_evidence_md(
    evidence_path: Path,
    iteration: int,
    category: str,
    target_hypothesis: str,
    raw_output: str,
    expected_pattern: str,
) -> None:
    """
    Append new evidence to evidence.md after log collection.

    Writes the raw findings with context about what we were looking for.
    Does NOT interpret or grade — that's the evaluator's job.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Truncate raw output for the markdown file (keep full in .log files)
    display_output = raw_output[:2000]
    if len(raw_output) > 2000:
        display_output += f"\n... [{len(raw_output) - 2000} more chars in log file]"

    entry = (
        f"## Iteration {iteration} — `{category}` (targeting {target_hypothesis})\n"
        f"\n"
        f"*Collected: {ts}*\n"
        f"\n"
        f"**Looking for**: {expected_pattern}\n"
        f"\n"
        f"**Raw output**:\n"
        f"```\n{display_output}\n```\n"
        f"\n"
        f"---\n\n"
    )

    if evidence_path.exists():
        with evidence_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    else:
        evidence_path.write_text(
            f"# Evidence Collected\n\n{entry}", encoding="utf-8"
        )

    logger.info("Appended evidence for iteration %d (%s)", iteration, category)
