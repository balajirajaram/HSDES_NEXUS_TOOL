"""Ingest the pre-validated 32-row sandstone silicon seed set.

This is intentionally limited to sandstone_TRUE_silicon_bugs_for_excel.csv.
It does not use the broader audit file to add C_needs_review rows and does not
invent missing MCA/socket fields.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
OWNER_MAP = {
    "hw.big_core": "Core", "hw.small_core": "Core", "hw.cha": "CHA",
    "hw.mesh": "Mesh/Fabric", "hw.upi": "UPI", "hw.uncore": "Uncore",
    "hw.mdf": "MDF", "hw.dsa": "DSA", "hw.memory": "Memory/IMC",
    "hw.ras": "RAS", "hw.security": "Security", "hw.configrom": "ConfigROM",
}
STATUS_RE = re.compile(r"(?i)\b(?:mc\s*status|status)\s*[:=]?\s*(0x[0-9a-f]{8,16})")
MCACOD_RE = re.compile(r"(?i)\bmcacod\s*[:=]?\s*(0x[0-9a-f]+)")
MSCOD_RE = re.compile(r"(?i)\bmscod\s*[:=]?\s*(0x[0-9a-f]+)")
BANK_RE = re.compile(r"(?i)\b(?:mc\s*bank|bank)\s*[:=]?\s*(?:0x)?(\d+|[0-9a-f]+)")
SOCKET_RE = re.compile(r"(?i)\b(?:socket|skt|s)\s*[:=]?\s*(\d+)")


def _parse_code(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text or "")
    return match.group(1).upper() if match else None


def _parse_mca(text: str) -> Dict[str, str | None]:
    status = _parse_code(text, STATUS_RE)
    mcacod = _parse_code(text, MCACOD_RE)
    mscod = _parse_code(text, MSCOD_RE)
    if status:
        try:
            value = int(status, 16)
            mcacod = mcacod or f"0x{value & 0xFFFF:04X}"
            mscod = mscod or f"0x{(value >> 16) & 0xFFFF:04X}"
        except ValueError:
            pass
    return {"status": status, "mcacod": mcacod, "mscod": mscod,
            "bank": _parse_code(text, BANK_RE), "socket": _parse_code(text, SOCKET_RE)}


def _root_cause(row: Dict[str, str], article: Dict[str, Any]) -> str:
    return str(row.get("rootcause_sighting") or article.get("title") or "").strip()


def build_case(row: Dict[str, str], article: Dict[str, Any]) -> Dict[str, Any]:
    article_text = "\n".join(str(article.get(key) or "") for key in
                                ("title", "description", "full_text", "comments"))
    parsed = _parse_mca(article_text + "\n" + row.get("title", ""))
    component = str(row.get("component_nature") or "").lower()
    owner = OWNER_MAP.get(component, component or None)
    confirmed_via = str(row.get("confirmed_via") or "")
    is_bugeco = confirmed_via in {"bugeco", "bugeco+sighting"}
    if is_bugeco:
        level = "LEVEL_4_FIX_VALIDATED"
        source = "bugeco:" + str(row.get("bugeco_hsd_ids") or "")
    else:
        level = "LEVEL_3_REPRODUCED"
        source = f"{row.get('rootcause_sighting', '')}={row.get('defect_history', '')}.hw.bug"
    missing = []
    for field in ("mcacod", "mscod", "bank", "socket"):
        if not parsed[field]:
            missing.append(field)
    note = "bank/MCACOD/socket not auto-parsed, needs manual annotation" if missing else ""
    return {
        "hsd_id": str(row["atscale_hsd_id"]),
        "platform": str(row.get("codename") or "UNKNOWN").upper(),
        "domain": component or "unknown",
        "validation_level": level,
        "expected_owner": owner or "UNKNOWN",
        "expected_reporting_ip": owner or "",
        "expected_first_error": owner or "",
        "expected_bank": parsed["bank"],
        "expected_socket": parsed["socket"],
        "expected_mcacod": parsed["mcacod"],
        "expected_mscod": parsed["mscod"],
        "expected_verdict": "CONFIRMED",
        "min_confidence": 0,
        "expected_contradiction": False,
        "notes": _root_cause(row, article) + (f"; {note}" if note else ""),
        "evidence": {
            "source": source,
            "validated_by": "sighting_central RCA process (Intel)",
            "validation_source": source,
            "fix_validated": is_bugeco,
            "source_references": [str(row.get("atscale_hsd_link") or "")],
        },
        "expected": {
            "owner": owner or "UNKNOWN", "reporting_ip": owner or "",
            "originating_ip": owner or "", "bank": parsed["bank"],
            "socket": parsed["socket"], "mcacod": parsed["mcacod"],
            "mscod": parsed["mscod"], "verdict": "CONFIRMED",
            "root_cause": _root_cause(row, article),
        },
    }


async def ingest(input_csv: Path, output_root: Path) -> Dict[str, Any]:
    import csv
    from app.hsdes_client import HSDESClient
    with input_csv.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    client = HSDESClient()
    counts: Dict[str, int] = {}
    incomplete = []
    written = []
    for row in rows:
        hsd_id = str(row.get("atscale_hsd_id") or "").strip()
        if not hsd_id:
            continue
        article = await client.get_article(hsd_id) or {}
        case = build_case(row, article)
        platform = case["platform"]
        destination = output_root / platform / f"{hsd_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        written.append(str(destination.relative_to(output_root)))
        counts[platform] = counts.get(platform, 0) + 1
        missing = [f for f in ("expected_mcacod", "expected_mscod", "expected_bank", "expected_socket") if not case[f]]
        if missing:
            incomplete.append({"hsd_id": hsd_id, "platform": platform, "missing": missing})
    return {"input_rows": len(rows), "written": len(written), "platform_counts": counts,
            "incomplete": incomplete, "files": written}


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest validated sandstone Golden Case seeds")
    parser.add_argument("--input", type=Path, default=ROOT / "sandstone_TRUE_silicon_bugs_for_excel.csv")
    parser.add_argument("--output-root", type=Path, default=ROOT / "golden_cases")
    args = parser.parse_args()
    result = asyncio.run(ingest(args.input, args.output_root))
    print(json.dumps(result, indent=2))
    return 0 if result["written"] == result["input_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
