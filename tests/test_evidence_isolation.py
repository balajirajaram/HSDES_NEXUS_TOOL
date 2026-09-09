#!/usr/bin/env python3
"""Regression tests: evidence-source isolation (Part 14).

Locks in the epistemology rule — a comment-thread claim is a Tier-3 human
observation and must never (a) set CONFIRMED, (b) raise confidence, (c) pass the
auto-post gate, or (d) become eligible KB root-cause knowledge. Deterministic;
no network. Run: python -m unittest tests.test_evidence_isolation
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import analyzer as A  # noqa: E402


def _decoded(bank="6", unit="CCF", mcacod="0x0402", mscod="0x4A00",
             status="0xBA00000C4A000402", flags=None, ierr_source="None"):
    return {
        "evidence": {
            "mc_status": {"status": status, "mscod": mscod, "mcacod": mcacod,
                          "bank": bank, "bank_unit": unit,
                          "decode": "SAD non-corrupting error other", "recovery": "reset"},
            "sockets": ["1"],
            "status_flags": flags or {"VAL": True, "UC": True, "EN": True,
                                      "MISCV": True, "PCC": True},
        },
        "ierr_table": [{"socket": "1", "type": "IERR", "source_unit": ierr_source,
                        "note": "No error logged" if ierr_source in ("None", "") else ""}],
        "boot_flow": {"reached_os": True},
    }


def _render(decoded, cf=None):
    lf = {"decoded": decoded, "lines_scanned": 50000,
          "signatures": [{"label": "IERR", "count": 19, "severity": "fatal"}]}
    target = {"id": "16031734105", "title": "[GNR] Kernel panic IERR CPU2",
              "full_text": "crashdump attached"}
    recall = {"confidence": "Low", "matches": []}
    L = []
    audit = A._audit_root_cause_evidence(target, lf, recall, [])
    A._render_causality_sections(L, target, lf, recall, cf, audit)
    md = "\n".join(L)
    return md, {"report_markdown": md, "log_findings": lf, "target": target,
                "comment_findings": cf}


class TestEvidenceIsolation(unittest.TestCase):

    def _verdict(self, md):
        sec = A._md_section(md, "## Engineer Verdict Audit")
        return A._md_line(sec, "Verdict type")

    def _confidence(self, md):
        sec = A._md_section(md, "## Root-Cause Confidence")
        m = re.search(r"(\d{1,3})\s*%", sec)
        return int(m.group(1)) if m else 0

    def test_1_comment_only_root_cause_never_confirmed(self):
        cf = {"root_cause": "Cascaded failures due to a VR issue led to IERR and kernel panic",
              "root_cause_author": "sunilc"}
        md, result = _render(_decoded(), cf)
        self.assertNotIn("CONFIRMED", self._verdict(md).upper())
        gate = A._post_gate(result)
        self.assertFalse(gate["allow"], "comment-only claim must not pass the gate")

    def test_8_uc_pcc_never_corrected(self):
        md, _ = _render(_decoded(flags={"VAL": True, "UC": True, "PCC": True, "EN": True}))
        own = A._md_section(md, "## MCA Ownership Analysis")
        self.assertNotIn("corrected", own.lower().replace("uncorrected", ""),
                         "UC/PCC status must never be labeled 'corrected'")

    def test_12_comment_does_not_change_machine_verdict_or_confidence(self):
        decoded = _decoded()
        md_no, _ = _render(decoded, cf=None)
        md_yes, _ = _render(decoded, cf={"root_cause": "VR issue caused the cascade",
                                         "root_cause_author": "sunilc"})
        self.assertEqual(self._verdict(md_no), self._verdict(md_yes),
                         "a comment must not change the machine verdict")
        self.assertEqual(self._confidence(md_no), self._confidence(md_yes),
                         "a comment must not change machine confidence")

    def test_kb_comment_only_is_unvalidated_and_ineligible(self):
        # MCA decoded but ownership not register-proven + a comment claim -> unvalidated.
        lf = {"decoded": _decoded(), "lines_scanned": 50000}
        state, eligible = A._kb_validation_state(lf, {"root_cause": "VR issue"})
        self.assertEqual(state, "UNVALIDATED_HYPOTHESIS")
        self.assertFalse(eligible)
        # Register-proven owner (real IERR source) -> machine-supported, still ineligible.
        lf2 = {"decoded": _decoded(ierr_source="CHA0"), "lines_scanned": 50000}
        state_m, elig_m = A._kb_validation_state(lf2, {"root_cause": "VR issue"})
        self.assertEqual(state_m, "MACHINE_SUPPORTED")
        self.assertFalse(elig_m)
        # No machine evidence at all -> observation only, ineligible.
        state2, elig2 = A._kb_validation_state({"lines_scanned": 0}, {"root_cause": "VR issue"})
        self.assertEqual(state2, "OBSERVATION_ONLY")
        self.assertFalse(elig2)

    def test_extract_findings_comment_only_not_confirmed(self):
        target = {"status": "open", "full_text": "", "raw": {}}
        cf = {"root_cause": "VR issue", "workaround": "swap the board"}
        f = A._extract_findings(target, cf)
        self.assertEqual(f["confidence"], "hypothesis",
                         "an open ticket with only a comment claim is not 'confirmed'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
