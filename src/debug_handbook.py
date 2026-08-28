"""Debug handbook loader and lightweight retrieval helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).parent
# Default handbook bundle shipped with BugScout (docs/handbooks/ at repo root)
DEFAULT_HANDBOOK_ROOT = _MODULE_DIR.parent / "docs" / "handbooks"


@dataclass
class HandbookSection:
    title: str
    content: str
    source_file: str


class DebugHandbookLoader:
    """Load markdown debug handbooks from a platform-specific directory."""

    def __init__(self, handbook_root: str | Path):
        self.handbook_root = Path(handbook_root)

    def discover_files(self) -> list[Path]:
        if not self.handbook_root.exists():
            return []
        candidates = []
        for pattern in ("*_debug_steps.md", "*_Analysis_*.md", "*.md"):
            candidates.extend(self.handbook_root.rglob(pattern))
        unique = []
        seen = set()
        for path in candidates:
            if path.name.endswith("_Index.md"):
                continue
            if path not in seen:
                seen.add(path)
                unique.append(path)
        return sorted(unique)

    def load_sections(self) -> list[HandbookSection]:
        sections: list[HandbookSection] = []
        for path in self.discover_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            chunks = self._split_markdown(text)
            for title, content in chunks:
                if len(content.strip()) < 40:
                    continue
                sections.append(HandbookSection(title=title, content=content, source_file=path.name))
        return sections

    def find_best_matches(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        tokens = [t for t in re.findall(r"[A-Za-z0-9_./-]{3,}", query.lower()) if t]
        matches = []
        for section in self.load_sections():
            content_lower = section.content.lower()
            title_lower = section.title.lower()
            score = 0
            for token in tokens:
                if token in title_lower:
                    score += 5
                if token in content_lower:
                    score += 1
            if score:
                matches.append({
                    "score": score,
                    "title": section.title,
                    "source_file": section.source_file,
                    "content_preview": section.content[:600],
                })
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:top_k]

    def _split_markdown(self, text: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        current_title = "Introduction"
        current_lines: list[str] = []
        for line in text.splitlines():
            match = re.match(r"^(#+)\s+(.+)$", line)
            if match:
                if current_lines:
                    sections.append((current_title, "\n".join(current_lines).strip()))
                    current_lines = []
                current_title = match.group(2).strip()
            else:
                current_lines.append(line)
        if current_lines:
            sections.append((current_title, "\n".join(current_lines).strip()))
        return sections
