import unittest

from tools.health_monitor import compare, overall_status, render_markdown


class TestHealthMonitor(unittest.TestCase):
    def test_first_run_is_baseline(self):
        self.assertEqual(compare(None, {"modules": []}),
                         ["BASELINE RUN — no comparison available"])

    def test_pass_to_fail_is_regression(self):
        previous = {"modules": [{"module_name": "regression_suite", "status": "PASS", "details": []}]}
        current = {"modules": [{"module_name": "regression_suite", "status": "FAIL", "details": []}]}
        self.assertIn("REGRESSION", compare(previous, current)[0])

    def test_critical_safety_failure(self):
        modules = [{"module_name": "safety_invariants", "status": "FAIL", "details": []}]
        self.assertEqual(overall_status(modules, []), "CRITICAL")

    def test_zero_actionable_benchmark_is_degraded(self):
        modules = [{"module_name": "benchmark_sanity", "status": "WARN", "details": []}]
        self.assertEqual(overall_status(modules, []), "DEGRADED")

    def test_markdown_has_overall_line(self):
        report = {"timestamp": "x", "overall_status": "HEALTHY",
                  "regressions": ["BASELINE RUN — no comparison available"], "modules": []}
        self.assertTrue(render_markdown(report).startswith("# NEXUS Health Monitor"))
        self.assertIn("OVERALL: HEALTHY", render_markdown(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
