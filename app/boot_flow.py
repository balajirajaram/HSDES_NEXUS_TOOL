"""Boot / Golden-Flow stage mapper.

Adapted from the HSLE Debug Agent (``hsle-run-debugger`` skill, ``bios_flow.txt``).
Given the decoded POST codes + the combined serial/BMC log text, it identifies
which boot phases were reached and the LAST / failing phase — turning a wall of
log into a "where did boot stop" answer (SEC -> PEI -> MRC -> DXE -> BDS -> OS).

Deterministic, no LLM. Markers are the real BIOS serial-log strings and POST-code
ranges the HSLE agent greps for.
"""

import re
from typing import Any, Dict, List, Optional

# Ordered boot phases. Each: (key, label, [serial markers], [post-code prefixes]).
# A phase is "reached" if any marker string OR post-code prefix appears.
_PHASES: List[tuple] = [
    ("sec", "SEC (reset vector / early CPU)",
     [r"\bSEC\b", r"Reset Vector", r"CarInit"],
     ["0x00", "0x01", "0x02", "0x03", "0x04", "0x05", "0x06", "0x07"]),
    ("pei_premem", "PEI pre-memory (PCH/silicon policy)",
     [r"EarlyPlatformPchInit", r"BIOS ID:", r"SiliconPolicyUpdatePreMem"],
     ["0xa0", "0xa1", "0xa3", "0xa4", "0xa8", "0xa9", "0xab"]),
    ("mrc", "FSP-M / MRC (DDR memory training)",
     [r"START_MRC_RUN", r"Initialize clocks for all MemSs", r"JEDEC_DATA",
      r"IpMcMemInitComplete", r"PeiInstallPeiMemory"],
     ["0xe0", "0xe1", "0xe3", "0xe4", "0xe5", "0xe6", "0xe9", "0xeb", "0xed", "0xee",
      "0xb", "0xc", "0xd"]),
    ("pei_postmem", "Post-memory PEI (ACPI HOBs / AP bringup)",
     [r"CEDT ACPI Table", r"DXE IPL Entry", r"CpuMpPei", r"RasPeiInit"],
     ["0x51"]),
    ("dxe", "DXE (driver dispatch)",
     [r"Loading DXE CORE", r"DXE Core", r"NvmExpressDriverBindingStart",
      r"DXE_", r"PciBus", r"post enumerated bus"],
     ["0x90", "0x91", "0x92", "0x93", "0x94", "0x95", "0x96", "0x97", "0x98", "0x99"]),
    ("bds", "BDS (boot device selection)",
     [r"\[Bds\]Booting", r"Valid efi partition table", r"BdsEntry", r"Boot0\d"],
     ["0xad", "0xae"]),
    ("os_handoff", "ExitBootServices -> OS handoff",
     [r"Decompressing Linux", r"ExitBootServices", r"Booting UEFI"],
     []),
    ("os", "OS boot (kernel)",
     [r"Linux version", r"systemd\[1\]", r"login:", r"Welcome to", r"Started ",
      r"kernel:"],
     []),
]

# Failure markers that indicate WHERE it broke (not a normal stage).
_FAIL_MARKERS: List[tuple] = [
    ("IERR / CATERR (CPU internal error)", re.compile(r"\bIERR\b|\bCATERR\b|\bMCERR\b", re.I)),
    ("Machine check (MCA)", re.compile(r"machine[\s_-]?check|MCi_STATUS|mcelog", re.I)),
    ("RC fatal / BIOS assert", re.compile(r"RC_FATAL|FATAL ERROR|ASSERT", re.I)),
    ("Node / system hang", re.compile(r"\bhang\b|\bhung\b|not responding|no response", re.I)),
    ("Reset / reboot", re.compile(r"unexpected reset|surprise reset|warm reset|cold reset", re.I)),
]

_POST_RE = re.compile(r"(?:post|checkpoint|progress code|debug_port)[^\n]{0,40}?(0x[0-9A-Fa-f]{2,4})", re.I)


def analyze_boot_flow(text: str, decoded_post: Optional[List[Dict[str, Any]]] = None
                      ) -> Optional[Dict[str, Any]]:
    """Map the log to boot phases; return stage progress + the last-reached /
    failing phase. Returns None when no boot activity is recognizable."""
    if not text or not text.strip():
        return None
    lower = text  # markers are case-insensitive via re / substring below
    post_codes = [c.get("code", "").lower() for c in (decoded_post or [])]

    stages: List[Dict[str, Any]] = []
    last_reached_idx = -1
    for idx, (key, label, markers, post_prefixes) in enumerate(_PHASES):
        hit_text = ""
        for m in markers:
            mm = re.search(m, text, re.I)
            if mm:
                hit_text = mm.group(0).strip()[:48]  # real matched log text, not the regex
                break
        hit_post = None
        for pc in post_codes:
            if any(pc.startswith(p) for p in post_prefixes):
                hit_post = pc
                break
        reached = bool(hit_text or hit_post)
        stages.append({
            "key": key, "label": label, "reached": reached,
            "evidence": (hit_text or (f"POST {hit_post}" if hit_post else "")),
        })
        if reached:
            last_reached_idx = idx

    if last_reached_idx < 0:
        return None

    # Golden Flow is monotonic: reaching a later stage implies every earlier stage
    # passed, even if its specific marker wasn't captured in this log stream.
    for i in range(last_reached_idx):
        if not stages[i]["reached"]:
            stages[i]["reached"] = True
            stages[i]["implied"] = True
            if not stages[i]["evidence"]:
                stages[i]["evidence"] = "(implied — later stage reached)"

    # Failing phase = the first NOT-reached phase after the last reached one.
    failing = None
    for s in stages[last_reached_idx + 1:]:
        failing = s
        break
    last_reached = stages[last_reached_idx]

    # Failure markers present in the log (what broke).
    fired = [label for label, pat in _FAIL_MARKERS if pat.search(text)]

    # Last POST checkpoint seen anywhere in the log.
    last_ckpt = ""
    for m in _POST_RE.finditer(text):
        last_ckpt = m.group(0).strip()[:80]

    return {
        "stages": stages,
        "last_reached": last_reached,
        "failing_stage": failing,
        "failure_markers": fired,
        "last_checkpoint": last_ckpt,
        "reached_os": stages[-1]["reached"],
    }
