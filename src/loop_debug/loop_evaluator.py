"""
loop_evaluator.py — Evaluator Role (Adversarial Checker)
═══════════════════════════════════════════════════════════════════════════════
Principle II: The model becomes sycophantic the moment it grades itself.
Principle III: The contract is what gets graded.

The Evaluator:
  - Is told "the current hypothesis is likely WRONG — prove it"
  - Reads evidence against the contract (not against gut feeling)
  - Scores discrimination power per evidence item
  - Returns CONTINUE / STOP / RESTART verdict
  - Never recommends logs or proposes hypotheses
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from .loop_config import EvaluatorVerdict, LoopConfig

logger = logging.getLogger(__name__)

# ─── System Prompt for Evaluator Role ─────────────────────────────────────────

EVALUATOR_SYSTEM_PROMPT = """\
You are the EVALUATOR in a loop-engineered debug system. Your stance is ADVERSARIAL.

The current top hypothesis is likely WRONG. Your job is to find the flaw in the
reasoning, check if the evidence actually discriminates between hypotheses, and
decide whether to continue, stop, or restart.

You will receive:
- The debug contract (what confirms/disconfirms each hypothesis)
- All evidence collected so far
- The current hypothesis list with confidence scores
- The iteration count

EVALUATION CRITERIA:
1. DISCRIMINATION: Does this evidence appear in BOTH pass and fail scenarios?
   If yes → it does NOT discriminate → score = 0
   If it narrows from N hypotheses to fewer → it DOES discriminate → score > 0

2. CONTRACT ALIGNMENT: Does the evidence match what the contract said would confirm/disconfirm?
   If confirming evidence matches contract criteria → increase confidence
   If disconfirming evidence found → decrease confidence

3. PROGRESS: Are we making forward progress or going in circles?
   If last 2-3 iterations haven't changed confidence by >0.1 → stuck

Your output MUST be a JSON object with:
{
  "verdict": "continue" | "stop" | "restart",
  "reasoning": "why this verdict",
  "updated_hypotheses": [
    {"id": "H1", "statement": "...", "confidence": 0.X, "evidence_for": [...], "evidence_against": [...]}
  ],
  "discrimination_scores": [
    {"iteration": N, "category": "...", "score": 0.X, "reason": "..."}
  ],
  "progress_assessment": "improving | stalled | regressing",
  "contract_gaps": ["any evidence criteria from contract that CANNOT be evaluated with available log categories"]
}

VERDICT RULES:
- STOP: Top hypothesis confidence >= {confidence_threshold} AND at least one disconfirming check passed
- RESTART: Stalled for {stuck_threshold} iterations (no hypothesis above 0.5) OR all hypotheses equally likely
- CONTINUE: Otherwise — suggest which contract criterion to target next

CRITICAL: You are NOT allowed to propose new hypotheses or recommend logs.
You only GRADE what exists against the CONTRACT.
"""


# ─── Main Evaluator Functions ─────────────────────────────────────────────────


def build_evaluator_prompt(
    contract_text: str,
    evidence_text: str,
    hypotheses: list[dict[str, Any]],
    iteration: int,
    config: LoopConfig,
) -> str:
    """
    Build the prompt for the evaluator GENI call.

    Args:
        contract_text:  Contents of contract.md
        evidence_text:  Contents of evidence.md (all collected evidence)
        hypotheses:     Current hypothesis list [{id, statement, confidence, ...}]
        iteration:      Current iteration number
        config:         Loop config (for thresholds)
    """
    hyp_section = "## Current Hypotheses\n\n"
    for h in hypotheses:
        hyp_section += (
            f"- **{h.get('id', '?')}** (conf={h.get('confidence', 0.0):.2f}): "
            f"{h.get('statement', '?')}\n"
        )

    return (
        f"## Debug Contract\n\n{contract_text}\n\n"
        f"## Evidence Collected (iterations 1-{iteration})\n\n{evidence_text}\n\n"
        f"{hyp_section}\n\n"
        f"## Meta\n\n"
        f"- Iteration: {iteration} of {config.max_iterations}\n"
        f"- Confidence threshold for STOP: {config.confidence_threshold}\n"
        f"- Stuck threshold for RESTART: {config.stuck_threshold} iterations\n"
    )


def get_evaluator_system_prompt(config: LoopConfig) -> str:
    """Return the evaluator system prompt with config values interpolated."""
    return EVALUATOR_SYSTEM_PROMPT.format(
        confidence_threshold=config.confidence_threshold,
        stuck_threshold=config.stuck_threshold,
    )


def parse_evaluator_response(response_text: str) -> dict[str, Any]:
    """
    Parse the evaluator's JSON response.

    Returns:
        dict with verdict, reasoning, updated_hypotheses, discrimination_scores, etc.
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
            raise ValueError(f"Could not parse evaluator response:\n{text[:500]}")

    # Normalize verdict
    verdict_str = parsed.get("verdict", "continue").lower().strip()
    try:
        verdict = EvaluatorVerdict(verdict_str)
    except ValueError:
        verdict = EvaluatorVerdict.CONTINUE

    return {
        "verdict": verdict,
        "reasoning": parsed.get("reasoning", ""),
        "updated_hypotheses": parsed.get("updated_hypotheses", []),
        "discrimination_scores": parsed.get("discrimination_scores", []),
        "progress_assessment": parsed.get("progress_assessment", ""),
        "contract_gaps": parsed.get("contract_gaps", []),
    }


def should_pause(
    verdict: EvaluatorVerdict,
    iteration: int,
    config: LoopConfig,
) -> bool:
    """
    Determine if the loop should pause for human input based on autonomy mode.

    Returns True if the loop should stop and wait for human confirmation.
    """
    from .loop_config import AutonomyMode

    # Always pause on RESTART (contract might be wrong — needs human)
    if verdict == EvaluatorVerdict.RESTART:
        return True

    # Always pause on STOP (present final findings)
    if verdict == EvaluatorVerdict.STOP:
        return True

    # Mode-specific pause logic for CONTINUE
    if config.autonomy_mode == AutonomyMode.SUPERVISED:
        return True  # pause every iteration

    if config.autonomy_mode == AutonomyMode.SEMI_AUTONOMOUS:
        # Pause every N iterations
        return iteration % config.semi_autonomous_batch == 0

    # AUTONOMOUS: never pause on CONTINUE
    return False


def update_hypotheses_md(
    hypotheses: list[dict[str, Any]],
    output_path: "Path",
) -> None:
    """Rewrite hypotheses.md with evaluator-updated confidence scores."""
    from pathlib import Path as _Path

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
        ]
        ev_for = h.get("evidence_for", [])
        if ev_for:
            lines.append(f"- **Supporting evidence**: {'; '.join(ev_for)}")
        ev_against = h.get("evidence_against", [])
        if ev_against:
            lines.append(f"- **Contradicting evidence**: {'; '.join(ev_against)}")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Updated %s", output_path)
