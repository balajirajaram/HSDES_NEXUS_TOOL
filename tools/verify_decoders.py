"""Audit decoder and knowledge resources against source_inventory.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.source_provenance import load_inventory, quality_report  # noqa: E402


def _duplicate_keys(path: Path) -> list[str]:
    """Detect duplicate top-level keys without silently accepting the last value."""
    duplicates: list[str] = []

    def hook(pairs):
        seen = set()
        result = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(f"{path}: {key}")
            seen.add(key)
            result[key] = value
        return result

    try:
        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    except (OSError, ValueError) as exc:
        duplicates.append(f"{path}: invalid JSON ({exc})")
    return duplicates


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit NEXUS decoder source provenance")
    parser.add_argument("--strict", action="store_true",
                        help="return failure when any resource has UNKNOWN trust")
    args = parser.parse_args()
    report = quality_report(ROOT)
    duplicate_keys = []
    for relative in report["resources"]:
        duplicate_keys.extend(_duplicate_keys(ROOT / relative))
    print(f"Resources discovered: {len(report['resources'])}")
    print(f"Inventory entries: {report['inventory_entries']}")
    print(f"Inventory coverage: {report['coverage_percent']:.1f}%")
    print(f"Missing inventory: {len(report['missing_inventory'])}")
    for path in report["missing_inventory"]:
        print(f"  MISSING {path}")
    print(f"Unknown trust: {len(report['unknown_trust'])}")
    for path in report["unknown_trust"]:
        print(f"  UNKNOWN {path}")
    print(f"Duplicate JSON keys: {len(duplicate_keys)}")
    for item in duplicate_keys:
        print(f"  DUPLICATE {item}")
    failed = bool(report["missing_inventory"] or duplicate_keys
                  or (args.strict and report["unknown_trust"]))
    print("QUALITY: FAIL" if failed else "QUALITY: PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
