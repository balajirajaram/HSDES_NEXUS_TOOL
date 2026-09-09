#!/usr/bin/env python3
"""Regression tests: decoder correctness (Part 9).

Covers the central MCA fatality classifier (UC/PCC never 'corrected'), the
MCi_* register-address helper, and the first-error vs reporting-owner ownership
conflict (OWNERSHIP_EVIDENCE_CONFLICT) that must block CONFIRMED + auto-post.
Deterministic; no network. Run: python -m unittest tests.test_decoder_correctness
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import analyzer as A  # noqa: E402


class TestFatalityClassifier(unittest.TestCase):

    def test_uc_pcc_is_uncorrected_fatal_never_corrected(self):
        # HSD 16031734105 Bank 6 status.
        r = A.classify_mca_status("0xBA00000C4A000402")
        self.assertTrue(r["valid"])
        self.assertTrue(r["flags"]["UC"])
        self.assertTrue(r["flags"]["PCC"])
        self.assertTrue(r["is_uncorrected"])
        self.assertTrue(r["is_fatal"])
        self.assertFalse(r["is_corrected"])
        self.assertEqual(r["severity"], "UNCORRECTED_FATAL")

    def test_bank4_status_also_uncorrected_fatal(self):
        r = A.classify_mca_status("0xBA0000004A000402")
        self.assertTrue(r["is_fatal"])
        self.assertFalse(r["is_corrected"])

    def test_corrected_status(self):
        # VAL=1, UC=0 -> corrected.
        r = A.classify_mca_status("0x9400000000000001")
        self.assertTrue(r["valid"])
        self.assertFalse(r["flags"]["UC"])
        self.assertTrue(r["is_corrected"])
        self.assertFalse(r["is_fatal"])

    def test_invalid_status(self):
        r = A.classify_mca_status("not-a-number")
        self.assertFalse(r["valid"])
        self.assertFalse(r["is_fatal"])


class TestRegisterAddrs(unittest.TestCase):

    def test_bank6(self):
        a = A.mci_register_addrs(6)
        # 0x400 + 4*6 = 0x418
        self.assertEqual(a["MCi_CTL"], "0x418")
        self.assertEqual(a["MCi_STATUS"], "0x419")
        self.assertEqual(a["MCi_ADDR"], "0x41A")
        self.assertEqual(a["MCi_MISC"], "0x41B")

    def test_bank4(self):
        a = A.mci_register_addrs(4)
        # 0x400 + 4*4 = 0x410
        self.assertEqual(a["MCi_CTL"], "0x410")
        self.assertEqual(a["MCi_STATUS"], "0x411")
        self.assertEqual(a["MCi_ADDR"], "0x412")
        self.assertEqual(a["MCi_MISC"], "0x413")


class TestOwnershipConflict(unittest.TestCase):

    def _render(self, first_ierr_unit, bank_unit):
        decoded = {
            "evidence": {
                "mc_status": {"status": "0xBA00000C4A000402", "mscod": "0x4A00",
                              "mcacod": "0x0402", "bank": "6", "bank_unit": bank_unit,
                              "decode": "SAD non-corrupting error other"},
                "sockets": ["1"],
                "status_flags": {"VAL": True, "UC": True, "PCC": True, "EN": True},
            },
            "ierr_table": [{"socket": "1", "type": "IERR", "source_unit": first_ierr_unit,
                            "note": ""}],
            "boot_flow": {"reached_os": True},
        }
        lf = {"decoded": decoded, "lines_scanned": 50000,
              "signatures": [{"label": "IERR", "count": 19, "severity": "fatal"}]}
        target = {"id": "16031734105", "title": "[CWF] Kernel panic IERR Socket 1",
                  "full_text": "crashdump attached"}
        recall = {"confidence": "Low", "matches": []}
        L = []
        A._render_causality_sections(L, target, lf, recall, None,
                                     A._audit_root_cause_evidence(target, lf, recall, []))
        md = "\n".join(L)
        return md, {"report_markdown": md, "log_findings": lf, "target": target}

    def test_punit_vs_ccf_emits_conflict_and_blocks(self):
        md, result = self._render("PUNIT compute2", "CCF")
        self.assertIn("OWNERSHIP_EVIDENCE_CONFLICT", md)
        self.assertIn("## Contradiction Detector", md)
        verdict = A._md_line(A._md_section(md, "## Engineer Verdict Audit"), "Verdict type")
        self.assertNotIn("CONFIRMED", verdict.upper())
        self.assertFalse(A._post_gate(result)["allow"])

    def test_same_ip_no_conflict(self):
        md, _ = self._render("CHA0", "CHA")
        self.assertNotIn("OWNERSHIP_EVIDENCE_CONFLICT", md)

    def test_ownership_fatality_never_corrected(self):
        md, _ = self._render("PUNIT", "CCF")
        own = A._md_section(md, "## MCA Ownership Analysis")
        self.assertNotIn("corrected", own.lower().replace("uncorrected", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
