"""Explain candidate gaps without changing candidate approval or Golden Cases."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
GAP_FIELDS = [
    "hsd_id", "platform", "source_query_id", "status", "tier", "approval_status",
    "evidence_score", "owner", "attachments_present", "validation_evidence",
    "rejection_reasons", "missing_evidence", "gap_count", "fastest_path_to_promotion",
    "promotion_effort_rank",
]
UNKNOWN_FIELDS = [
    "hsd_id", "source_query_id", "status", "domain", "owner", "title_or_summary",
    "unknown_reason", "missing_field", "next_action",
]
PROMOTION_FIELDS = [
    "hsd_id", "platform", "domain", "current_tier", "evidence_score",
    "missing_items", "reproduction_missing", "fix_validation_missing",
    "owner_missing", "root_cause_missing", "attachments_missing",
    "transfer_chain_unresolved", "duplicate_chain_unresolved", "decoder_ambiguity",
    "ownership_conflict", "platform_unknown", "fastest_promotion_path",
    "recommended_upgrade", "evidence_found", "evidence_missing", "why_not_gold",
    "confidence", "reviewer_needed", "recommendation", "human_decision",
]
MAX_REVIEW_CASES = 15


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def unknown_platform_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    result = []
    for row in rows:
        if str(row.get("platform", "")).upper() != "UNKNOWN":
            continue
        result.append({
            "hsd_id": row.get("hsd_id", ""),
            "source_query_id": row.get("source_query_id", ""),
            "status": row.get("status", ""),
            "domain": row.get("domain", ""),
            "owner": row.get("owner", ""),
            "title_or_summary": row.get("root_cause_summary", ""),
            "unknown_reason": "Platform did not match GNR/SRF/CWF/DMR/COR normalization",
            "missing_field": "platform/product_found/family_affected or recognized platform token",
            "next_action": "Read HSD summary/title and assign platform before review",
        })
    return result


def _gap_reasons(row: Dict[str, str]) -> List[str]:
    reasons = []
    missing = {x for x in (row.get("missing_evidence") or "").split(";") if x}
    rejection = {x for x in (row.get("rejection_reasons") or "").split(";") if x}
    if row.get("approval_status") == "REJECTED":
        reasons.append("NON_TERMINAL_OR_REJECTED_STATUS")
    if "attachments/logs" in missing or row.get("attachments_present") != "Yes":
        reasons.append("ATTACHMENTS_OR_LOGS_MISSING")
    if "independent root cause" in missing or "NO_INDEPENDENT_ROOT_CAUSE" in rejection:
        reasons.append("ROOT_CAUSE_MISSING")
    if "reproduction or fix validation" in missing or "NO_FIX_VALIDATION" in rejection:
        reasons.append("REPRODUCTION_OR_FIX_VALIDATION_MISSING")
    if not row.get("owner", "").strip() or row.get("platform", "") == "UNKNOWN":
        reasons.append("OWNER_OR_PLATFORM_UNRESOLVED")
    if "ROOT_CAUSE_COMMENT_ONLY" in rejection:
        reasons.append("ROOT_CAUSE_COMMENT_ONLY")
    if "ACTIVE_OWNERSHIP_CONTRADICTION" in rejection:
        reasons.append("OWNERSHIP_CONTRADICTION")
    if "DECODER_AMBIGUITY" in rejection:
        reasons.append("DECODER_AMBIGUITY")
    return reasons


def gap_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    result = []
    for row in rows:
        reasons = _gap_reasons(row)
        if not reasons:
            reasons = ["NO_RECORDED_GAP"]
        paths = {
                "NON_TERMINAL_OR_REJECTED_STATUS": "Resolve disposition or replace candidate",
            "ATTACHMENTS_OR_LOGS_MISSING": "Collect logs/attachments",
            "ROOT_CAUSE_MISSING": "Document independently supported root cause",
            "REPRODUCTION_OR_FIX_VALIDATION_MISSING": "Add reproduction or fix validation",
            "OWNER_OR_PLATFORM_UNRESOLVED": "Resolve owner/platform from HSD evidence",
            "ROOT_CAUSE_COMMENT_ONLY": "Replace comment-only claim with independent evidence",
            "OWNERSHIP_CONTRADICTION": "Resolve ownership conflict with domain expert",
            "DECODER_AMBIGUITY": "Resolve decoder ambiguity with authoritative source",
        }
        fastest = paths.get(reasons[0], "Review evidence")
        result.append({
            "hsd_id": row.get("hsd_id", ""),
            "platform": row.get("platform", ""),
            "source_query_id": row.get("source_query_id", ""),
            "status": row.get("status", ""),
            "tier": row.get("suggested_tier", ""),
            "approval_status": row.get("approval_status", ""),
            "evidence_score": row.get("evidence_score", ""),
            "owner": row.get("owner", ""),
            "attachments_present": row.get("attachments_present", ""),
            "validation_evidence": row.get("validation_evidence", ""),
            "rejection_reasons": row.get("rejection_reasons", ""),
            "missing_evidence": row.get("missing_evidence", ""),
            "gap_count": str(len(reasons)),
            "fastest_path_to_promotion": fastest,
            "promotion_effort_rank": ",".join(reasons),
        })
    return sorted(result, key=lambda r: (
        0 if r["approval_status"] != "REJECTED" else 1,
        int(r["gap_count"]), -int(r["evidence_score"] or 0), r["hsd_id"]))


def write_csv(path: Path, fields: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def promotion_rows(rows: List[Dict[str, str]], gaps: List[Dict[str, str]]) -> List[Dict[str, str]]:
    gap_by_id = {row["hsd_id"]: row for row in gaps}
    result = []
    for row in rows:
        if row.get("approval_status") == "REJECTED":
            continue
        gap = gap_by_id.get(row.get("hsd_id", ""), {})
        reasons = set(filter(None, gap.get("promotion_effort_rank", "").split(",")))
        fix_missing = "REPRODUCTION_OR_FIX_VALIDATION_MISSING" in reasons
        root_missing = "ROOT_CAUSE_MISSING" in reasons
        owner_missing = "OWNER_OR_PLATFORM_UNRESOLVED" in reasons
        attachment_missing = "ATTACHMENTS_OR_LOGS_MISSING" in reasons
        upgrade = "PLATINUM" if not fix_missing and not root_missing else "GOLD"
        critical = {"OWNER_OR_PLATFORM_UNRESOLVED", "OWNERSHIP_CONTRADICTION",
                    "DECODER_AMBIGUITY", "ROOT_CAUSE_COMMENT_ONLY"}
        reviewer_needed = bool(critical.intersection(reasons))
        evidence_found = []
        if row.get("attachments_present") == "Yes":
            evidence_found.append("attachments/logs")
        if row.get("validation_evidence") not in ("", "No validation evidence", "Root Cause Comment Only"):
            evidence_found.append(row.get("validation_evidence", ""))
        if row.get("owner", "").strip():
            evidence_found.append("owner")
        if root_missing or attachment_missing or owner_missing:
            recommendation = "REVIEW"
        elif not reviewer_needed:
            recommendation = "AUTO_APPROVE_CANDIDATE"
        else:
            recommendation = "NEEDS_REVIEW"
        why_not_gold = "Already has independent evidence" if not root_missing else "Missing independent root cause"
        if fix_missing:
            why_not_gold = "Missing reproduction or fix validation"
        confidence = max(0, min(100, int(row.get("evidence_score") or 0)))
        result.append({
            "hsd_id": row.get("hsd_id", ""),
            "platform": row.get("platform", ""),
            "domain": row.get("domain", ""),
            "current_tier": row.get("suggested_tier", ""),
            "evidence_score": row.get("evidence_score", ""),
            "missing_items": gap.get("missing_evidence", ""),
            "reproduction_missing": "Yes" if fix_missing else "No",
            "fix_validation_missing": "Yes" if fix_missing else "No",
            "owner_missing": "Yes" if owner_missing else "No",
            "root_cause_missing": "Yes" if root_missing else "No",
            "attachments_missing": "Yes" if attachment_missing else "No",
            "transfer_chain_unresolved": "Unknown",
            "duplicate_chain_unresolved": "Unknown",
            "decoder_ambiguity": "Yes" if "DECODER_AMBIGUITY" in reasons else "No",
            "ownership_conflict": "Yes" if "OWNERSHIP_CONTRADICTION" in reasons else "No",
            "platform_unknown": "Yes" if row.get("platform") == "UNKNOWN" else "No",
            "fastest_promotion_path": gap.get("fastest_path_to_promotion", "Review evidence"),
            "recommended_upgrade": upgrade,
            "evidence_found": ";".join(evidence_found),
            "evidence_missing": gap.get("missing_evidence", ""),
            "why_not_gold": why_not_gold,
            "confidence": str(confidence),
            "reviewer_needed": "Yes" if reviewer_needed else "No",
            "recommendation": recommendation,
            "human_decision": "PENDING",
        })
    return sorted(result, key=lambda row: (
        row["reviewer_needed"] == "Yes", -int(row["evidence_score"] or 0), row["hsd_id"]))


def write_review_cards(rows: List[Dict[str, str]], output: Path) -> None:
    cards = []
    for row in rows[:MAX_REVIEW_CASES]:
        cards.append(
            f"<article><h2>HSD {row['hsd_id']}</h2>"
            f"<p><b>Platform:</b> {row['platform']} &nbsp; <b>Domain:</b> {row['domain']} "
            f"&nbsp; <b>Current tier:</b> {row['current_tier']} &nbsp; <b>Score:</b> {row['evidence_score']}</p>"
            f"<p><b>Suggested upgrade:</b> {row['recommended_upgrade']} "
            f"<b>Fastest path:</b> {row['fastest_promotion_path']}</p>"
            f"<p><b>Evidence:</b> {row['evidence_found'] or 'none recorded'} "
            f"<b>Missing:</b> {row['evidence_missing'] or 'none recorded'}</p>"
            f"<p><b>Why not Gold:</b> {row['why_not_gold']} "
            f"<b>Confidence:</b> {row['confidence']}% "
            f"<b>Reviewer needed:</b> {row['reviewer_needed']}</p>"
            f"<p><b>Risk:</b> decoder ambiguity={row['decoder_ambiguity']}, "
            f"ownership conflict={row['ownership_conflict']}, platform unknown={row['platform_unknown']}</p>"
            "<p><b>Decision:</b> APPROVE / REJECT / REVIEW</p></article>"
        )
    html = "<!doctype html><meta charset=utf-8><title>NEXUS Candidate Review Cards</title>"
    html += "<style>body{font:14px system-ui;max-width:1000px;margin:2rem auto}article{border:1px solid #ddd;padding:1rem;margin:1rem 0}</style>"
    html += "<h1>NEXUS Candidate Review Cards</h1>" + "".join(cards)
    output.write_text(html, encoding="utf-8")


def write_approval_dashboard(rows: List[Dict[str, str]], output: Path) -> None:
    platforms = ["GNR", "SRF", "DMR", "COR", "CWF", "UNKNOWN"]
    counts = {platform: [row for row in rows if row.get("platform") == platform]
              for platform in platforms}
    tier_names = ("BRONZE", "SILVER", "GOLD", "PLATINUM")
    summary_rows = []
    for platform in platforms:
        platform_rows = counts[platform]
        tiers = {tier: sum(1 for row in platform_rows if row.get("current_tier") == tier)
                 for tier in tier_names}
        summary_rows.append(
            f"<tr><td>{platform}</td><td>{len(platform_rows)}</td>"
            + "".join(f"<td>{tiers[tier]}</td>" for tier in tier_names)
            + "</tr>"
        )
    top_rows = []
    for row in rows[:30]:
        risk = []
        if row.get("platform_unknown") == "Yes":
            risk.append("platform")
        if row.get("owner_missing") == "Yes":
            risk.append("owner")
        if row.get("root_cause_missing") == "Yes":
            risk.append("RCA")
        if row.get("fix_validation_missing") == "Yes":
            risk.append("fix validation")
        if row.get("attachments_missing") == "Yes":
            risk.append("attachments")
        required = "domain expert" if row.get("ownership_conflict") == "Yes" or row.get("decoder_ambiguity") == "Yes" else "reviewer"
        top_rows.append(
            f"<tr><td>{row['hsd_id']}</td><td>{row['platform']}</td>"
            f"<td>{row['current_tier']}</td><td>{row['evidence_score']}</td>"
            f"<td>{row['recommended_upgrade']}</td><td>{row['fastest_promotion_path']}</td>"
            f"<td>{', '.join(risk) or 'none recorded'}</td><td>{required}</td></tr>"
        )
    html = "<!doctype html><meta charset=utf-8><title>NEXUS Golden Approval Dashboard</title>"
    html += "<style>body{font:14px system-ui;max-width:1200px;margin:2rem auto}table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border:1px solid #e6e6e6;padding:.45rem;text-align:left}th{background:#f5f5f5}.status{padding:.7rem;background:#fff3cd;font-weight:bold}</style>"
    html += "<h1>NEXUS Golden Approval Dashboard</h1>"
    html += f"<p class=status>Production status: NOT APPROVED. Qualified Golden Cases: 0/30. Human approval required.</p>"
    html += "<h2>Platform Coverage</h2><table><tr><th>Platform</th><th>Total</th>"
    html += "".join(f"<th>{tier.title()}</th>" for tier in tier_names) + "</tr>"
    html += "".join(summary_rows) + "</table>"
    html += "<h2>Fastest Candidates to Promote</h2><table><tr><th>HSD</th><th>Platform</th><th>Tier</th><th>Score</th><th>Suggested Upgrade</th><th>Fastest Path</th><th>Risk</th><th>Required Reviewer</th></tr>"
    html += "".join(top_rows) or "<tr><td colspan=8>No candidates available</td></tr>"
    html += "</table><h2>Decision</h2><p>Approve only after independent RCA, Level 3 reproduction or Level 4 fix validation, named validator, and source provenance are confirmed. This dashboard never promotes cases.</p>"
    output.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate candidate platform/gap reports")
    parser.add_argument("--input", type=Path, default=ROOT / "golden_candidates.csv")
    parser.add_argument("--unknown-output", type=Path, default=ROOT / "unknown_platform.csv")
    parser.add_argument("--gap-output", type=Path, default=ROOT / "candidate_gap_analysis.csv")
    parser.add_argument("--top-output", type=Path, default=ROOT / "top_30_easiest_candidates.csv")
    parser.add_argument("--promotion-output", type=Path, default=ROOT / "promotion_candidates.csv")
    parser.add_argument("--cards-output", type=Path, default=ROOT / "candidate_review_cards.html")
    parser.add_argument("--platform-output", type=Path, default=ROOT / "platform_normalization_report.csv")
    parser.add_argument("--conflict-output", type=Path, default=ROOT / "ownership_conflict_report.csv")
    parser.add_argument("--summary-output", type=Path, default=ROOT / "qualification_summary.md")
    parser.add_argument("--dashboard-output", type=Path, default=ROOT / "golden_approval_dashboard.html")
    parser.add_argument("--platform-fix-output", type=Path, default=ROOT / "platform_fix_candidates.csv")
    args = parser.parse_args()
    rows = _rows(args.input)
    unknown = unknown_platform_rows(rows)
    gaps = gap_rows(rows)
    write_csv(args.unknown_output, UNKNOWN_FIELDS, unknown)
    write_csv(args.gap_output, GAP_FIELDS, gaps)
    write_csv(args.top_output, GAP_FIELDS, gaps[:30])
    promotions = promotion_rows(rows, gaps)
    write_csv(args.promotion_output, PROMOTION_FIELDS, promotions)
    write_review_cards(promotions, args.cards_output)
    write_approval_dashboard(promotions, args.dashboard_output)
    write_csv(args.platform_output, UNKNOWN_FIELDS, unknown)
    conflicts = [row for row in gaps if "OWNERSHIP_CONTRADICTION" in row.get("promotion_effort_rank", "")]
    write_csv(args.conflict_output, GAP_FIELDS, conflicts)
    platform_fixes = [row for row in unknown]
    write_csv(args.platform_fix_output, UNKNOWN_FIELDS, platform_fixes)
    summary = [
        "# NEXUS Qualification Summary", "", "## Current State",
        f"- Candidates analyzed: {len(rows)}",
        f"- Unknown platform: {len(unknown)}",
        f"- Promotion recommendations: {len(promotions)}",
        f"- Candidates without expert review recommendation: {sum(1 for row in promotions if row['recommendation'] == 'AUTO_APPROVE_CANDIDATE')}",
        f"- Candidates requiring reviewer: {sum(1 for row in promotions if row['reviewer_needed'] == 'Yes')}",
        f"- Qualified Golden Cases: 0/30", "",
        "## Remaining Work",
        "- Resolve platform normalization for unknown records.",
        "- Add independent RCA, reproduction, fix-validation, and ownership evidence to Bronze cases.",
        f"- Human approval is required before any promotion; review queue is capped at {MAX_REVIEW_CASES}.", "",
        "## Expected Benchmark Impact",
        "- No benchmark impact until Level 3/4 cases are approved and promoted.",
        "- Promotion recommendations are advisory only and do not create Golden Cases.", "",
        "## Decision", "- Production status: NOT APPROVED",
    ]
    args.summary_output.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"Candidates analyzed: {len(rows)}")
    print(f"Unknown platform: {len(unknown)}")
    print(f"Gap rows: {len(gaps)}")
    print(f"Top easiest candidates: {min(30, len(gaps))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
