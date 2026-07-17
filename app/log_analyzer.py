"""Log analysis model — scans attached logs (serial / BIOS / PythonSV / BMC SEL /
OS kernel / RPT) for known server-platform failure signatures and returns
structured findings that ground the triage report.

Pattern-based and deterministic (no LLM). Extend `_SIGNATURES` freely.
"""

import re
from typing import Any, Dict, List, Optional

# (label, severity, domain, compiled pattern)
_SIGNATURES: List[tuple] = [
    ("MCE / Machine Check (MCA)", "fatal", "RAS / MCA",
     re.compile(r"machine[\s_-]?check|\bMCE\b|MC[i0-9]?_STATUS|IA32_MC|mcelog|hardware error", re.I)),
    ("CATERR / IERR / MCERR", "fatal", "RAS / MCA",
     re.compile(r"\bCATERR\b|\bIERR\b|\bMCERR\b|\bMSMI\b|THERMTRIP", re.I)),
    ("Kernel panic / call trace / hung task", "fatal", "OS / driver",
     re.compile(r"kernel panic|call trace|\bBUG:\b|soft lockup|hung task|\bRIP:\b|oops", re.I)),
    ("NMI / watchdog", "high", "BIOS / firmware / boot-hang",
     re.compile(r"\bNMI\b|watchdog|WDT expired|hang", re.I)),
    ("BMC / SEL / IPMI event", "high", "BIOS / firmware / boot-hang",
     re.compile(r"\bSEL\b|\bBMC\b|IPMI|sensor.*assert|BMC down", re.I)),
    ("WHEA (Windows hardware error)", "fatal", "RAS / MCA",
     re.compile(r"\bWHEA\b|Event\s*ID?\s*1[78]\b", re.I)),
    ("UPI / KTI link error", "high", "UPI / coherency",
     re.compile(r"\bUPI\b|\bKTI\b|ktilk|link.*(crc|retrain|down)", re.I)),
    ("DDR / memory training / ECC", "high", "Memory",
     re.compile(r"\bMRC\b|training fail|\bDIMM\b|correctable|uncorrectable|\bECC\b|patrol scrub", re.I)),
    ("PCIe / CXL AER / LTSSM", "high", "IO / PCIe / CXL",
     re.compile(r"\bAER\b|LTSSM|link down|PCIe.*error|\bCXL\b", re.I)),
    ("BIOS ASSERT / EFI_ERROR", "high", "BIOS / firmware / boot-hang",
     re.compile(r"ASSERT|assertion failed|EFI_ERROR|DXE|PEI", re.I)),
    ("Timeout", "medium", "BIOS / firmware / boot-hang",
     re.compile(r"\btimed?\s*out\b|timeout", re.I)),
    ("Reset / reboot", "medium", "BIOS / firmware / boot-hang",
     re.compile(r"warm reset|cold reset|unexpected reboot|surprise reset", re.I)),
]

# POST / progress checkpoint like "POST 0xB4" or "Progress Code: 0x..."
_POST_RE = re.compile(r"(post|checkpoint|progress code)[^\n]{0,40}(0x[0-9A-Fa-f]{2,4})", re.I)
_SEV_RANK = {"fatal": 3, "high": 2, "medium": 1}


def analyze_log(text: str, max_examples: int = 1) -> Dict[str, Any]:
    if not text or not text.strip():
        return {"lines_scanned": 0, "signatures": [], "domains": [],
                "last_checkpoint": "", "summary": "empty log"}

    lines = text.splitlines()
    sig_hits: Dict[str, Dict[str, Any]] = {}
    for ln in lines:
        for label, sev, domain, pat in _SIGNATURES:
            if pat.search(ln):
                h = sig_hits.setdefault(label, {
                    "label": label, "severity": sev, "domain": domain,
                    "count": 0, "examples": []})
                h["count"] += 1
                if len(h["examples"]) < max_examples:
                    h["examples"].append(ln.strip()[:200])

    # last POST/progress checkpoint (often the point just before a hang)
    last_ckpt = ""
    for m in _POST_RE.finditer(text):
        last_ckpt = m.group(0).strip()[:120]

    signatures = sorted(
        sig_hits.values(),
        key=lambda s: (_SEV_RANK.get(s["severity"], 0), s["count"]),
        reverse=True,
    )
    domains: List[str] = []
    for s in signatures:
        if s["domain"] not in domains:
            domains.append(s["domain"])

    if signatures:
        top = signatures[0]
        summary = (f"{len(signatures)} signature type(s); strongest: "
                   f"{top['label']} ({top['severity']}, x{top['count']}).")
    else:
        summary = "No known failure signatures matched."

    return {
        "lines_scanned": len(lines),
        "signatures": signatures,
        "domains": domains,
        "last_checkpoint": last_ckpt,
        "summary": summary,
    }


def read_log(path: str, max_bytes: int = 5_000_000) -> Optional[str]:
    """Read a log file (plain text; truncates very large files)."""
    try:
        import gzip
        opener = gzip.open if path.lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(max_bytes)
        except Exception:
            return None
