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
     re.compile(r"machine[\s_-]?check|MC[i0-9]_STATUS|IA32_MC[0-9]|mcelog|hardware error", re.I)),
    ("CATERR / IERR / MCERR", "fatal", "RAS / MCA",
     re.compile(r"\bCATERR\b|\bIERR\b|\bMCERR\b|\bMSMI\b|THERMTRIP", re.I)),
    ("Kernel panic / call trace / hung task", "fatal", "OS / driver",
     re.compile(r"kernel panic|call trace|kernel BUG:|\bBUG:\s|soft lockup|hung task|\bOops:", re.I)),
    ("NMI / watchdog", "high", "BIOS / firmware / boot-hang",
     re.compile(r"\bNMI\b|watchdog|WDT expired|\bhang\b|hung", re.I)),
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

# ---- MCA (Machine Check) status decode ----
# Matches MCi_STATUS / MC status / MCACOD hex values in logs.
_MCI_RE = re.compile(
    r"(?:MCi?_?STATUS|MC[ _]?status|MCA?_?STATUS)\W{0,8}(0x[0-9A-Fa-f]{8,16})", re.I)
# MCi_STATUS architectural status bits (Intel SDM Vol.3).
_MCI_BITS = [
    (63, "VAL", "valid"), (62, "OVER", "overflow"), (61, "UC", "uncorrected"),
    (60, "EN", "enabled"), (59, "MISCV", "misc-valid"), (58, "ADDRV", "addr-valid"),
    (57, "PCC", "processor-context-corrupt"), (56, "S", "signalled"),
    (55, "AR", "action-required"),
]


def decode_mca(text: str) -> List[Dict[str, Any]]:
    """Decode MCi_STATUS values found in the log into human-readable fields:
    the architectural status bits, MCACOD (bits 15:0) and MSCOD (bits 31:16)."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for m in _MCI_RE.finditer(text):
        raw = m.group(1)
        try:
            val = int(raw, 16)
        except ValueError:
            continue
        if val in seen:
            continue
        seen.add(val)
        flags = [name for bit, name, _desc in _MCI_BITS if (val >> bit) & 1]
        mcacod = val & 0xFFFF
        out.append({
            "status": hex(val),
            "flags": flags,
            "mcacod": hex(mcacod),
            "mcacod_text": decode_mcacod(mcacod),
            "mscod": hex((val >> 16) & 0xFFFF),
            "severity": "fatal" if "UC" in flags or "PCC" in flags else "corrected",
        })
    return out[:5]


def decode_mcacod(v: int) -> str:
    """Best-effort MCACOD (bits 15:0) classification per Intel SDM Vol.3B §16.9.
    Model-specific (MSCOD) details still require the IP's MCA spec."""
    v &= 0xFFFF
    simple = {
        0x0000: "No error", 0x0001: "Unclassified",
        0x0002: "Microcode ROM parity error", 0x0003: "External error",
        0x0004: "FRC error", 0x0005: "Internal parity error",
        0x0006: "SMM handler code access violation", 0x0400: "Internal timer error",
    }
    if v in simple:
        return simple[v]
    if 0x0401 <= v <= 0x04FF:
        return "Internal unclassified error"
    _LL = ["L0", "L1", "L2", "LG"]
    _TT = ["Instruction", "Data", "Generic", "?"]
    if (v & 0xFFFC) == 0x000C:
        return f"Generic cache hierarchy error (level {_LL[v & 0x3]})"
    if (v & 0xFFF0) == 0x0010:
        return f"TLB error ({_TT[(v >> 2) & 0x3]}, level {_LL[v & 0x3]})"
    if (v & 0xFF00) == 0x0100:
        return f"Cache/memory hierarchy error ({_TT[(v >> 2) & 0x3]}, level {_LL[v & 0x3]})"
    if (v & 0xF800) == 0x0800:
        return "Bus / interconnect error (e.g. UPI/QPI, IIO) — see MSCOD/IP MCA spec"
    if (v & 0xFF80) == 0x0080:
        return "Memory controller error (channel/rank in low bits)"
    return "compound/vendor-specific code — see SDM / IP MCA spec"


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
        "mca_decode": decode_mca(text),
        "timeline": build_timeline(text),
        "summary": summary,
    }


# ---- Sequence-of-events timeline ----
_TS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?"   # 2026-06-30 12:21:31
    r"|\d{2}:\d{2}:\d{2}(?:\.\d+)?"                          # 12:21:31
    r"|\[\s*\d+\.\d{3,6}\s*\])")                             # [ 12.345678]

# ordered by how "late" in a failure they usually occur
_EVENT_PATS: List[tuple] = [
    ("POST / checkpoint", "progress",
     re.compile(r"(checkpoint|progress code|\bPOST\b)\D{0,20}0x[0-9A-Fa-f]{2,4}", re.I)),
    ("UPI / link error", "error",
     re.compile(r"IpWrError|\bUPI\b.*(error|crc|retrain|degrad)|\bKTI\b.*error", re.I)),
    ("Memory CE/UE / poison", "error",
     re.compile(r"poison|uncorrectable|correctable error|\bEDAC\b|MLC|DCU", re.I)),
    ("MCE / Machine Check", "fatal",
     re.compile(r"machine check|MCi?_?STATUS\s*[:=]|mcelog|hardware error", re.I)),
    ("CATERR / IERR", "fatal",
     re.compile(r"\bCATERR\b|\bIERR\b|\bMCERR\b", re.I)),
    ("Kernel panic", "fatal",
     re.compile(r"kernel panic|not syncing|Fatal .*machine check|call trace|soft lockup", re.I)),
    ("Hang / reset / BMC-down", "fatal",
     re.compile(r"\bhung\b|\bhang\b|unexpected reset|surprise reset|BMC down", re.I)),
]


def build_timeline(text: str, max_events: int = 15) -> List[Dict[str, Any]]:
    """Extract significant events in file order (= chronological) so the report
    can show the SEQUENCE of what happened and where the failure occurred."""
    events: List[Dict[str, Any]] = []
    for idx, line in enumerate(text.splitlines()):
        s = line.strip()
        # skip our own attachment markers and build-artifact/debug-path noise
        if s.startswith("###") or "PDB =" in s or ".pdb" in s.lower() or "\\Build\\" in s:
            continue
        for label, sev, pat in _EVENT_PATS:
            if pat.search(line):
                ts = _TS_RE.search(line)
                events.append({
                    "idx": idx, "ts": ts.group(0).strip() if ts else "",
                    "label": label, "severity": sev,
                    "text": s[:160],
                })
                break
    # compress runs of the same event type into one row with a count
    compressed: List[Dict[str, Any]] = []
    for e in events:
        if compressed and compressed[-1]["label"] == e["label"]:
            compressed[-1]["count"] += 1
            continue
        e["count"] = 1
        compressed.append(e)
    # mark the failure point = first fatal-severity event
    for e in compressed:
        if e["severity"] == "fatal":
            e["failure_point"] = True
            break
    return compressed[:max_events]


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
