"""
loop_config.py — Configuration for the Loop-Engineered Debug System
═══════════════════════════════════════════════════════════════════════════════
Central settings: autonomy modes, thresholds, role prompts, and state paths.
All tunable parameters live here — no hardcoding in role modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class AutonomyMode(Enum):
    """How much human oversight the loop requires."""
    SUPERVISED = "supervised"           # Pause after every evaluator verdict
    SEMI_AUTONOMOUS = "semi_autonomous" # Run up to N iterations before pausing
    AUTONOMOUS = "autonomous"           # Run until STOP/RESTART/contract dispute


class EvaluatorVerdict(Enum):
    """Evaluator's decision after reviewing evidence."""
    CONTINUE = "continue"   # Evidence insufficient, generator should collect more
    STOP = "stop"           # Confidence >= threshold, root cause confirmed
    RESTART = "restart"     # Stuck — discard hypothesis tree, planner re-plans


@dataclass
class LoopConfig:
    """All tunable parameters for the loop debug system."""

    # ─── Session identity ──────────────────────────────────────────────────
    hsd_id: str = ""
    session_id: str = ""

    # ─── Autonomy ──────────────────────────────────────────────────────────
    autonomy_mode: AutonomyMode = AutonomyMode.SUPERVISED
    semi_autonomous_batch: int = 3   # iterations before pause in semi-autonomous
    max_iterations: int = 10         # hard stop
    restart_limit: int = 2           # max times planner can re-plan

    # ─── Confidence thresholds ─────────────────────────────────────────────
    confidence_threshold: float = 0.85   # evaluator triggers STOP above this
    stuck_threshold: int = 3             # consecutive low-progress → RESTART

    # ─── Execution ─────────────────────────────────────────────────────────
    execution_mode: str = "manual"   # manual | local | ssh | auto
    server: str = ""
    ssh_user: str = ""

    # ─── Paths ─────────────────────────────────────────────────────────────
    output_dir: Path = field(default_factory=lambda: Path("output"))
    log_taxonomy_path: Path = field(default_factory=lambda: Path("log_taxonomy.md"))

    # ─── Role model settings (for heterogeneous model splits if needed) ────
    planner_model: str = ""     # empty = use default GENI model
    generator_model: str = ""
    evaluator_model: str = ""

    # ─── Discrimination scoring ────────────────────────────────────────────
    min_discrimination_score: float = 0.3  # below this, evidence is "not useful"

    @property
    def session_dir(self) -> Path:
        """Directory for this session's state files."""
        return self.output_dir / f"live_debug_{self.session_id}"

    @property
    def db_path(self) -> Path:
        return self.session_dir / "session.db"

    @property
    def hypotheses_path(self) -> Path:
        return self.session_dir / "hypotheses.md"

    @property
    def contract_path(self) -> Path:
        return self.session_dir / "contract.md"

    @property
    def evidence_path(self) -> Path:
        return self.session_dir / "evidence.md"

    @property
    def progress_path(self) -> Path:
        return self.session_dir / "progress.md"

    @property
    def log_path(self) -> Path:
        return self.session_dir / "log.md"

    def ensure_dirs(self) -> None:
        """Create session directory if it doesn't exist."""
        self.session_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_session_init(cls, init_path: Path) -> "LoopConfig":
        """Load config from a session_init.json file (backward-compatible)."""
        import json
        data = json.loads(init_path.read_text(encoding="utf-8"))
        mode_str = data.get("autonomy_mode", "supervised")
        try:
            autonomy = AutonomyMode(mode_str)
        except ValueError:
            autonomy = AutonomyMode.SUPERVISED

        return cls(
            hsd_id=data.get("hsd_id", ""),
            session_id=data.get("session_id", ""),
            autonomy_mode=autonomy,
            max_iterations=data.get("max_iterations", 10),
            restart_limit=data.get("restart_limit", 2),
            confidence_threshold=data.get("confidence_threshold", 0.85),
            execution_mode=data.get("execution_mode", "manual"),
            server=data.get("server", ""),
            ssh_user=data.get("ssh_user", ""),
            output_dir=Path(data.get("output_dir", "output")),
            log_taxonomy_path=Path(data.get("log_taxonomy_path", "log_taxonomy.md")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to dict (for session_init.json)."""
        return {
            "hsd_id": self.hsd_id,
            "session_id": self.session_id,
            "autonomy_mode": self.autonomy_mode.value,
            "semi_autonomous_batch": self.semi_autonomous_batch,
            "max_iterations": self.max_iterations,
            "restart_limit": self.restart_limit,
            "confidence_threshold": self.confidence_threshold,
            "stuck_threshold": self.stuck_threshold,
            "execution_mode": self.execution_mode,
            "server": self.server,
            "ssh_user": self.ssh_user,
            "output_dir": str(self.output_dir),
            "log_taxonomy_path": str(self.log_taxonomy_path),
        }
