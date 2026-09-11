"""Generate AutoHSD evidence-collection recommendations without execution."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


def _candidate_profile(row: Dict[str, str]) -> Dict[str, Any]:
    missing = [x for x in (row.get("missing_evidence") or "").split(";") if x]
    platform = row.get("platform", "UNKNOWN")
    domain = row.get("domain", "Other")
    commands = []
    required = []
    if "attachments/logs" in missing:
        required.append({"data": "SOL/PythonSV/crashdump logs", "why": "No machine evidence is attached", "benefit": "Enables MCA, boot, socket, and ownership decoding"})
        commands += ["# Recommendation only: collect and attach SOL/serial + PythonSV + crashdump artifacts"]
    if "independent root cause" in missing:
        required.append({"data": "Independent RCA evidence", "why": "Current RCA is absent or not independently supported", "benefit": "Separates machine evidence from human hypothesis"})
    if "reproduction or fix validation" in missing:
        required.append({"data": "Reproduction or pass/fail comparison", "why": "No reproducibility or fix-validation record is present", "benefit": "Supports Level 3/Level 4 qualification"})
        commands += ["# Recommendation only: capture failing and passing runs with identical ingredients"]
    commands += [
        "# Recommendation only; do not execute automatically",
        "sv.sockets  # enumerate actual sockets before selecting a socket-specific read",
        "sv.<resolved_socket>.uncore.mca.dump()  # collect MCA status/address/misc",
    ]
    if domain in {"MCA", "Memory"} or "mca" in platform.lower():
        commands += ["rdmsr -a 0x401+4*N  # collect MCi_STATUS for each relevant bank",
                     "rdmsr -a 0x402+4*N  # collect MCi_ADDR when ADDRV is set",
                     "rdmsr -a 0x403+4*N  # collect MCi_MISC when MISCV is set"]
    if domain == "PCIe/CXL":
        commands += ["# Recommendation only: collect PCIe AER/CXL error status and device topology"]
    if domain == "UPI":
        commands += ["# Recommendation only: collect UPI/KTI link status, retry, CRC, and phy-reset counters"]
    if domain == "Memory":
        commands += ["# Recommendation only: collect IMC/DDR retry, CRC, DIMM/rank, and memory-controller status"]
    if domain == "BIOS/Boot":
        commands += ["# Recommendation only: collect POST/checkpoint history and BIOS/IFWI/BMC versions"]
    return {
        "hsd_id": row.get("hsd_id", ""), "platform": platform, "domain": domain,
        "current_tier": row.get("suggested_tier", ""), "owner": row.get("owner", ""),
        "missing_evidence": missing, "required_data": required, "commands": commands,
        "execution_policy": "RECOMMENDATION_ONLY_NOT_EXECUTED",
        "expected_benefit": "Increase evidence completeness and permit re-analysis",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AutoHSD collection recommendations")
    parser.add_argument("--candidates", type=Path, default=ROOT / "golden_candidates.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "autohsd_output")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with args.candidates.open(newline="", encoding="utf-8") as handle:
        profiles = [_candidate_profile(row) for row in csv.DictReader(handle)]
    profile_path = args.output_dir / "AutoHSD_Collection_Profile.json"
    profile_path.write_text(json.dumps({"execution_policy": "RECOMMENDATION_ONLY_NOT_EXECUTED",
                                        "profiles": profiles}, indent=2), encoding="utf-8")
    pack_lines = ["NEXUS AutoHSD Command Pack", "", "POLICY: RECOMMENDATION ONLY. NO COMMANDS WERE EXECUTED.", ""]
    for profile in profiles:
        pack_lines += [f"HSD {profile['hsd_id']} | {profile['platform']} | {profile['domain']}"]
        pack_lines += [f"- {command}" for command in profile["commands"]]
        pack_lines.append("")
    (args.output_dir / "AutoHSD_Command_Pack.txt").write_text("\n".join(pack_lines), encoding="utf-8")
    cards = []
    for profile in profiles[:30]:
        cards.append(f"<article><h2>HSD {html.escape(profile['hsd_id'])}</h2>"
                     f"<p><b>Platform:</b> {html.escape(profile['platform'])} <b>Domain:</b> {html.escape(profile['domain'])} <b>Tier:</b> {html.escape(profile['current_tier'])}</p>"
                     f"<p><b>Missing evidence:</b> {html.escape('; '.join(profile['missing_evidence']) or 'none recorded')}</p>"
                     f"<p><b>Expected benefit:</b> {html.escape(profile['expected_benefit'])}</p>"
                     "<p><b>Policy:</b> Recommendation only. Commands are not executed.</p></article>")
    dashboard = "<!doctype html><meta charset=utf-8><title>AutoHSD Dashboard</title>"
    dashboard += "<style>body{font:14px system-ui;max-width:1100px;margin:2rem auto}article{border:1px solid #e6e6e6;padding:1rem;margin:1rem 0}</style>"
    dashboard += f"<h1>AutoHSD Evidence Collection Dashboard</h1><p>Profiles: {len(profiles)}. Execution policy: recommendation-only.</p>" + "".join(cards)
    (args.output_dir / "autohsd_dashboard.html").write_text(dashboard, encoding="utf-8")
    print(f"Profiles generated: {len(profiles)}")
    print("Commands were not executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
