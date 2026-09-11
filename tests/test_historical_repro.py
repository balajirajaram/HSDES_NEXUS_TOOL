import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.analyzer import _post_gate
from app.historical_repro import match_historical_repro, render_section


class TestHistoricalRepro(unittest.TestCase):
    def setUp(self):
        self.cases = [
            {
                "hsd_id": "1001", "platform": "GNR", "expected_owner": "CHA",
                "expected_mcacod": "0x0402", "expected_mscod": "0x4A00", "expected_bank": "4",
                "validation_level": "LEVEL_4_FIX_VALIDATED", "title": "sandstone branch_tree_icache_focused",
                "notes": "TOR_TIMEOUT reproduced", "bugeco_id": "13000000001",
                "evidence": {"validated_by": "RTL", "validation_source": "Fixed in GNR B0"},
            },
            {
                "hsd_id": "1002", "platform": "GNR", "expected_owner": "CHA",
                "expected_mcacod": "0x0412", "expected_mscod": "0x25", "expected_bank": "4",
                "validation_level": "LEVEL_3_REPRODUCED", "title": "sandstone-rf-cold",
                "notes": "IERR reproduced", "evidence": {"validated_by": "RTL", "validation_source": "WIP"},
            },
        ]

    def test_exact_match_returns_workload(self):
        result = match_historical_repro({"platform": "GNR", "owner": "CHA",
                                         "mcacod": "0x0402", "mscod": "0x4A00", "bank": "4"}, self.cases)
        self.assertEqual(result["confidence"], "EXACT")
        self.assertEqual(result["suggested_repro_test"], "sandstone branch_tree_icache_focused")
        self.assertEqual(result["hsd_id"], "1001")

    def test_partial_match_same_owner_different_mcacod(self):
        result = match_historical_repro({"platform": "GNR", "owner": "CHA",
                                         "mcacod": "0x0999", "mscod": "0x01"}, self.cases)
        self.assertEqual(result["confidence"], "PARTIAL")

    def test_no_match_is_explicit(self):
        result = match_historical_repro({"platform": "SPR", "owner": "UPI",
                                         "keywords": "unrelated"}, self.cases)
        self.assertIsNone(result)
        self.assertIn("No sufficiently similar historical case found", render_section(result))

    def test_repro_section_does_not_change_gate(self):
        result = {"report_markdown": "## Engineer Verdict Audit\n- **Verdict type:** WORKING HYPOTHESIS\n"
                                      "## Ownership Evidence Ladder\n- **Ownership Confidence:** INSUFFICIENT\n"
                                      "## Root-Cause Confidence\n- **Confidence:** 20%\n"}
        before = _post_gate(copy.deepcopy(result))
        result["report_markdown"] += "\n" + render_section(None)
        after = _post_gate(result)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
