"""
loop_debug — Loop-Engineered Live Debug System
═══════════════════════════════════════════════════════════════════════════════
Applies Loop Engineering principles (Karpathy/Osmani) to HSD debug:
  - Role separation: Planner / Generator / Evaluator
  - Contract negotiation before log collection
  - Configurable autonomy (supervised → autonomous)
  - State on disk (survives crashes)
  - Adversarial evaluation (checker told hypothesis is wrong)
"""

from .loop_config import LoopConfig, AutonomyMode
from .loop_orchestrator import LoopOrchestrator

__all__ = ["LoopConfig", "AutonomyMode", "LoopOrchestrator"]
