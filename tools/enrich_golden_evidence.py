"""Enrich Golden Cases with minimal source-derived evidence from HSDES.

Only title/description text fetched from the HSD article is used. Expected owner,
MCA, and validation fields are never copied into machine_evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
_STATUS = re.compile(r"(?i)(?:status|mc_status|mce\s*\d+\s*status)\s*[:=]?\s*(0x[0-9a-f]{6,16})")
_EXPLICIT_MCACOD = re.compile(r"(?i)\bmcacod\s*[:=]?\s*(0x[0-9a-f]+)")
_EXPLICIT_MSCOD = re.compile(r"(?i)\bmscod\s*[:=]?\s*(0x[0-9a-f]+)")
_BANK = re.compile(r"(?i)\bmc\s*bank\s*(?:=|:)\s*(0x[0-9a-f]+|\d+)")
_IERR = re.compile(r"(?i)(?:first\s+)?(?:ierr|mcerr|caterr)[^\n]{0,160}")


def _raw_evidence(title: str, description: str) -> tuple[Dict[str, Any] | None, str]:
    status_matches = _STATUS.findall(title)
    mcacod = _EXPLICIT_MCACOD.search(title)
    mscod = _EXPLICIT_MSCOD.search(title)
    bank = _BANK.search(title)
    ierr = _IERR.search(title)
    if not (status_matches or mcacod or mscod or bank or ierr):
        status_matches = _STATUS.findall(description)
        mcacod = _EXPLICIT_MCACOD.search(description)
        mscod = _EXPLICIT_MSCOD.search(description)
        bank = _BANK.search(description)
        ierr = _IERR.search(description)
    if not (status_matches or mcacod or mscod or bank or ierr):
        return None, "none"
    events = []
    for status in dict.fromkeys(status_matches):
        events.append({"status": status, "source_text": status})
    evidence: Dict[str, Any] = {"mca_events": events}
    if mcacod:
        evidence["mcacod"] = mcacod.group(1).upper()
    if mscod:
        evidence["mscod"] = mscod.group(1).upper()
    if bank:
        evidence["bank"] = bank.group(1).upper()
    if ierr:
        evidence["first_error"] = [{"source_text": ierr.group(0)}]
    return evidence, "reconstructed_from_hsd_title" if any(
        (status_matches, _EXPLICIT_MCACOD.search(title), _EXPLICIT_MSCOD.search(title),
         _BANK.search(title), _IERR.search(title))
    ) else "reconstructed_from_hsd_description"


async def enrich(root: Path) -> Dict[str, int]:
    from app.hsdes_client import HSDESClient
    client = HSDESClient()
    enriched = 0
    insufficient = 0
    errors = 0
    for path in sorted(root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not case.get("hsd_id"):
            continue
        article = await client.get_article(str(case["hsd_id"]))
        if not article or article.get("error"):
            errors += 1
            continue
        title = str(article.get("title") or "")
        description = str(article.get("description") or "")
        evidence, source = _raw_evidence(title, description)
        case["title"] = title
        case["description"] = description
        case["evidence_source"] = source
        case["machine_evidence"] = evidence
        if evidence:
            enriched += 1
        else:
            insufficient += 1
        path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    return {"enriched": enriched, "insufficient_evidence": insufficient, "fetch_errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="Add source-derived evidence to Golden Cases")
    parser.add_argument("--dir", type=Path, default=ROOT / "golden_cases")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(enrich(args.dir)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
