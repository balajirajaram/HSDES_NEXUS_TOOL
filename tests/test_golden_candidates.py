"""Candidate Golden Case workflow tests."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_golden_candidates import (build_candidates, reduce_review_pool,
                                           write_candidates, write_review_queues)  # noqa: E402
from tools.blind_compare_cases import compare  # noqa: E402
from tools.promote_golden_cases import promote  # noqa: E402


class TestGoldenCandidates(unittest.TestCase):
    def test_open_case_is_rejected(self):
        rows = build_candidates([{
            "id": 16030000001,
            "title": "[CWF] UPI MCERR",
            "status": "open",
            "owner": "engineer",
        }])
        self.assertEqual(rows[0]["suggested_tier"], "REJECT")
        self.assertEqual(rows[0]["human_approval"], "PENDING")

    def test_comment_only_rca_cannot_be_gold(self):
        rows = build_candidates([{
            "id": 16030000002,
            "title": "[GNR] MCA root cause",
            "status": "complete",
            "owner": "engineer",
            "comment_count": 2,
            "comments": [{"text": "Root cause is UPI"}],
            "description": "MCA log attached",
        }])
        self.assertEqual(rows[0]["suggested_tier"], "SILVER")
        self.assertEqual(rows[0]["validation_evidence"], "Root Cause Comment Only")

    def test_fix_validated_candidate_is_pending_platinum(self):
        rows = build_candidates([{
            "id": 16030000003,
            "title": "[SRF] BIOS boot failure MCERR",
            "status": "verified",
            "owner": "engineer",
            "root_cause": "PUNIT firmware sequencing",
            "fix_validated": True,
            "attachments": ["crashdump.json"],
            "mcacod": "0x402",
            "first_error": "PUNIT",
        }])
        self.assertEqual(rows[0]["suggested_tier"], "PLATINUM")
        self.assertEqual(rows[0]["human_approval"], "PENDING")
        self.assertEqual(rows[0]["platform"], "SRF")

    def test_writer_creates_csv_only(self):
        rows = build_candidates([])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "golden_candidates.csv"
            write_candidates(rows, output)
            with output.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 0)
            self.assertFalse((Path(tmp) / "golden_cases").exists())

    def test_queues_and_thresholds_are_deterministic(self):
        rows = build_candidates([{
            "id": 16030000004, "title": "[GNR] MCA fix reproduced",
            "status": "verified", "owner": "PUNIT", "root_cause": "sequencing",
            "fix_validated": True, "attachments": ["dump"], "mcacod": "0x402",
            "first_error": "PUNIT",
        }])
        self.assertEqual(rows[0]["approval_status"], "PREQUALIFIED")
        self.assertEqual(rows[0]["promote_eligible"], "YES")
        with tempfile.TemporaryDirectory() as tmp:
            write_review_queues(rows, Path(tmp) / "candidates.csv")
            self.assertTrue((Path(tmp) / "golden_review" / "prequalified.csv").exists())

    def test_unapproved_candidate_cannot_promote(self):
        row = {
            "hsd_id": "16030000005", "platform": "GNR", "domain": "MCA",
            "status": "verified", "owner": "PUNIT", "root_cause_summary": "x",
            "evidence_score": "90", "rejection_reasons": "", "approval_status": "PREQUALIFIED",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root / "candidates.csv").open("w", newline="", encoding="utf-8") as h:
                writer = csv.DictWriter(h, fieldnames=row.keys())
                writer.writeheader(); writer.writerow(row)
            with (root / "decisions.csv").open("w", newline="", encoding="utf-8") as h:
                writer = csv.DictWriter(h, fieldnames=["hsd_id", "decision"])
                writer.writeheader(); writer.writerow({"hsd_id": row["hsd_id"], "decision": "REJECT"})
            self.assertEqual(promote(root / "decisions.csv", root / "candidates.csv", root / "golden"), [])

    def test_blind_comparison_detects_machine_influence(self):
        base = {"owning_ip": "PUNIT", "confidence": 60, "verdict": "WORKING HYPOTHESIS"}
        payload = {"A": base, "B": dict(base), "C": {**base, "confidence": 75}, "D": dict(base)}
        result = compare(payload)
        self.assertFalse(result["machine_isolation_pass"])
        self.assertEqual(result["differences"][0]["run"], "C")

    def test_review_pool_applies_platform_quotas(self):
        records = []
        for platform, count in (("GNR", 12), ("SRF", 12), ("DMR", 7), ("COR", 7)):
            for index in range(count):
                records.append({
                    "id": f"{platform}{index}", "title": f"[{platform}] MCA fix",
                    "status": "verified", "owner": "PUNIT", "root_cause": "validated",
                    "fix_validated": True, "attachments": ["dump"], "mcacod": "0x402",
                })
        rows = reduce_review_pool(build_candidates(records))
        counts = {}
        for row in rows:
            counts[row["platform"]] = counts.get(row["platform"], 0) + 1
        self.assertEqual(counts, {"GNR": 10, "SRF": 10, "DMR": 5, "COR": 5})


if __name__ == "__main__":
    unittest.main(verbosity=2)
