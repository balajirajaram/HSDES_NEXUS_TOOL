"""Handbook retrieval helper for crashdump-oriented BugScout flows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .debug_handbook import DebugHandbookLoader, DEFAULT_HANDBOOK_ROOT
except ImportError:
    from debug_handbook import DebugHandbookLoader, DEFAULT_HANDBOOK_ROOT  # type: ignore[no-redef]


class HandbookRAG:
    """Retrieve relevant handbook sections for a crashdump summary or triage record."""

    def __init__(self, handbook_root: str | Path):
        self.loader = DebugHandbookLoader(handbook_root)

    @classmethod
    def from_default_root(cls) -> "HandbookRAG":
        """Return a HandbookRAG instance backed by BugScout's bundled handbook."""
        return cls(DEFAULT_HANDBOOK_ROOT)

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        matches = self.loader.find_best_matches(query, top_k=top_k)
        return [
            {
                "rank": idx + 1,
                "title": match["title"],
                "source_file": match["source_file"],
                "score": match["score"],
                "content_preview": match["content_preview"],
            }
            for idx, match in enumerate(matches)
        ]

    def triage_retrieve(self, parsed: dict[str, Any], top_k: int = 4) -> list[dict[str, Any]]:
        """Retrieve handbook sections relevant to a parsed HSD triage record.

        Builds the query from component, accelerator type, failure modes, and
        a short snippet of the initial symptom.
        """
        component = parsed.get("component", "")
        failure_modes = parsed.get("failure_modes", [])
        accelerator = parsed.get("accelerator_type", "")
        symptom = parsed.get("initial_symptom", "")[:200]
        query = " ".join(filter(None, [component, accelerator, " ".join(failure_modes), symptom]))
        return self.retrieve(query, top_k=top_k)
