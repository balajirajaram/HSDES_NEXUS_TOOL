"""Shared HSD ID parsing helpers — used by both single-HSD and batch-mode
endpoints in main.py so the normalization logic exists in exactly one place.
"""

from __future__ import annotations

import csv
import io
import re
from typing import List, Tuple


def normalize_hsd_id(value: str) -> str:
    """Accept a plain HSD number or an HSDES article URL."""
    text = str(value or "").strip()
    article_match = re.search(r"/article(?:-one)?/[^/]*?(\d{8,})", text, re.IGNORECASE)
    if article_match:
        return article_match.group(1)
    number_match = re.search(r"(?<!\d)(\d{8,})(?!\d)", text)
    return number_match.group(1) if number_match else text


def parse_hsd_id_list(raw_text: str) -> Tuple[List[str], int]:
    """Split a comma/whitespace/newline-separated blob of HSD IDs (or article
    URLs) into a de-duplicated, order-preserving list. Returns
    (unique_ids, duplicates_removed_count)."""
    tokens = [t for t in re.split(r"[,\s]+", (raw_text or "").strip()) if t]
    seen: set = set()
    unique: List[str] = []
    duplicates = 0
    for tok in tokens:
        norm = normalize_hsd_id(tok)
        if not norm:
            continue
        if norm in seen:
            duplicates += 1
            continue
        seen.add(norm)
        unique.append(norm)
    return unique, duplicates


def parse_hsd_ids_from_csv_text(csv_text: str) -> Tuple[List[str], int]:
    """Parse a CSV's `hsd_id` column (case-insensitive header) into a
    de-duplicated, order-preserving list. Falls back to treating every
    non-empty cell as an ID when no recognizable header row is found."""
    text = (csv_text or "").strip()
    if not text:
        return [], 0
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return [], 0
    header = [c.strip().lower() for c in rows[0]]
    values: List[str] = []
    if "hsd_id" in header:
        idx = header.index("hsd_id")
        for row in rows[1:]:
            if idx < len(row) and row[idx].strip():
                values.append(row[idx].strip())
    else:
        for row in rows:
            for cell in row:
                if cell.strip():
                    values.append(cell.strip())
    return parse_hsd_id_list(",".join(values))
