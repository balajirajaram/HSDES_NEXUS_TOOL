import copy
import unittest

from app.analyzer import _post_gate
from app.repro_recommender import recommend_repro_vectors
from app.repro_signature_extractor import extract_stress_vector
from tools.build_stress_vector_library import build_library


def _case(hsd_id, platform, owner, mechanism, title, level="LEVEL_4_FIX_VALIDATED"):
    return {
        "hsd_id": hsd_id,
        "platform": platform,
        "expected_owner": owner,
        "failure_mechanism": mechanism,
        "title": title,
        "validation_level": level,
        "evidence": {"validated_by": "test", "validation_source": "test"},
    }


class TestReproVectors(unittest.TestCase):
    def test_exact_match_returns_registry_workload(self):
        library = build_library([_case("1", "DMR", "Core/FE/BPU", "3-strike",
                                      "sandstone branch_tree_icache_focused")])
        result = recommend_repro_vectors("Core/FE/BPU", "3-strike", "DMR", library=library)
        self.assertEqual(result[0]["match_type"], "EXACT")
        self.assertEqual(result[0]["tool_name"], "sandstone")
        self.assertEqual(result[0]["subtest_or_mode"], "branch_tree_icache_focused")
        self.assertEqual(result[0]["hit_count"], 1)

    def test_cross_platform_analog_is_ranked_lower(self):
        library = build_library([
            _case("1", "DMR", "Core/FE/BPU", "3-strike", "sandstone branch_tree_icache_focused"),
            _case("2", "GNR", "Core/FE/BPU", "3-strike", "hammer-unified combo"),
        ])
        result = recommend_repro_vectors("Core/FE/BPU", "3-strike", "DMR", library=library)
        self.assertEqual(result[0]["match_type"], "EXACT")
        self.assertEqual(result[0]["tool_name"], "sandstone")
        self.assertEqual(result[1]["match_type"], "CROSS_PLATFORM_ANALOG")
        self.assertEqual(result[1]["tool_name"], "hammer-unified")

    def test_no_match_is_empty_not_a_guess(self):
        library = build_library([_case("1", "DMR", "Core/FE/BPU", "3-strike", "sandstone combo")])
        self.assertEqual(recommend_repro_vectors("UPI", "parity", "SPR", library=library), [])

    def test_new_registry_tool_is_learned_during_rebuild(self):
        case = _case("3", "DMR", "Core/FE/BPU", "3-strike", "burnin rf-cold G3 cycling")
        vector = extract_stress_vector(case)
        self.assertEqual(vector["tool_name"], "burnin")
        library = build_library([case])
        result = recommend_repro_vectors("Core/FE/BPU", "3-strike", "DMR", library=library)
        self.assertEqual(result[0]["tool_name"], "burnin")
        self.assertEqual(result[0]["trigger_context"], ["G3_cycle"])

    def test_vector_section_cannot_change_gate(self):
        result = {"report_markdown": "## Engineer Verdict Audit\n- **Verdict type:** WORKING HYPOTHESIS\n"
                                      "## Ownership Evidence Ladder\n- **Ownership Confidence:** INSUFFICIENT\n"
                                      "## Root-Cause Confidence\n- **Confidence:** 20%\n"}
        before = _post_gate(copy.deepcopy(result))
        result["report_markdown"] += "\n## Suggested Reproduction Vectors\nHistorical reference only"
        self.assertEqual(before, _post_gate(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
