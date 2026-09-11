import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.analyzer as analyzer
from app.analyzer import _post_gate
from app.repro_recommender import NO_MATCH_MESSAGE, recommend_repro, render_repro_section
from tools.build_repro_index import build_repro_index


class TestGoldenReproRecommender(unittest.TestCase):
    def setUp(self):
        self.index = {
            "entries": [
                {
                    "owning_ip": "Core/FE/BPU", "failure_mechanism": "3-strike", "platform": "DMR",
                    "tool_name": "sandstone", "subtest_or_mode": "branch_tree_icache_focused",
                    "trigger_context": ["steady_state"], "hit_count": 5,
                    "evidence_tier": "LEVEL_4_FIX_VALIDATED", "source_hsd_ids": ["15019342741"],
                },
                {
                    "owning_ip": "Core/FE/BPU", "failure_mechanism": "3-strike", "platform": "GNR",
                    "tool_name": "hammer-unified", "subtest_or_mode": "chaos",
                    "trigger_context": ["warm_reset"], "hit_count": 2,
                    "evidence_tier": "LEVEL_3_REPRODUCED", "source_hsd_ids": ["2"],
                },
            ]
        }

    def test_exact_match_prefers_same_platform_workload(self):
        result = recommend_repro("Core/FE/BPU", "3-strike", "DMR", index=self.index)
        self.assertEqual(result["match_type"], "EXACT")
        self.assertEqual(result["results"][0]["subtest_or_mode"], "branch_tree_icache_focused")

    def test_cross_platform_match_is_labeled(self):
        result = recommend_repro("Core/FE/BPU", "3-strike", "SPR", index=self.index)
        self.assertEqual(result["match_type"], "CROSS_PLATFORM_ANALOG")
        self.assertEqual(result["results"][0]["match_type"], "CROSS_PLATFORM_ANALOG")

    def test_no_match_is_explicit(self):
        result = recommend_repro("UPI", "never-seen", "COR", index=self.index)
        self.assertEqual(result["match_type"], "NO_MATCH")
        self.assertEqual(result["message"], NO_MATCH_MESSAGE)
        self.assertIn(NO_MATCH_MESSAGE, render_repro_section(result))

    def test_repro_section_does_not_change_gate(self):
        result = {"report_markdown": "## Engineer Verdict Audit\n- **Verdict type:** WORKING HYPOTHESIS\n"
                                      "## Ownership Evidence Ladder\n- **Ownership Confidence:** INSUFFICIENT\n"
                                      "## Root-Cause Confidence\n- **Confidence:** 20%\n"}
        before = _post_gate(dict(result))
        verdict_before = analyzer._md_line(
            analyzer._md_section(result["report_markdown"], "## Engineer Verdict Audit"),
            "Verdict type",
        )
        confidence_before = analyzer._md_line(
            analyzer._md_section(result["report_markdown"], "## Root-Cause Confidence"),
            "Confidence",
        )
        result["report_markdown"] += "\n" + render_repro_section(
            recommend_repro("Core/FE/BPU", "3-strike", "DMR", index=self.index))
        after = _post_gate(result)
        verdict_after = analyzer._md_line(
            analyzer._md_section(result["report_markdown"], "## Engineer Verdict Audit"),
            "Verdict type",
        )
        confidence_after = analyzer._md_line(
            analyzer._md_section(result["report_markdown"], "## Root-Cause Confidence"),
            "Confidence",
        )
        self.assertEqual(before, after)
        self.assertEqual(verdict_before, verdict_after)
        self.assertEqual(confidence_before, confidence_after)

    def test_unvalidated_index_row_is_not_recommended(self):
        index = {"entries": [{
            "owning_ip": "Core", "failure_mechanism": "3-strike", "platform": "DMR",
            "recommendations": [{
                "tool_name": "unclassified", "subtest_or_mode": "unknown",
                "trigger_context": ["unknown"], "hit_count": 4,
                "evidence_tier": "UNKNOWN", "source_hsd_ids": ["x"],
            }],
        }]}
        result = recommend_repro("Core", "3-strike", "DMR", index=index)
        self.assertEqual(result["match_type"], "NO_MATCH")

    def test_repro_index_aggregates_vectors_and_discovers_multiple_tools(self):
        cases = [
            {"hsd_id": "1", "platform": "DMR", "expected_owner": "Core/FE/BPU",
             "failure_mechanism": "3-strike", "validation_level": "LEVEL_3_REPRODUCED",
             "evidence": {"validated_by": "test", "validation_source": "test"},
             "title": "sandstone branch_tree_icache_focused"},
            {"hsd_id": "2", "platform": "DMR", "expected_owner": "Core/FE/BPU",
             "failure_mechanism": "3-strike", "validation_level": "LEVEL_4_FIX_VALIDATED",
             "evidence": {"validated_by": "test", "validation_source": "test"},
             "title": "sandstone branch_tree_icache_focused"},
            {"hsd_id": "3", "platform": "GNR", "expected_owner": "Core/FE/BPU",
             "failure_mechanism": "3-strike", "validation_level": "LEVEL_3_REPRODUCED",
             "evidence": {"validated_by": "test", "validation_source": "test"},
             "title": "hammer-unified chaos"},
        ]
        index = build_repro_index(cases)
        self.assertEqual(index["case_count"], 3)
        self.assertGreaterEqual(index["tool_name_count"], 2)
        dmr = next(entry for entry in index["entries"]
                   if entry["platform"] == "DMR")
        vector = dmr["recommendations"][0]
        self.assertEqual(vector["hit_count"], 2)
        self.assertEqual(vector["evidence_tier"], "LEVEL_4_FIX_VALIDATED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
