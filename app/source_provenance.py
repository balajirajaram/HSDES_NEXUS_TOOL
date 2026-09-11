"""Source trust metadata for decoder and knowledge provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

_INVENTORY = Path(__file__).with_name("knowledge") / "source_inventory.json"
_TRUST_RANK = {
    "AUTHORITATIVE": 100,
    "OFFICIAL_INTERNAL": 90,
    "VALIDATED_HISTORICAL": 80,
    "ENGINEER_KNOWLEDGE": 50,
    "LLM_INFERENCE": 20,
    "UNKNOWN": 0,
}


def load_inventory(path: Path = _INVENTORY) -> List[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("entries") or [])
    except (OSError, ValueError, TypeError):
        return []


def inventory_entry(path: str, entries: Iterable[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    wanted = path.replace("\\", "/")
    for entry in entries if entries is not None else load_inventory():
        if str(entry.get("path", "")).replace("\\", "/") == wanted:
            result = dict(entry)
            result["score"] = _TRUST_RANK.get(str(result.get("trust", "UNKNOWN")), 0)
            return result
    return {"path": wanted, "trust": "UNKNOWN", "score": 0,
            "owner": "UNKNOWN", "origin": "UNKNOWN",
            "source_document": "UNKNOWN", "last_validated": "UNKNOWN"}


def provenance_for(path: str) -> Dict[str, Any]:
    return inventory_entry(path)


def is_authoritative(path: str) -> bool:
    return provenance_for(path).get("trust") == "AUTHORITATIVE"


def quality_report(root: Path) -> Dict[str, Any]:
    """Audit listed JSON decoder/knowledge resources for inventory coverage."""
    entries = load_inventory()
    by_path = {str(e.get("path", "")).replace("\\", "/"): e for e in entries}
    resource_dirs = (root / "app" / "decoders", root / "app" / "knowledge")
    resources = sorted({p.relative_to(root).as_posix() for directory in resource_dirs
                        if directory.exists() for p in directory.glob("*.json")})
    missing = [p for p in resources if p not in by_path]
    unknown = [p for p in resources if p in by_path
               and str(by_path[p].get("trust", "UNKNOWN")) == "UNKNOWN"]
    duplicate_paths = sorted({p for p in resources if resources.count(p) > 1})
    return {"resources": resources, "inventory_entries": len(entries),
            "missing_inventory": missing, "unknown_trust": unknown,
            "duplicate_paths": duplicate_paths,
            "coverage_percent": (100 * (len(resources) - len(missing)) / len(resources)
                                  if resources else 100.0)}
