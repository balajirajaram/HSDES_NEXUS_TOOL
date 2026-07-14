"""
loop_orchestrator.py — Main Loop Controller
═══════════════════════════════════════════════════════════════════════════════
Principle I: gather → reason → act → verify → repeat.
Principle V: Let the loop restart.
Principle IV: Write to disk, not to context.

The Orchestrator:
  - Drives: planner → [generator → evaluator]* → report
  - Handles RESTART by re-invoking planner with failure context
  - Implements autonomy mode pauses
  - Persists all state to disk (crash-recoverable)
  - Integrates with existing live_debug_runner.py infrastructure
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from .loop_config import AutonomyMode, EvaluatorVerdict, LoopConfig
from .loop_planner import (
    append_log_md,
    build_planner_prompt,
    parse_planner_response,
    write_contract_md,
    write_hypotheses_md,
    write_progress_md,
)
from .loop_evaluator import (
    build_evaluator_prompt,
    get_evaluator_system_prompt,
    parse_evaluator_response,
    should_pause,
    update_hypotheses_md,
)
from .loop_generator import (
    append_evidence_md,
    build_generator_prompt,
    parse_generator_response,
)

logger = logging.getLogger(__name__)


# ─── MCP Call Protocol ─────────────────────────────────────────────────────────

class MCPCaller(Protocol):
    """Protocol for calling GENI DebugAssistantAgentTool (or mock for tests)."""

    def call(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt and return the response text."""
        ...


class ExecutionAdapter(Protocol):
    """Protocol matching the adapters in live_debug_runner.py."""

    def run(self, commands: list[str], context: str = "") -> str:
        ...


# ─── Loop State (in-memory, synced to disk) ────────────────────────────────────

class LoopState:
    """
    Mutable state for the current loop run.
    Persisted to disk after every mutation (Principle IV).
    """

    def __init__(self, config: LoopConfig):
        self.config = config
        self.hypotheses: list[dict[str, Any]] = []
        self.contract: list[dict[str, Any]] = []
        self.iteration: int = 0
        self.restart_count: int = 0
        self.collected_categories: list[str] = []
        self.verdict_history: list[EvaluatorVerdict] = []
        self.phase: str = "init"

    @property
    def evidence_text(self) -> str:
        """Read evidence.md from disk (source of truth)."""
        if self.config.evidence_path.exists():
            return self.config.evidence_path.read_text(encoding="utf-8")
        return ""

    @property
    def contract_text(self) -> str:
        """Read contract.md from disk."""
        if self.config.contract_path.exists():
            return self.config.contract_path.read_text(encoding="utf-8")
        return ""

    def top_hypothesis_confidence(self) -> float:
        """Return confidence of the highest-ranked hypothesis."""
        if not self.hypotheses:
            return 0.0
        return max(h.get("confidence", 0.0) for h in self.hypotheses)

    def save_checkpoint(self) -> None:
        """Persist current loop state to a JSON checkpoint file."""
        checkpoint = {
            "iteration": self.iteration,
            "restart_count": self.restart_count,
            "collected_categories": self.collected_categories,
            "hypotheses": self.hypotheses,
            "contract": self.contract,
            "phase": self.phase,
            "verdict_history": [v.value for v in self.verdict_history],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        cp_path = self.config.session_dir / "loop_checkpoint.json"
        cp_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, config: LoopConfig) -> "LoopState":
        """Recover state from disk after crash."""
        cp_path = config.session_dir / "loop_checkpoint.json"
        if not cp_path.exists():
            return cls(config)

        data = json.loads(cp_path.read_text(encoding="utf-8"))
        state = cls(config)
        state.iteration = data.get("iteration", 0)
        state.restart_count = data.get("restart_count", 0)
        state.collected_categories = data.get("collected_categories", [])
        state.hypotheses = data.get("hypotheses", [])
        state.contract = data.get("contract", [])
        state.phase = data.get("phase", "init")
        state.verdict_history = [
            EvaluatorVerdict(v) for v in data.get("verdict_history", [])
        ]
        logger.info(
            "Recovered from checkpoint: iteration=%d, phase=%s",
            state.iteration, state.phase,
        )
        return state


# ─── The Loop ──────────────────────────────────────────────────────────────────

class LoopOrchestrator:
    """
    Main controller: planner → [generator → evaluator]* → report

    Usage:
        config = LoopConfig(hsd_id="123", session_id="123_20260707_120000", ...)
        orch = LoopOrchestrator(config, mcp_caller=my_geni_caller, adapter=my_adapter)
        result = orch.run(hsd_context={...}, initial_logs=[...], similar_hsds=[...])
    """

    def __init__(
        self,
        config: LoopConfig,
        mcp_caller: MCPCaller,
        adapter: ExecutionAdapter,
        log_taxonomy: str = "",
        on_pause: Callable[[LoopState, EvaluatorVerdict], str] | None = None,
    ):
        """
        Args:
            config:       Loop configuration
            mcp_caller:   Object with .call(system_prompt, user_prompt) -> str
            adapter:      Execution adapter (Manual/Local/SSH/Auto)
            log_taxonomy: Full log taxonomy markdown text
            on_pause:     Callback when loop pauses for human input.
                          Receives (state, verdict), returns user input string.
                          If None, loop prints and reads from stdin.
        """
        self.config = config
        self.mcp = mcp_caller
        self.adapter = adapter
        self.log_taxonomy = log_taxonomy
        self.on_pause = on_pause or self._default_pause

    def run(
        self,
        hsd_context: dict[str, Any],
        initial_logs: list[dict[str, Any]] | None = None,
        similar_hsds: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Execute the full debug loop.

        Returns:
            dict with keys: root_cause, confidence, iterations_used, verdict_history
        """
        self.config.ensure_dirs()

        # ─── Recover or initialize state ──────────────────────────────────
        state = LoopState.load_checkpoint(self.config)

        if state.phase == "init":
            state = self._run_planner(state, hsd_context, initial_logs or [], similar_hsds or [])

        # ─── Inner loop: generate → evaluate ──────────────────────────────
        while state.iteration < self.config.max_iterations:
            state.iteration += 1
            state.phase = "generate"
            state.save_checkpoint()

            # GENERATOR: pick and collect log
            gen_result = self._run_generator(state)
            if gen_result is None:
                # Generator couldn't find anything useful to collect
                append_log_md(self.config, "ORCHESTRATOR", "generator_exhausted",
                              "No uncollected categories can discriminate further.")
                break

            # EVALUATOR: grade evidence against contract
            state.phase = "evaluate"
            state.save_checkpoint()
            eval_result = self._run_evaluator(state)
            verdict = eval_result["verdict"]
            state.verdict_history.append(verdict)

            # Update hypotheses from evaluator
            if eval_result.get("updated_hypotheses"):
                state.hypotheses = eval_result["updated_hypotheses"]
                update_hypotheses_md(state.hypotheses, self.config.hypotheses_path)

            write_progress_md(
                self.config,
                phase=f"evaluate (verdict={verdict.value})",
                iteration=state.iteration,
                notes=eval_result.get("reasoning", ""),
            )
            state.save_checkpoint()

            # ─── Handle verdict ───────────────────────────────────────────
            if verdict == EvaluatorVerdict.STOP:
                append_log_md(self.config, "EVALUATOR", "STOP",
                              f"Confidence threshold met. {eval_result.get('reasoning', '')}")
                state.phase = "done"
                state.save_checkpoint()
                break

            if verdict == EvaluatorVerdict.RESTART:
                if state.restart_count >= self.config.restart_limit:
                    append_log_md(self.config, "ORCHESTRATOR", "restart_limit_reached",
                                  f"Restart limit ({self.config.restart_limit}) exhausted.")
                    state.phase = "done_inconclusive"
                    state.save_checkpoint()
                    break
                # Pause for human (restart always requires confirmation)
                user_input = self._pause(state, verdict)
                if user_input.lower().strip() in ("stop", "quit", "exit"):
                    state.phase = "stopped_by_user"
                    state.save_checkpoint()
                    break
                # Re-plan with failure context
                state.restart_count += 1
                state = self._run_planner(
                    state, hsd_context, initial_logs or [], similar_hsds or [],
                    restart_reason=eval_result.get("reasoning", ""),
                )
                continue

            # CONTINUE — check if we should pause
            if should_pause(verdict, state.iteration, self.config):
                user_input = self._pause(state, verdict)
                if user_input.lower().strip() in ("stop", "quit", "exit"):
                    state.phase = "stopped_by_user"
                    state.save_checkpoint()
                    break

        # ─── Final result ─────────────────────────────────────────────────
        if state.phase not in ("done", "stopped_by_user", "done_inconclusive"):
            state.phase = "max_iterations_reached"
            state.save_checkpoint()

        return {
            "phase": state.phase,
            "root_cause": state.hypotheses[0].get("statement", "") if state.hypotheses else "",
            "confidence": state.top_hypothesis_confidence(),
            "iterations_used": state.iteration,
            "restart_count": state.restart_count,
            "verdict_history": [v.value for v in state.verdict_history],
            "collected_categories": state.collected_categories,
            "hypotheses": state.hypotheses,
        }

    # ─── Role Runners ─────────────────────────────────────────────────────────

    def _run_planner(
        self,
        state: LoopState,
        hsd_context: dict[str, Any],
        initial_logs: list[dict[str, Any]],
        similar_hsds: list[dict[str, Any]],
        restart_reason: str = "",
    ) -> LoopState:
        """Execute the planner role and write contract + hypotheses to disk."""
        from .loop_planner import PLANNER_SYSTEM_PROMPT

        state.phase = "planning"
        append_log_md(self.config, "PLANNER", "start",
                      f"Restart #{state.restart_count}" if restart_reason else "Initial planning")

        # Build prompt (include restart context if re-planning)
        user_prompt = build_planner_prompt(
            hsd_context, initial_logs, similar_hsds, self.log_taxonomy
        )
        if restart_reason:
            user_prompt += (
                f"\n\n## ⚠️ RESTART: Previous Hypotheses Failed\n\n"
                f"The evaluator determined the previous hypothesis set was unresolvable:\n"
                f"> {restart_reason}\n\n"
                f"Please propose a DIFFERENT hypothesis set. Avoid the same angles.\n"
                f"Evidence collected so far:\n\n{state.evidence_text}\n"
            )

        # Call GENI as planner
        response = self.mcp.call(PLANNER_SYSTEM_PROMPT, user_prompt)
        parsed = parse_planner_response(response)

        # Update state
        state.hypotheses = parsed["hypotheses"]
        state.contract = parsed["contract"]
        state.phase = "planned"

        # Write to disk (Principle IV)
        write_hypotheses_md(state.hypotheses, self.config.hypotheses_path)
        write_contract_md(state.contract, self.config.contract_path)
        write_progress_md(self.config, phase="planned", iteration=state.iteration,
                          notes=f"{len(state.hypotheses)} hypotheses, "
                                f"{len(state.contract)} contract entries")
        state.save_checkpoint()

        append_log_md(self.config, "PLANNER", "complete",
                      f"Produced {len(state.hypotheses)} hypotheses")
        return state

    def _run_generator(self, state: LoopState) -> dict[str, Any] | None:
        """Execute the generator role: select and collect one log category."""
        from .loop_generator import GENERATOR_SYSTEM_PROMPT

        append_log_md(self.config, "GENERATOR", f"iteration_{state.iteration}_start")

        user_prompt = build_generator_prompt(
            contract_text=state.contract_text,
            evidence_text=state.evidence_text,
            hypotheses=state.hypotheses,
            log_taxonomy=self.log_taxonomy,
            already_collected=state.collected_categories,
            iteration=state.iteration,
        )

        # Call GENI as generator
        response = self.mcp.call(GENERATOR_SYSTEM_PROMPT, user_prompt)
        gen_result = parse_generator_response(response)

        category = gen_result.get("category", "")
        commands = gen_result.get("commands", [])

        if not category or not commands:
            return None

        # Execute log collection via adapter
        context = f"Iteration {state.iteration}: collecting {category} for {gen_result.get('target_hypothesis', '?')}"
        raw_output = self.adapter.run(commands, context=context)

        # Record collection
        state.collected_categories.append(category)

        # Write evidence to disk
        append_evidence_md(
            evidence_path=self.config.evidence_path,
            iteration=state.iteration,
            category=category,
            target_hypothesis=gen_result.get("target_hypothesis", ""),
            raw_output=raw_output,
            expected_pattern=gen_result.get("expected_discriminating_pattern", ""),
        )

        # Also persist full log via existing infrastructure
        from live_debug_runner import ingest_log_output
        ingest_log_output(raw_output, category, self.config.session_dir)

        append_log_md(self.config, "GENERATOR", f"collected_{category}",
                      f"Target: {gen_result.get('target_hypothesis', '?')}, "
                      f"Commands: {len(commands)}")
        return gen_result

    def _run_evaluator(self, state: LoopState) -> dict[str, Any]:
        """Execute the evaluator role: grade evidence against contract."""
        system_prompt = get_evaluator_system_prompt(self.config)

        user_prompt = build_evaluator_prompt(
            contract_text=state.contract_text,
            evidence_text=state.evidence_text,
            hypotheses=state.hypotheses,
            iteration=state.iteration,
            config=self.config,
        )

        # Call GENI as evaluator
        response = self.mcp.call(system_prompt, user_prompt)
        eval_result = parse_evaluator_response(response)

        append_log_md(
            self.config, "EVALUATOR",
            f"verdict={eval_result['verdict'].value}",
            eval_result.get("reasoning", ""),
        )
        return eval_result

    # ─── Pause Handling ───────────────────────────────────────────────────────

    def _pause(self, state: LoopState, verdict: EvaluatorVerdict) -> str:
        """Pause the loop and get human input."""
        return self.on_pause(state, verdict)

    @staticmethod
    def _default_pause(state: LoopState, verdict: EvaluatorVerdict) -> str:
        """Default pause: print status and read from stdin."""
        print(f"\n{'═' * 60}")
        print(f"  LOOP PAUSED — Iteration {state.iteration}")
        print(f"  Verdict: {verdict.value}")
        print(f"  Top hypothesis: {state.hypotheses[0].get('statement', '?') if state.hypotheses else '?'}")
        print(f"  Confidence: {state.top_hypothesis_confidence():.2f}")
        print(f"{'═' * 60}")

        if verdict == EvaluatorVerdict.RESTART:
            print("  The evaluator recommends RESTARTING with fresh hypotheses.")
            print("  Type 'go' to restart, 'stop' to end session, or add context:")
        else:
            print("  Type 'go' to continue, 'stop' to end, or add context:")

        print()
        try:
            user_input = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            user_input = "stop"

        return user_input if user_input else "go"
