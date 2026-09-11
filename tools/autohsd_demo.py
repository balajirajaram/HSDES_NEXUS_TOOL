"""AutoHSD demonstration mode: report recommendations only, no execution."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


def _profile(hsd_id: str, result: Dict[str, Any] | None) -> Dict[str, Any]:
    result = result or {}
    ownership = result.get("ownership") or result.get("extracted_ownership") or {}
    missing = result.get("missing_evidence") or result.get("required_missing_data") or []
    if isinstance(missing, str):
        missing = [missing]
    rca = result.get("root_cause") or result.get("rca") or result.get("report_markdown", "")[:800]
    bank = ownership.get("bank") or "N"
    socket = ownership.get("socket") or "<resolved_socket>"
    domain = str(ownership.get("domain") or result.get("domain") or "MCA/unknown")
    python_sv = [
        "# Recommendation only; do not execute automatically",
        "sv.sockets  # enumerate actual sockets",
        f"sv.socket{socket}.uncore.mca.dump()  # collect MC_STATUS/ADDR/MISC",
    ]
    status_scope = [
        "# Recommendation only; confirm exact paths for the platform/stepping",
        "status_scope --collect platform,stepping,bios,bmc,ucode",
        "status_scope --collect ierr,mcerr,mca,post,pcie,upi,memory",
    ]
    mca = [
        "# Recommendation only; use the resolved bank after log review",
        f"rdmsr -a 0x401+4*{bank}  # MCi_STATUS",
        f"rdmsr -a 0x402+4*{bank}  # MCi_ADDR when ADDRV=1",
        f"rdmsr -a 0x403+4*{bank}  # MCi_MISC when MISCV=1",
    ]
    if "PCIe" in domain or "CXL" in domain:
        status_scope.append("status_scope --collect pcie_aer,cxl_error_status,topology")
    if "UPI" in domain:
        python_sv.append("sv.socket<0..N>.upi.dump_links()  # UPI/KTI status and retry counters")
    if "Memory" in domain:
        python_sv.append("sv.socket<0..N>.imc.dump_status()  # IMC/DDR/DIMM evidence")
    return {
        "hsd_id": hsd_id, "rca": rca, "domain": domain,
        "missing_evidence": missing, "python_sv_commands": python_sv,
        "status_scope_commands": status_scope, "mca_commands": mca,
        "reanalysis_plan": [
            "1. Collect only the missing artifacts above.",
            "2. Attach the raw artifacts to the HSD or local analysis input.",
            "3. Re-run deterministic log/MCA/ownership analysis.",
            "4. Compare owner, socket, bank, MCACOD/MSCOD, confidence, and verdict.",
            "5. Keep the result draft-only if ambiguity or contradiction remains.",
        ],
        "execution_policy": "RECOMMENDATION_ONLY_NOT_EXECUTED",
    }


def render(profile: Dict[str, Any]) -> str:
    def bullets(values: List[str]) -> str:
        return "<ul>" + "".join(f"<li>{html.escape(str(value))}</li>" for value in values) + "</ul>"
    return """<!doctype html><meta charset=utf-8><title>AutoHSD Demonstration</title>
<style>body{{font:14px system-ui;max-width:1050px;margin:2rem auto}}section{{border:1px solid #e6e6e6;padding:1rem;margin:1rem 0}}h1{{margin-bottom:.2rem}}.policy{{background:#fff3cd;padding:.8rem;font-weight:bold}}code,li{{white-space:pre-wrap}}</style>
<h1>AutoHSD Demonstration Report</h1>
<p class=policy>Recommendation-only demonstration. No commands were executed and no HSDES write-back was performed.</p>
<section><h2>Input / RCA</h2><p><b>HSD:</b> {hsd}</p><p><b>Domain:</b> {domain}</p><p>{rca}</p></section>
<section><h2>Missing Evidence</h2>{missing}</section>
<section><h2>PythonSV Commands</h2>{python}</section>
<section><h2>StatusScope Commands</h2>{status}</section>
<section><h2>MCA Commands</h2>{mca}</section>
<section><h2>Re-analysis Plan</h2>{plan}</section>
""".format(hsd=html.escape(profile["hsd_id"]), domain=html.escape(profile["domain"]),
           rca=html.escape(profile["rca"]), missing=bullets(profile["missing_evidence"]),
           python=bullets(profile["python_sv_commands"]), status=bullets(profile["status_scope_commands"]),
           mca=bullets(profile["mca_commands"]), plan=bullets(profile["reanalysis_plan"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AutoHSD demonstration report")
    parser.add_argument("hsd_id")
    parser.add_argument("--result-json", type=Path, help="Optional local analysis result JSON")
    parser.add_argument("--output", type=Path, default=ROOT / "autohsd_demo_report.html")
    args = parser.parse_args()
    result = json.loads(args.result_json.read_text(encoding="utf-8")) if args.result_json else {}
    profile = _profile(args.hsd_id, result)
    args.output.write_text(render(profile), encoding="utf-8")
    print(f"AutoHSD demonstration report written: {args.output}")
    print("Commands were not executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
