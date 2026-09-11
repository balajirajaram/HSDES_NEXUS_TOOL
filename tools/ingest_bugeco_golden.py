"""Ingest the manually validated RTL-Bugeco Golden Case batch.

This importer is append-only: it refuses to overwrite an existing case file.
Each listed sighting gets its own fixture while sharing the row's RTL Bugeco
validation evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]

ROWS: List[Dict[str, Any]] = [
    {
        "platform": "DMR",
        "sightings": ["14028507593", "21044871638"],
        "bugeco_id": "13013348392",
        "owner": "Core/FE/HAM",
        "secondary_ip": "Core/FE/DSB",
        "resolution": "Fix WIP (NOT yet fixed)",
        "notes": "HA ordering issue; WA in ucode (defeature). Fix is WIP and not yet confirmed.",
        "level": "LEVEL_3_REPRODUCED",
        "fix_validated": False,
    },
    {
        "platform": "DMR",
        "sightings": ["15019342741", "15019357856", "15019358385", "15019382716", "15019383400"],
        "bugeco_id": "13013348392",
        "owner": "Core/FE/BPU",
        "resolution": "Fixed in PNC C0",
        "notes": "Root caused to Front End/BPU RTL bug; fixed in PNC C0.",
        "level": "LEVEL_4_FIX_VALIDATED",
        "fix_validated": True,
    },
    {
        "platform": "GNR",
        "sightings": ["22019405820"],
        "bugeco_id": "14021589581",
        "owner": "Acode",
        "secondary_ip": "Power/FW",
        "resolution": "Fixed in RWC-R0",
        "notes": "Fixed in Uncore/Acode.",
        "level": "LEVEL_4_FIX_VALIDATED",
        "fix_validated": True,
    },
    {
        "platform": "SPR",
        "sightings": ["1404503208"],
        "bugeco_id": "1309345419",
        "owner": "uCode",
        "resolution": "Fixed in GLC Q0",
        "notes": "Fixed in Core/uCode.",
        "level": "LEVEL_4_FIX_VALIDATED",
        "fix_validated": True,
        "additional_bugeco_ids": ["1309522432", "1308560873"],
    },
    {
        "platform": "SPR",
        "sightings": ["14014613214"],
        "bugeco_id": "1401131480",
        "owner": "Uncore",
        "secondary_ip": "Uncore/CHA",
        "resolution": "Fixed in CHA SPR-A0",
        "notes": "WA in uCode; fixed in Uncore/CHA.",
        "level": "LEVEL_4_FIX_VALIDATED",
        "fix_validated": True,
    },
    {
        "platform": "SPR",
        "sightings": ["14015800984"],
        "bugeco_id": "1401585456",
        "owner": "UPI Initialization",
        "secondary_ip": "Fuse Download",
        "resolution": "Fixed in SPR-E0",
        "notes": "Fixed in Pcode. This is a firmware/Pcode fix, not a silicon respin; record as FW-only resolution.",
        "level": "LEVEL_4_FIX_VALIDATED",
        "fix_validated": True,
    },
    {
        "platform": "SPR",
        "sightings": ["22014056631"],
        "bugeco_id": "14015439921",
        "owner": "Core/BPU",
        "secondary_ip": "Core/BPU",
        "resolution": "Fixed in SPR-Q0",
        "notes": "WA in ucode; fixed in FE/BPU RTL.",
        "level": "LEVEL_4_FIX_VALIDATED",
        "fix_validated": True,
    },
    {
        "platform": "ICX",
        "sightings": ["22010039282"],
        "bugeco_id": "1306993191",
        "owner": "uCode",
        "secondary_ip": "Core/MEU/DCU",
        "resolution": "Fixed in SNC E0",
        "notes": "WA in ucode; fixed in Core/MEU/DCU.",
        "level": "LEVEL_4_FIX_VALIDATED",
        "fix_validated": True,
        "additional_bugeco_ids": ["1306055589"],
    },
]

STATUS_RE = re.compile(r"(?i)\\b(?:mc\\s*status|status)\\s*[:=]?\\s*(0x[0-9a-f]{8,16})")
MCACOD_RE = re.compile(r"(?i)\\bmcacod\\s*[:=]?\\s*(0x[0-9a-f]+)")
MSCOD_RE = re.compile(r"(?i)\\bmscod\\s*[:=]?\\s*(0x[0-9a-f]+)")
BANK_RE = re.compile(r"(?i)\\b(?:mc\\s*bank|bank)\\s*[:=]?\\s*(?:0x)?(\\d+|[0-9a-f]+)")
SOCKET_RE = re.compile(r"(?i)\\b(?:socket|skt|s)\\s*[:=]?\\s*(\\d+)")


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
    return {
        "status": status,
        "mcacod": mcacod,
        "mscod": mscod,
        "bank": _parse_code(text, BANK_RE),
        "socket": _parse_code(text, SOCKET_RE),
    }


def build_case(row: Dict[str, Any], hsd_id: str, article: Dict[str, Any]) -> Dict[str, Any]:
    article_text = "\\n".join(str(article.get(key) or "") for key in
                                ("title", "description", "full_text", "comments"))
    parsed = _parse_mca(article_text)
    source = f"RTL Bugeco {row['bugeco_id']}; fixed in {row['resolution']}"
    notes = row["notes"]
    if row.get("additional_bugeco_ids"):
        notes += "; additional RTL Bugeco IDs: " + ", ".join(row["additional_bugeco_ids"])
    case: Dict[str, Any] = {
        "hsd_id": hsd_id,
        "platform": row["platform"],
        "domain": row["owner"],
        "validation_level": row["level"],
        "expected_owner": row["owner"],
        "expected_reporting_ip": row["owner"],
        "expected_first_error": row["owner"],
        "expected_bank": parsed["bank"],
        "expected_socket": parsed["socket"],
        "expected_mcacod": parsed["mcacod"],
        "expected_mscod": parsed["mscod"],
        "expected_verdict": "CONFIRMED",
        "min_confidence": 0,
        "expected_contradiction": False,
        "notes": notes,
        "evidence": {
            "source": source,
            "validation_source": source,
            "validated_by": "RTL/Silicon validation (bugeco record)",
            "fix_validated": row["fix_validated"],
            "source_references": [row["bugeco_id"]],
        },
        "expected": {
            "owner": row["owner"],
            "reporting_ip": row["owner"],
            "originating_ip": row["owner"],
            "bank": parsed["bank"],
            "socket": parsed["socket"],
            "mcacod": parsed["mcacod"],
            "mscod": parsed["mscod"],
            "verdict": "CONFIRMED",
            "root_cause": notes,
        },
        "bugeco_id": row["bugeco_id"],
    }
    if row.get("secondary_ip"):
        case["secondary_ip"] = row["secondary_ip"]
    return case


async def ingest(output_root: Path) -> Dict[str, Any]:
    from app.hsdes_client import HSDESClient

    client = HSDESClient()
    written: List[str] = []
    counts: Dict[str, int] = {}
    article_errors: List[Dict[str, str]] = []
    for row in ROWS:
        for hsd_id in row["sightings"]:
            destination = output_root / row["platform"] / f"{hsd_id}.json"
            if destination.exists():
                # Keep the first-batch fixture intact while adding this higher-confidence overlay.
                destination = output_root / row["platform"] / f"{hsd_id}_bugeco.json"
            if destination.exists():
                raise FileExistsError(f"Refusing to overwrite existing Bugeco Golden Case: {destination}")
            article = await client.get_article(hsd_id) or {}
            if article.get("error"):
                article_errors.append({"hsd_id": hsd_id, "error": str(article["error"])})
            case = build_case(row, hsd_id, article)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
            written.append(str(destination.relative_to(output_root)))
            counts[row["platform"]] = counts.get(row["platform"], 0) + 1
    return {
        "rows": len(ROWS),
        "written": len(written),
        "platform_counts": counts,
        "article_errors": article_errors,
        "files": written,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest append-only RTL-Bugeco Golden Cases")
    parser.add_argument("--output-root", type=Path, default=ROOT / "golden_cases")
    args = parser.parse_args()
    result = asyncio.run(ingest(args.output_root))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
