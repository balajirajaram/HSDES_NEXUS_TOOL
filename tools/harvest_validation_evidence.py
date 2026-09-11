"""Harvest validation evidence for Bronze/manual candidates.

This is a candidate-only stage. It never promotes or benchmarks cases. It uses
exported HSD article data and attachment metadata; richer HSDES history/link
fields are consumed when present in the export.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_FIELDS = [
    "hsd_id", "platform", "evidence_type", "evidence_source", "evidence_text",
    "confidence", "validation_level", "gold_eligible", "platinum_eligible",
]
PROMOTION_FIELDS = [
    "hsd_id", "platform", "current_tier", "recommended_tier", "evidence_found",
    "evidence_missing", "confidence", "gold_eligible", "platinum_eligible",
    "owner", "reviewer_needed", "recommendation", "why",
]
ASSIGNMENT_FIELDS = ["hsd_id", "platform", "domain", "risk", "assigned_reviewer", "reason", "status"]
DOMAIN_REVIEWERS = {
    "MCA": "Kandeepan",
    "Memory": "Jyoti",
    "PCIe/CXL": "Krishna",
    "UPI": "Sunil",
    "BIOS/Boot": "Kandeepan",
    "Other": "Kandeepan",
}
INDEPENDENT_TYPES = {"FIX_VALIDATION", "REPRODUCTION", "PASS_FAIL_EXPERIMENT"}


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _record_text(record: Dict[str, Any]) -> str:
    values = []
    for key in ("title", "description", "comments", "history", "links", "related",
                "resolution", "root_cause", "root_cause_summary", "fix_description",
                "status_reason", "reason", "attachments"):
        value = record.get(key)
        if value:
            values.append(str(value))
    return " ".join(values)


def _candidate_records(export_path: Path, candidate_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    if not export_path.exists():
        return {}
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    articles = payload.get("articles", payload) if isinstance(payload, dict) else payload
    by_id = {str(item.get("id")): item for item in articles or [] if isinstance(item, dict)}
    return {row["hsd_id"]: by_id.get(row["hsd_id"], {}) for row in candidate_rows}


def harvest_one(row: Dict[str, str], article: Dict[str, Any]) -> List[Dict[str, str]]:
    text = _record_text(article).lower()
    hsd_id = row.get("hsd_id", "")
    platform = row.get("platform", "")
    found: List[Dict[str, str]] = []

    patterns = [
        ("FIX_VALIDATION", r"fix validated|verified with latest|issue not seen|workaround verified|implemented.await_user_verify"),
        ("REPRODUCTION", r"reproduced|reproducible|repro|passing\s*(?:vs|versus)\s*failing|failing\s*vs\s*passing"),
        ("PASS_FAIL_EXPERIMENT", r"a/b|a-b|passing.*failing|fail(?:ed)?\s+.*pass(?:ed)?|before.*after"),
        ("ENGINEER_AGREEMENT", r"agreed|agreement|confirmed by|reviewed by|team consensus|multiple engineers"),
        ("RELATED_VALIDATED_CASE", r"related|duplicate|transferred|child-parent"),
    ]
    for evidence_type, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 100)
            excerpt = re.sub(r"\s+", " ", text[start:match.end() + 180]).strip()
            found.append({
                "hsd_id": hsd_id, "platform": platform,
                "evidence_type": evidence_type,
                "evidence_source": "HSD export article/comments/history/links",
                "evidence_text": excerpt[:500],
                "confidence": "0.70" if evidence_type in INDEPENDENT_TYPES else "0.50",
                "validation_level": "LEVEL_4_FIX_VALIDATED" if evidence_type == "FIX_VALIDATION" else "LEVEL_3_REPRODUCED" if evidence_type in {"REPRODUCTION", "PASS_FAIL_EXPERIMENT"} else "UNVALIDATED",
                "gold_eligible": "Yes" if evidence_type in INDEPENDENT_TYPES else "No",
                "platinum_eligible": "Yes" if evidence_type == "FIX_VALIDATION" else "No",
            })
    return found


def harvest(candidate_path: Path, export_path: Path) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    candidates = _rows(candidate_path)
    articles = _candidate_records(export_path, candidates)
    evidence_rows: List[Dict[str, str]] = []
    promotion_rows: List[Dict[str, str]] = []
    for row in candidates:
        if row.get("approval_status") == "REJECTED":
            continue
        evidence = harvest_one(row, articles.get(row.get("hsd_id", ""), {}))
        evidence_rows.extend(evidence)
        types = {item["evidence_type"] for item in evidence}
        independent = types.intersection(INDEPENDENT_TYPES)
        ambiguity = "DECODER_AMBIGUITY" in (row.get("rejection_reasons") or "")
        conflict = "OWNERSHIP_CONTRADICTION" in (row.get("rejection_reasons") or "")
        owner_known = bool(row.get("owner", "").strip()) and row.get("platform") != "UNKNOWN"
        structured_rca = bool(row.get("root_cause_summary", "").strip())
        gold = bool(structured_rca and independent and owner_known and not ambiguity and not conflict)
        platinum = "FIX_VALIDATION" in types and gold
        reviewer_needed = ambiguity or conflict or not owner_known
        if platinum:
            tier = "PLATINUM"
        elif gold:
            tier = "GOLD"
        else:
            tier = row.get("suggested_tier", "BRONZE")
        missing = []
        if not independent:
            missing.append("independent validation")
        if not owner_known:
            missing.append("known platform/owner")
        if ambiguity:
            missing.append("decoder ambiguity resolution")
        if conflict:
            missing.append("ownership conflict resolution")
        promotion_rows.append({
            "hsd_id": row.get("hsd_id", ""), "platform": row.get("platform", ""),
            "current_tier": row.get("suggested_tier", ""), "recommended_tier": tier,
            "evidence_found": ";".join(sorted(types)), "evidence_missing": ";".join(missing),
            "confidence": "0.70" if gold else "0.30", "gold_eligible": "Yes" if gold else "No",
            "platinum_eligible": "Yes" if platinum else "No", "owner": row.get("owner", ""),
            "reviewer_needed": "Yes" if reviewer_needed else "No",
            "recommendation": "REVIEW" if reviewer_needed else "RECOMMEND_APPROVAL" if gold else "REJECT",
            "why": "Structured RCA plus independent evidence harvested" if gold else "; ".join(missing) or "Evidence signal requires human validation",
        })
    return evidence_rows, promotion_rows


def write_csv(path: Path, fields: List[str], rows: Iterable[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest Bronze candidate validation evidence")
    parser.add_argument("--candidates", type=Path, default=ROOT / "golden_candidates.csv")
    parser.add_argument("--export", type=Path, default=ROOT / "hsdes_candidates.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    evidence, promotion = harvest(args.candidates, args.export)
    write_csv(args.output_dir / "validation_evidence.csv", EVIDENCE_FIELDS, evidence)
    write_csv(args.output_dir / "promotion_candidates.csv", PROMOTION_FIELDS, promotion)
    gold = [row for row in promotion if row["gold_eligible"] == "Yes"]
    platinum = [row for row in promotion if row["platinum_eligible"] == "Yes"]
    assignments = []
    for row in promotion:
        if row["reviewer_needed"] == "Yes":
            assignments.append({"hsd_id": row["hsd_id"], "platform": row["platform"],
                                "domain": "Unknown", "risk": row["evidence_missing"],
                                "assigned_reviewer": DOMAIN_REVIEWERS.get("Other", "Kandeepan"),
                                "reason": row["why"], "status": "PENDING"})
    write_csv(args.output_dir / "gold_recommended.csv", PROMOTION_FIELDS, gold)
    write_csv(args.output_dir / "platinum_recommended.csv", PROMOTION_FIELDS, platinum)
    write_csv(args.output_dir / "review_assignment.csv", ASSIGNMENT_FIELDS, assignments)
    print(f"Candidates harvested: {len(promotion)}")
    print(f"Evidence rows: {len(evidence)}")
    print(f"Gold recommendations: {len(gold)}")
    print(f"Platinum recommendations: {len(platinum)}")
    print(f"Review assignments: {len(assignments)}")
    print("No Golden Cases were created; approval remains required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
