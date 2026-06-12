"""Build a lightweight handbook knowledge base from markdown debug handbooks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from .debug_handbook import DebugHandbookLoader, DEFAULT_HANDBOOK_ROOT
except ImportError:
    from debug_handbook import DebugHandbookLoader, DEFAULT_HANDBOOK_ROOT  # type: ignore[no-redef]


class HandbookKBBuilder:
    """Mine handbook markdown files into a simple cause/evidence knowledge base."""

    def __init__(self, handbook_root: str | Path):
        self.handbook_root = Path(handbook_root)
        self.loader = DebugHandbookLoader(handbook_root)

    def build(self, output_path: str | Path) -> dict[str, Any]:
        entries = []
        for section in self.loader.load_sections():
            causes = self._extract_causes(section.content)
            entries.append({
                "source_file": section.source_file,
                "title": section.title,
                "keywords": self._keywords(section.title + " " + section.content),
                "causes": causes,
            })

        kb = {
            "handbook_root": str(self.handbook_root),
            "section_count": len(entries),
            "entries": entries,
        }
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")
        return kb

    def _extract_causes(self, content: str) -> list[str]:
        causes = []
        patterns = [
            r"(?:root cause|caused by|due to|triggered by)[:\s]+([^\.\n]+)",
            r"(?:failure mode|failure mechanism)[:\s]+([^\.\n]+)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, content, flags=re.IGNORECASE):
                cause = match.group(1).strip()
                if 5 < len(cause) < 200:
                    causes.append(cause)
        return list(dict.fromkeys(causes))

    @classmethod
    def build_default(cls, output_path: str | Path | None = None) -> dict[str, Any]:
        """Build the KB from BugScout's bundled handbook and write to docs/handbooks/."""
        instance = cls(DEFAULT_HANDBOOK_ROOT)
        if output_path is None:
            output_path = DEFAULT_HANDBOOK_ROOT / "acd_handbook_kb.json"
        return instance.build(output_path)

    def _keywords(self, text: str) -> list[str]:
        words = re.findall(r"\b[A-Za-z][A-Za-z0-9_/-]{3,}\b", text.lower())
        stop = {"this", "that", "with", "from", "into", "have", "will", "should", "could", "would"}
        filtered = [w for w in words if w not in stop]
        counts: dict[str, int] = {}
        for word in filtered:
            counts[word] = counts.get(word, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:20]]
