"""Build a human-review candidate list; never promote tickets to golden_cases/.

Input is a JSON file containing HSDES search articles or a list of article
records. The records may include a read payload under ``data``. Search results
are candidate evidence only; validators must read and approve candidates before
creating golden-case JSON files.

Usage:
  python tools/build_golden_candidates.py --input hsdes_candidates.json
  python tools/build_golden_candidates.py --input hsdes_candidates.json \
      --output golden_candidates.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "golden_candidates.csv"
QUERY_IDS = ("16026853717", "16027811005", "16022833305", "14012297882",
             "16027523187", "16027357901")
REVIEW_QUOTAS = {"GNR": 10, "SRF": 10, "DMR": 5, "COR": 5}
TERMINAL_OK = {"complete", "verified", "implemented", "closed", "fixed", "resolved"}
REJECT_STATUSES = {"open", "new", "rejected", "duplicate", "blocked"}
PLATFORM_RE = re.compile(r"(?i)\b(GNR|SRF|CWF|DMR|COR)\b")
DOMAIN_TERMS = {
    "MCA": ("mca", "mce", "mcerr", "ierr", "machine check"),
    "UPI": ("upi", "kti", "link degrade", "phy reset"),
    "PCIe/CXL": ("pcie", "cxl", "aer", "poisoned tlp"),
    "Memory": ("memory", "dimm", "imc", "ddr", "umc"),
    "BIOS/Boot": ("bios", "boot", "postcode", "post code", "hang"),
}
CSV_FIELDS = [
    "platform", "hsd_id", "domain", "status", "owner", "root_cause_summary",
    "evidence_score", "fix_validation_present", "comments_present",
    "attachments_present", "validation_evidence", "suggested_tier",
    "why_selected", "rejection_reasons", "missing_evidence",
    "promote_eligible", "approval_status", "human_approval", "source_query_id",
    "bank", "socket", "mcacod", "mscod", "reporting_ip", "originating_ip",
]


def _unwrap(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, dict):
        articles = data.get("articles") or data.get("article") or data.get("records")
        if isinstance(articles, list):
            return [x for x in articles if isinstance(x, dict)]
        if data.get("id"):
            return [data]
    return []


def _text(record: Dict[str, Any]) -> str:
    fields = ("title", "description", "comments", "root_cause", "root_cause_summary",
              "fix_description", "resolution", "reason", "status_reason", "tag")
    return " ".join(str(record.get(k) or "") for k in fields).lower()


def _platform(record: Dict[str, Any]) -> str:
    text = " ".join(str(record.get(k) or "") for k in ("platform", "product_found", "title", "family_affected"))
    match = PLATFORM_RE.search(text)
    return match.group(1).upper() if match else "UNKNOWN"


def _domain(text: str) -> str:
    for domain, terms in DOMAIN_TERMS.items():
        if any(term in text for term in terms):
            return domain
    return "Other"


def _has_attachment(record: Dict[str, Any], text: str) -> bool:
    for key in ("attachments", "attachment_count", "images", "documents", "logs"):
        value = record.get(key)
        if isinstance(value, (list, dict)) and value:
            return True
        if isinstance(value, int) and value > 0:
            return True
    return any(term in text for term in ("attachment", "crashdump", "log attached", "logs:"))


def _has_root_cause(record: Dict[str, Any], text: str) -> bool:
    values = (record.get("root_cause"), record.get("root_cause_summary"),
              record.get("resolution"), record.get("fix_description"))
    return any(str(value or "").strip() for value in values) or "root cause" in text


def _fix_validation(record: Dict[str, Any], text: str) -> tuple[bool, str]:
    explicit = record.get("fix_validated")
    if explicit is True:
        return True, "Fix Validated"
    if any(term in text for term in ("fix validated", "reproduced", "a/b", "a-b experiment",
                                     "passing vs failing", "issue not seen", "verified with latest")):
        return True, "Fix Validated or Reproduced evidence present; reviewer confirmation required"
    return False, "Root Cause Comment Only" if "root cause" in text else "No validation evidence"


def score_candidate(record: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(record)
    status = str(record.get("status") or "UNKNOWN").lower()
    has_comments = bool(record.get("comments") or record.get("comment_count") or "comment" in text)
    has_attachments = _has_attachment(record, text)
    has_rca = _has_root_cause(record, text)
    fix_validated, validation_evidence = _fix_validation(record, text)
    evidence = 0
    rejection_reasons = []
    missing_evidence = []
    evidence += 20 if status in TERMINAL_OK and status not in REJECT_STATUSES else 0
    evidence += 20 if has_rca else 0
    evidence += 15 if fix_validated else 0
    evidence += 15 if has_attachments else 0
    evidence += 10 if record.get("mcacod") or "mcacod" in text or "mca" in text else 0
    evidence += 10 if record.get("first_error") or "ierr" in text or "mcerr" in text else 0
    evidence += 10 if record.get("expected_owner") or record.get("owner") else 0
    evidence -= 40 if validation_evidence == "Root Cause Comment Only" else 0
    evidence -= 30 if record.get("contradiction") else 0
    evidence -= 25 if record.get("decoder_ambiguity") else 0
    evidence -= 30 if not has_attachments else 0
    if not has_attachments:
        missing_evidence.append("attachments/logs")
    if not has_rca:
        missing_evidence.append("independent root cause")
    if not fix_validated:
        missing_evidence.append("reproduction or fix validation")
    if status in REJECT_STATUSES or status.startswith("open"):
        tier = "REJECT"
        why = "Open/rejected/non-terminal status"
        rejection_reasons.append("NON_TERMINAL_OR_REJECTED_STATUS")
    elif not has_rca:
        tier = "BRONZE"
        why = "Closed/terminal candidate, but root cause is not documented"
        rejection_reasons.append("NO_INDEPENDENT_ROOT_CAUSE")
    elif validation_evidence == "Root Cause Comment Only":
        tier = "SILVER"
        why = "Root cause appears only in human comments; never eligible for Gold/Platinum"
        rejection_reasons.append("ROOT_CAUSE_COMMENT_ONLY")
    elif fix_validated:
        tier = "PLATINUM"
        why = "Fix/reproduction evidence signal present; human validation required"
    else:
        tier = "GOLD"
        why = "Closed candidate with documented RCA; independent validation still required"
    if not fix_validated:
        rejection_reasons.append("NO_FIX_VALIDATION")
    if record.get("contradiction"):
        rejection_reasons.append("ACTIVE_OWNERSHIP_CONTRADICTION")
    if record.get("decoder_ambiguity"):
        rejection_reasons.append("DECODER_AMBIGUITY")
    eligible = tier == "PLATINUM" and evidence >= 70
    approval_status = "REJECTED" if tier == "REJECT" else (
        "PREQUALIFIED" if eligible else "MANUAL_REVIEW")
    return {
        "platform": _platform(record),
        "hsd_id": str(record.get("id") or record.get("hsd_id") or ""),
        "domain": _domain(text),
        "status": record.get("status", ""),
        "owner": record.get("owner", ""),
        "root_cause_summary": str(record.get("root_cause_summary") or record.get("root_cause") or record.get("resolution") or "")[:500],
        "evidence_score": evidence,
        "fix_validation_present": "Yes" if fix_validated else "No",
        "comments_present": "Yes" if has_comments else "No",
        "attachments_present": "Yes" if has_attachments else "No",
        "validation_evidence": validation_evidence,
        "suggested_tier": tier,
        "why_selected": why,
        "rejection_reasons": ";".join(sorted(set(rejection_reasons))),
        "missing_evidence": ";".join(sorted(set(missing_evidence))),
        "promote_eligible": "YES" if eligible else "NO",
        "approval_status": approval_status,
        "human_approval": "PENDING",
        "source_query_id": str(record.get("source_query_id") or ""),
        "bank": str(record.get("bank") or record.get("expected_bank") or ""),
        "socket": str(record.get("socket") or record.get("expected_socket") or ""),
        "mcacod": str(record.get("mcacod") or record.get("expected_mcacod") or ""),
        "mscod": str(record.get("mscod") or record.get("expected_mscod") or ""),
        "reporting_ip": str(record.get("reporting_ip") or ""),
        "originating_ip": str(record.get("originating_ip") or record.get("first_error") or ""),
    }


def build_candidates(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted((score_candidate(record) for record in records),
                  key=lambda row: (-int(row["evidence_score"]), row["platform"], row["hsd_id"]))


def write_candidates(rows: List[Dict[str, Any]], output: Path) -> None:
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_review_queues(rows: List[Dict[str, Any]], output: Path) -> None:
    queue_dir = output.parent / "golden_review"
    queue_dir.mkdir(parents=True, exist_ok=True)
    for name, predicate in {
        "rejected.csv": lambda r: r["approval_status"] == "REJECTED",
        "manual_review.csv": lambda r: r["approval_status"] == "MANUAL_REVIEW",
        "prequalified.csv": lambda r: r["approval_status"] == "PREQUALIFIED",
    }.items():
        with (queue_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(r for r in rows if predicate(r))


def reduce_review_pool(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Select the bounded human-review pool; never changes approval state."""
    selected = []
    for platform, limit in REVIEW_QUOTAS.items():
        platform_rows = [r for r in rows if r["platform"] == platform
                         and r["approval_status"] != "REJECTED"]
        selected.extend(platform_rows[:limit])
    return selected


def write_review_required(rows: List[Dict[str, Any]], output: Path) -> List[Dict[str, Any]]:
    selected = reduce_review_pool(rows)
    path = output.parent / "review_required.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    return selected


def write_candidate_summary(rows: List[Dict[str, Any]], output: Path) -> None:
    selected = reduce_review_pool(rows)
    cards = []
    for row in selected:
        cards.append(
            "<article class=\"candidate\"><h2>HSD " + row["hsd_id"] + "</h2>"
            f"<p><b>Platform:</b> {row['platform']} &nbsp; <b>Domain:</b> {row['domain']} "
            f"&nbsp; <b>Tier:</b> {row['suggested_tier']} &nbsp; <b>Score:</b> {row['evidence_score']}</p>"
            f"<p><b>Owner:</b> {row['owner']} &nbsp; <b>Bank:</b> {row['bank']} "
            f"&nbsp; <b>Socket:</b> {row['socket']} &nbsp; <b>MCACOD:</b> {row['mcacod']} "
            f"&nbsp; <b>MSCOD:</b> {row['mscod']}</p>"
            f"<p><b>Validation evidence:</b> {row['validation_evidence']}</p>"
            f"<p><b>Why selected:</b> {row['why_selected']}</p>"
            "<p class=\"decision\">Human decision: APPROVE / REJECT / NEEDS REVIEW</p></article>"
        )
    html = "<!doctype html><meta charset=utf-8><title>NEXUS Candidate Review</title>"
    html += "<style>body{font:14px system-ui;max-width:1000px;margin:2rem auto}.candidate{border:1px solid #ddd;padding:1rem;margin:1rem 0}.decision{font-weight:bold}</style>"
    html += "<h1>NEXUS Candidate Golden Case Review</h1>"
    html += f"<p>Review pool: {len(selected)}. No candidate has been promoted automatically.</p>"
    html += "".join(cards) or "<p>No review candidates.</p>"
    (output.parent / "candidate_summary.html").write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create human-review HSD golden candidates")
    parser.add_argument("--input", type=Path, required=True, help="Exported HSDES search/read JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = build_candidates(_unwrap(payload))
    write_candidates(rows, args.output)
    write_review_queues(rows, args.output)
    selected = write_review_required(rows, args.output)
    write_candidate_summary(rows, args.output)
    print(f"Wrote {len(rows)} candidates to {args.output}")
    print(f"Wrote {len(selected)} bounded review candidates")
    print("No golden_cases files were created; human approval is required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
