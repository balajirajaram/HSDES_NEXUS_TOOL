"""Debug Knowledge Pack — gives the analyzer 'access' to BIOS code areas and debug
wiki pages, offline and shareable.

Two layers:
  1. Curated pack (knowledge/debug_kb.json): failure MECHANISM -> real Intel debug
     wiki links + BIOS/firmware code areas + concrete next steps. Grounded in
     BIOSBKM Debug CookBook, DebugEncyclopedia, and BIOS FAS/HAS spec content.
     Works with no network — ships with the tool.
  2. Optional live BIOS-source enrichment: if config.BIOS_REPO_PATH points to a
     local BIOS/IFWI checkout, we grep it for the EXACT code sites found in the
     logs (e.g. MultiSocketLib.c:1241) and include the surrounding source.

The matcher scores entries against the detected domains, suspected area, log
signatures, comment breadcrumbs, and ticket text, and returns the top hits.
"""

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

from .config import config

_PACK_PATH = os.path.join(os.path.dirname(__file__), "knowledge", "debug_kb.json")


@lru_cache(maxsize=1)
def _load_pack() -> List[Dict[str, Any]]:
    try:
        with open(_PACK_PATH, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("entries", [])
    except Exception:
        return []


def match_knowledge(blob: str, domains: Optional[List[str]] = None,
                    top_k: int = 3) -> List[Dict[str, Any]]:
    """Return the most relevant knowledge entries for this issue. `blob` should
    combine symptoms + suspected area + signatures + breadcrumbs + ticket text."""
    text = (blob or "").lower()
    dom = {d.lower() for d in (domains or [])}
    scored: List[tuple] = []
    for e in _load_pack():
        hits = [kw for kw in e.get("match", []) if kw.lower() in text]
        score = len(hits)
        if e.get("domain", "").lower() in dom:
            score += 1
        if score:
            scored.append((score, hits, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[Dict[str, Any]] = []
    for score, hits, e in scored[:top_k]:
        out.append({
            "id": e.get("id"),
            "title": e.get("title", ""),
            "summary": e.get("summary", ""),
            "wiki_links": e.get("wiki_links", []),
            "code_paths": e.get("code_paths", []),
            "debug_steps": e.get("debug_steps", []),
            "matched_terms": hits[:8],
        })
    return out


# ---- optional live BIOS-source enrichment ----
_CODE_SITE_RE = re.compile(r"\b([A-Za-z0-9_]+\.c):(\d+)\b")


def lookup_bios_code(code_sites: List[str], context: int = 6,
                     max_sites: int = 4) -> List[Dict[str, Any]]:
    """If a local BIOS checkout is configured (BIOS_REPO_PATH), pull the source
    around the exact file:line sites seen in the logs. Returns [] otherwise."""
    root = config.BIOS_REPO_PATH
    if not root or not os.path.isdir(root):
        return []
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for site in code_sites:
        m = _CODE_SITE_RE.search(site)
        if not m:
            continue
        fname, line = m.group(1), int(m.group(2))
        if (fname, line) in seen:
            continue
        seen.add((fname, line))
        path = _find_file(root, fname)
        if not path:
            out.append({"site": f"{fname}:{line}", "found": False, "snippet": ""})
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            lo = max(0, line - 1 - context)
            hi = min(len(lines), line - 1 + context + 1)
            snippet = "".join(
                f"{'>' if (i + 1) == line else ' '} {i + 1:>5}: {lines[i]}"
                for i in range(lo, hi))
            out.append({"site": f"{fname}:{line}",
                        "path": os.path.relpath(path, root),
                        "found": True, "snippet": snippet.rstrip()})
        except Exception:
            out.append({"site": f"{fname}:{line}", "found": False, "snippet": ""})
        if len(out) >= max_sites:
            break
    return out


@lru_cache(maxsize=256)
def _find_file(root: str, fname: str) -> Optional[str]:
    for dirpath, _dirs, files in os.walk(root):
        if fname in files:
            return os.path.join(dirpath, fname)
    return None
