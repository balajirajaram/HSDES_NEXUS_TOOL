#!/usr/bin/env python3
"""
MCA Decoder - Parse MCA status values and decode MCACOD/MSCOD.

Uses DMR MCA customer documentation to map bank-specific MCA codes to
human-readable decode, description, and recommended action.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Add shared utilities to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from decoder_utils import load_json_database, normalize_text, parse_hex_value


STATUS_PATTERNS = [
    re.compile(r"(?i)(?:MCi?_STATUS|MCA_STATUS|MC_STATUS)\s*[:=]\s*(0x[0-9A-Fa-f]{8,16})"),
    re.compile(r"(?i)STATUS\s*[:=]\s*(0x[0-9A-Fa-f]{8,16})"),
    re.compile(r"(?i)MCi?_STATUS\[(0x[0-9A-Fa-f]{8,16})\]"),
    # PythonSV format: "Status (F2000000E1010400H)" — hex with optional H suffix in parens
    re.compile(r"(?i)\bStatus\s*\(([0-9A-Fa-f]{8,16})H?\)"),
    # BIOS RAS format: "[CpuRas]MC status 0xHEX, class FATAL"
    re.compile(r"(?i)\[CpuRas\]MC\s+status\s+(0x[0-9A-Fa-f]{8,16})"),
]

# Linux MCE format: "Bank N: HEXVALUE" (no 0x prefix, exactly 16 hex chars)
MCE_BANK_STATUS_PATTERN = re.compile(
    r"(?i)\bBank\s+(\d+)\s*:\s*([0-9a-fA-F]{16})\b"
)

# Primary MSCOD/MCACOD patterns: standard "FIELD=0xVALUE" and table row "| FIELD | 0xVALUE |"
MSCOD_PATTERN = re.compile(r"(?i)MSCOD\s*[:=]\s*(0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)")
MCACOD_PATTERN = re.compile(r"(?i)MCACOD\s*[:=]\s*(0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)")
# PythonSV verbose: "MSCOD=THREE_STRIKE (E101H)" — symbolic name followed by hex in parens
MSCOD_VERBOSE_PATTERN = re.compile(r"(?i)MSCOD\s*=\s*\w+(?:_\w+)*\s*\(([0-9A-Fa-f]+)H?\)")
MCACOD_VERBOSE_PATTERN = re.compile(r"(?i)MCACOD\s*=\s*\w+(?:_\w+)*\s*\(([0-9A-Fa-f]+)H?\)")
# Table row format: "│ MSCOD │ 0xVALUE │" or "| MSCOD | 0xVALUE |"
MSCOD_TABLE_PATTERN = re.compile(r"(?i)[|│]\s*MSCOD\s*[|│]\s*(0x[0-9A-Fa-f]+)\s*[|│]")
MCACOD_TABLE_PATTERN = re.compile(r"(?i)[|│]\s*MCACOD\s*[|│]\s*(0x[0-9A-Fa-f]+)\s*[|│]")

BANK_PATTERN = re.compile(r"(?i)bank\s*#?\s*(\d+)")
# BIOS RAS format: "McBank = 0x4" — hex bank number from McBankErrorHandler lines
MCBANK_HEX_PATTERN = re.compile(r"(?i)McBank\s*=\s*0x([0-9A-Fa-f]+)")
# Register-name format: MC4_STATUS / MC12_ADDR / MC0_MISC → decimal bank number
MCREG_BANK_PATTERN = re.compile(r"(?i)\bMC(\d{1,2})_(?:STATUS|ADDR|MISC|CTL)\b")
# Software/tooling noise that carries hex tokens which must NEVER be read as an
# MCi_STATUS (e.g. PythonSV plugin-registration warnings expose a Plugin *ID*):
#   WARNING  Plugin "mca" is already registered (<Plugin name: mca, ... ID: 0x000073EC038A86A0>)
_NOISE_LINE_PATTERN = re.compile(
    r"(?i)(?:already\s+registered|Plugin\s+name\s*:|Plugin\s+type\s*:|McaPlugin"
    r"|object\s+at\s+0x|Traceback|register(?:ed|ing)\s+plugin)"
)
HEX_TOKEN_PATTERN = re.compile(r"\b(?:0x)?[0-9A-Fa-f]{8,16}\b")
# PythonSV CCF table section header
CCF_TABLE_HEADER_PATTERN = re.compile(r"={5,}\s*Ccf:.*mca_status\s*={5,}", re.IGNORECASE)

# Bank extraction patterns for register paths
MC_PATTERN = re.compile(r"\.mc(\d+)\.")  # Memory controller: mc0-7 → banks 19-26
BANK_COMPONENT_PATTERNS = {
    'ifu': 0, 'dcu': 1, 'dtlb': 2, 'mlc': 3,
    'ccf': 6, 'ncu': 5,
    'hamvf': 12, 'ha': 12, 'mvf': 12,
    'hsf': 13, 'sca': 14, 'ioca': 14,
    'mse': 16, 'iocache': 17, 'uxi': 18,
    'rasip': 10, 'root': 10,
}
# Pre-compiled word-boundary patterns for component names — avoids re-compiling on every
# _extract_bank call (which is invoked per log line and inside the lookback loop).
_BANK_COMPONENT_REGEXES: list[tuple[re.Pattern, int]] = [
    (re.compile(r'(?i)\b' + re.escape(comp) + r'\b'), bank_id)
    for comp, bank_id in BANK_COMPONENT_PATTERNS.items()
]

# Number of lines to scan backwards when looking for bank context (McBankErrorHandler)
_LOOKBACK_WINDOW = 5

# normalize_text is now imported from shared.decoder_utils


def parse_bank_numbers(value: str | int | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [int(value)]
    text = normalize_text(value)
    if not text:
        return []
    lowered = text.lower()
    if lowered in {"n/a", "na", "none"}:
        return []
    text = text.replace("#", "")
    parts = [part.strip() for part in re.split(r"[,/]", text) if part.strip()]
    numbers: list[int] = []
    for part in parts:
        match = re.match(r"(\d+)\s*-\s*(\d+)", part)
        if match:
            start = int(match.group(1))
            end = int(match.group(2))
            numbers.extend(range(start, end + 1))
            continue
        if part.isdigit():
            numbers.append(int(part))
    return sorted(set(numbers))


def parse_code_value(value: str | int | None) -> int | None:
    """Parse a hex code value. Delegates to shared parse_hex_value."""
    return parse_hex_value(value)


def compile_code_pattern(raw_value: str | None) -> dict:
    if raw_value is None:
        return {"type": "any"}
    text = normalize_text(raw_value)
    if not text:
        return {"type": "any"}
    normalized = text.lower()
    normalized = normalized.replace("dont", "don't")
    
    # Handle binary format with underscores (e.g., "0000_0000_1000_0000")
    if '_' in normalized and re.match(r'^[01_]+$', normalized.replace('_', '')):
        binary_str = normalized.replace('_', '')
        try:
            value = int(binary_str, 2)
            return {"type": "exact", "value": value}
        except ValueError:
            pass
    
    if "don't care" in normalized or "dont care" in normalized:
        return {"type": "any"}
    # Database entries that mean "any value is valid" for this field
    _WILDCARD_STRINGS = {
        "n/a", "na", "none",
        "internal state information",   # MLC bank MSCOD wildcard
        "see mlc mscod decoder",        # MLC bank MSCOD wildcard
    }
    if normalized in _WILDCARD_STRINGS or normalized.startswith("see "):
        return {"type": "any"}

    bit_match = re.search(r"bit\s*(\d+)", normalized)
    if bit_match:
        return {"type": "bit", "bit": int(bit_match.group(1))}

    parts = [part.strip() for part in re.split(r"[,/]", normalized) if part.strip()]
    if len(parts) > 1:
        return {
            "type": "any_of",
            "patterns": [compile_code_pattern(part) for part in parts],
        }

    if "*" in normalized:
        hex_str = normalized.replace("0x", "")
        hex_str = re.sub(r"[^0-9a-f*]", "", hex_str)
        if not hex_str:
            return {"type": "any"}
        mask = 0
        value = 0
        for char in hex_str:
            mask <<= 4
            value <<= 4
            if char == "*":
                continue
            mask |= 0xF
            value |= int(char, 16)
        return {"type": "mask", "mask": mask, "value": value}

    if re.fullmatch(r"0x[0-9a-f]+", normalized):
        return {"type": "exact", "value": int(normalized, 16)}
    if normalized.isdigit():
        return {"type": "exact", "value": int(normalized, 10)}

    hex_match = re.search(r"0x[0-9a-f]+", normalized)
    if hex_match:
        return {"type": "exact", "value": int(hex_match.group(0), 16)}

    return {"type": "unknown", "value": normalized}


def match_code(pattern: dict, value: int | None) -> bool:
    if value is None:
        return False
    pattern_type = pattern.get("type")
    if pattern_type == "any":
        return True
    if pattern_type == "exact":
        return value == pattern.get("value")
    if pattern_type == "mask":
        mask = pattern.get("mask", 0)
        expected = pattern.get("value", 0)
        return (value & mask) == (expected & mask)
    if pattern_type == "bit":
        bit = pattern.get("bit", 0)
        return (value & (1 << bit)) != 0
    if pattern_type == "any_of":
        return any(match_code(sub, value) for sub in pattern.get("patterns", []))
    return False


def format_code(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"0x{value:04X}"


def _normalize_entry_aliases(entry: dict) -> dict:
    """Add compatibility aliases for source-backed decode entries.

    CBB Punit firmware MCAs use the pcode mca_code enum from
    ~/work/pcode/source/pcode/kernel/error_handler.h for MSCOD meanings.
    Existing skill data keyed those entries on MCACOD 0x0410, while field
    extractions seen in practice can present the category as 0x0440. Match
    both values so explicit decode requests work for either encoding.
    """
    normalized = dict(entry)
    sheet = normalize_text(entry.get("sheet")) or ""
    decode = normalize_text(entry.get("decode")) or ""
    mcacod = normalize_text(entry.get("mcacod")) or ""

    if (
        sheet == "CBB PUNIT"
        and parse_bank_numbers(entry.get("bank")) == [4]
        and decode.startswith("PCODE_FW_")
        and mcacod.lower() == "0x0410"
    ):
        normalized["mcacod"] = "0x0410, 0x0440"
        notes = normalize_text(entry.get("notes")) or ""
        compat_note = (
            "Pcode FW category from IO_FIRMWARE_MCA_COMMAND. Decoder matches "
            "both legacy 0x0410 and explicit MCCOD/MCACOD 0x0440."
        )
        legacy_note = "MCACOD=0x0410 = Pcode FW MCA category (CAT_MCOD_CBB)."
        if legacy_note in notes:
            normalized["notes"] = notes.replace(legacy_note, compat_note)
        else:
            normalized["notes"] = f"{notes} {compat_note}".strip() if notes else compat_note

    return normalized


class MCADecoder:
    """Decoder for MCA status values."""

    def __init__(self, db_path: str | None = None) -> None:
        script_dir = Path(__file__).parent
        if db_path is None:
            db_path = script_dir / "mca_codes_database.json"
        else:
            db_path = Path(db_path)
            if not db_path.is_absolute() and not db_path.exists():
                alt_path = script_dir / db_path
                if alt_path.exists():
                    db_path = alt_path

        self.db = self._load_database(str(db_path))
        self.entries = [self._prepare_entry(entry) for entry in self.db] if self.db else []
        if self.entries:
            print(f"Loaded {len(self.entries)} MCA decode entries", file=sys.stderr)

    def _load_database(self, path: str) -> list[dict]:
        return load_json_database(path, default=[])

    def _prepare_entry(self, entry: dict) -> dict:
        prepared = _normalize_entry_aliases(entry)
        prepared["bank_numbers"] = parse_bank_numbers(prepared.get("bank"))
        prepared["mscod_pattern"] = compile_code_pattern(prepared.get("mscod"))
        prepared["mcacod_pattern"] = compile_code_pattern(prepared.get("mcacod"))
        return prepared

    def decode_status(self, status_value: str | int, bank: int | None = None) -> dict:
        status_int = parse_code_value(status_value)
        if status_int is None:
            raise ValueError(f"Invalid status value: {status_value}")
        mscod = (status_int >> 16) & 0xFFFF
        mcacod = status_int & 0xFFFF
        matches = self.decode_codes(mscod, mcacod, bank)
        return {
            "status": f"0x{status_int:016X}",
            "bank": bank,
            "mscod": mscod,
            "mcacod": mcacod,
            "matches": matches,
        }

    @staticmethod
    def _status_is_valid_mca(status_value: str | int) -> bool:
        """True only if MCi_STATUS bit 63 (VAL) is set. A status word with VAL=0
        carries no valid machine-check and must not be reported as an error — this
        is what rejects hex tokens accidentally mined from unrelated 64-bit values."""
        status_int = parse_code_value(status_value)
        if status_int is None:
            return False
        return bool((status_int >> 63) & 0x1)

    def decode_codes(self, mscod: int, mcacod: int, bank: int | None = None) -> list[dict]:
        matches: list[dict] = []
        for entry in self.entries:
            bank_numbers = entry.get("bank_numbers", [])
            if bank is not None:
                if not bank_numbers:
                    continue
                if bank not in bank_numbers:
                    continue
            if not match_code(entry.get("mscod_pattern", {}), mscod):
                continue
            if not match_code(entry.get("mcacod_pattern", {}), mcacod):
                continue
            matches.append(entry)
        return matches

    def parse_log(self, log_text: str) -> list[dict]:
        records: list[dict] = []
        lines = log_text.splitlines()

        # Pre-pass: parse CCF table sections (column-based format)
        ccf_records = self._parse_ccf_table(log_text)
        records.extend(ccf_records)

        # Track which line ranges are inside CCF table sections to skip during line-by-line pass
        ccf_line_ranges: list[tuple[int, int]] = []
        in_ccf = False
        ccf_start = 0
        for i, line in enumerate(lines):
            if CCF_TABLE_HEADER_PATTERN.search(line):
                in_ccf = True
                ccf_start = i
            elif in_ccf and line.startswith("╘") or (in_ccf and line.strip() == "" and i > ccf_start + 5):
                ccf_line_ranges.append((ccf_start, i))
                in_ccf = False
        if in_ccf:
            ccf_line_ranges.append((ccf_start, len(lines)))

        def _in_ccf_range(idx: int) -> bool:
            return any(start <= idx <= end for start, end in ccf_line_ranges)

        def _lookback_bank(idx: int, window: int = _LOOKBACK_WINDOW) -> int | None:
            """Look back up to *window* lines for a bank number (e.g. McBank = 0xN)."""
            start = max(0, idx - window)
            for j in range(idx - 1, start - 1, -1):
                b = self._extract_bank(lines[j])
                if b is not None:
                    return b
            return None

        for i, line in enumerate(lines):
            if _in_ccf_range(i):
                continue

            # Linux MCE format: "Bank N: HEXVALUE" (no 0x prefix, 16 hex chars)
            mce_match = MCE_BANK_STATUS_PATTERN.search(line)
            if mce_match:
                mce_bank = int(mce_match.group(1))
                mce_status = "0x" + mce_match.group(2)
                if not self._status_is_valid_mca(mce_status):
                    continue
                decoded = self.decode_status(mce_status, mce_bank)
                decoded["context"] = line.strip()
                records.append(decoded)
                continue

            bank = self._extract_bank(line)
            status_values = self._extract_status_values(line)
            if status_values:
                # If no bank on this line, look back for context (e.g. McBankErrorHandler)
                if bank is None:
                    bank = _lookback_bank(i)
                for status in status_values:
                    # Reject status words whose VAL bit (63) is clear — no valid MCA.
                    if not self._status_is_valid_mca(status):
                        continue
                    decoded = self.decode_status(status, bank)
                    decoded["context"] = line.strip()
                    records.append(decoded)
                continue

            mscod = self._extract_mscod(line)
            mcacod = self._extract_mcacod(line)
            if mscod is not None and mcacod is not None:
                if bank is None:
                    bank = _lookback_bank(i)
                matches = self.decode_codes(mscod, mcacod, bank)
                records.append(
                    {
                        "status": None,
                        "bank": bank,
                        "mscod": mscod,
                        "mcacod": mcacod,
                        "matches": matches,
                        "context": line.strip(),
                    }
                )
        return records

    def _parse_ccf_table(self, log_text: str) -> list[dict]:
        """Parse CCF nd_cbos_sum_mca_status table sections.

        Detects table sections introduced by '========= Ccf: ...' headers and
        extracts MSCOD and MCACOD from the columnar row format:
          │ IpName │ MCA │ Valid │ MCACOD (RRRR,TT) │ MSCOD │ ...│
          │ socket0_cbb1_cbo5 │ ... │ GENERIC_ERR [0x110a] │ TOR_TIMEOUT_ERROR [0x4000] │...│
        """
        records: list[dict] = []
        # Match NAME [0xHEX] from a column cell
        cell_hex_pattern = re.compile(r"\[0x([0-9A-Fa-f]+)\]")
        # Column indices (0-based) for MCACOD and MSCOD in CCF table header
        MCACOD_COL = 3  # "MCACOD (RRRR,TT)"
        MSCOD_COL = 4   # "MSCOD"

        lines = log_text.splitlines()
        in_table = False
        col_indices: dict[str, int] = {}

        for line in lines:
            if CCF_TABLE_HEADER_PATTERN.search(line):
                in_table = True
                col_indices = {}
                continue

            if not in_table:
                continue

            # Detect end of table (bottom border or blank line after table started)
            if line.startswith("╘") or (line.strip() == "" and col_indices):
                in_table = False
                col_indices = {}
                continue

            # Skip box-drawing border rows
            if line.startswith("╒") or line.startswith("╞") or line.startswith("├"):
                continue

            # Detect header row — look for "IpName" and "MSCOD" column headers
            if "IpName" in line and "MSCOD" in line:
                cells = [c.strip() for c in line.split("│")]
                for idx, cell in enumerate(cells):
                    cell_lower = cell.lower()
                    if "ipname" in cell_lower:
                        col_indices["ip"] = idx
                    elif "mcacod" in cell_lower:
                        col_indices["mcacod"] = idx
                    elif "mscod" in cell_lower:
                        col_indices["mscod"] = idx
                    elif "valid" in cell_lower:
                        col_indices["valid"] = idx
                continue

            # Skip rows without Unicode pipe or without "Valid MC"
            if "│" not in line:
                continue

            cells = [c.strip() for c in line.split("│")]

            # Only process rows that indicate a valid Machine Check
            valid_idx = col_indices.get("valid", 2)
            if valid_idx < len(cells) and "Valid MC" not in cells[valid_idx]:
                continue

            mscod_idx = col_indices.get("mscod", MSCOD_COL)
            mcacod_idx = col_indices.get("mcacod", MCACOD_COL)
            ip_idx = col_indices.get("ip", 1)

            if mscod_idx >= len(cells) or mcacod_idx >= len(cells):
                continue

            mscod_cell = cells[mscod_idx]
            mcacod_cell = cells[mcacod_idx]
            ip_name = cells[ip_idx] if ip_idx < len(cells) else ""

            mscod_match = cell_hex_pattern.search(mscod_cell)
            mcacod_match = cell_hex_pattern.search(mcacod_cell)

            if not mscod_match or not mcacod_match:
                continue

            mscod_val = int(mscod_match.group(1), 16)
            mcacod_val = int(mcacod_match.group(1), 16)
            bank = 6  # CCF is always bank 6

            matches = self.decode_codes(mscod_val, mcacod_val, bank)
            records.append({
                "status": None,
                "bank": bank,
                "mscod": mscod_val,
                "mcacod": mcacod_val,
                "matches": matches,
                "context": f"CCF: {ip_name} MSCOD={mscod_cell.strip()} MCACOD={mcacod_cell.strip()}",
            })

        return records

    def _extract_status_values(self, line: str) -> list[str]:
        # Never mine hex out of tooling/plugin-registration or traceback noise —
        # those hex tokens are software IDs/addresses, not MCi_STATUS values.
        if _NOISE_LINE_PATTERN.search(line):
            return []
        matches: list[str] = []
        for pattern in STATUS_PATTERNS:
            matches.extend(match.group(1) for match in pattern.finditer(line))
        if matches:
            return matches

        # Fallback: look for bare 64-bit hex tokens only in clearly MCA-related lines.
        # Use word boundaries so "status_scope_ext" (Python class name) doesn't trigger.
        if not re.search(r"(?i)\b(?:bank|mca|mci|mcg|machine check|status)\b", line):
            return []

        # Skip lines that look like Python object representations (e.g. "object at 0x...")
        if re.search(r"object at 0x[0-9A-Fa-f]+", line, re.IGNORECASE):
            return []

        # Skip lines where MSCOD/MCACOD are already labeled — they will be parsed by
        # the dedicated extraction path, avoiding false positives from decimal numbers.
        if re.search(r"(?i)\bMSCOD\s*=", line) or re.search(r"(?i)\bMCACOD\s*=", line):
            return []

        # Only return tokens with an explicit 0x prefix to avoid treating decimal
        # numbers (all 0-9 chars) as hex status values.
        tokens = re.findall(r"\b0x[0-9A-Fa-f]{8,16}\b", line)
        return tokens

    def _extract_code(self, line: str, pattern: re.Pattern[str]) -> int | None:
        match = pattern.search(line)
        if not match:
            return None
        return parse_code_value(match.group(1))

    def _extract_mscod(self, line: str) -> int | None:
        """Extract MSCOD value from a line, trying multiple PythonSV formats."""
        # Standard: MSCOD=0xE101 or MSCOD: 0xE101
        val = self._extract_code(line, MSCOD_PATTERN)
        if val is not None:
            return val
        # PythonSV verbose: MSCOD=THREE_STRIKE (E101H)
        match = MSCOD_VERBOSE_PATTERN.search(line)
        if match:
            return parse_code_value("0x" + match.group(1))
        # Table row: │ MSCOD │ 0xE101 │
        match = MSCOD_TABLE_PATTERN.search(line)
        if match:
            return parse_code_value(match.group(1))
        return None

    def _extract_mcacod(self, line: str) -> int | None:
        """Extract MCACOD value from a line, trying multiple PythonSV formats."""
        # Standard: MCACOD=0x0400 or MCACOD: 0x0400
        val = self._extract_code(line, MCACOD_PATTERN)
        if val is not None:
            return val
        # PythonSV verbose: MCACOD=INTERNAL_TIMER (0400H)
        match = MCACOD_VERBOSE_PATTERN.search(line)
        if match:
            return parse_code_value("0x" + match.group(1))
        # Table row: │ MCACOD │ 0x400 │
        match = MCACOD_TABLE_PATTERN.search(line)
        if match:
            return parse_code_value(match.group(1))
        return None

    def _extract_bank(self, line: str) -> int | None:
        """Extract bank number from various register path formats.
        
        Supports:
        - BIOS RAS format: McBank = 0xN (hex) — checked first as most specific
        - Register-name format: MC4_STATUS / MC12_ADDR → bank 4 / 12
        - Memory controller paths: mc0-7 → banks 19-26
        - Component paths: ccf, hamvf, hsf, sca, etc.
        - Legacy format: bank #N or bank N
        """
        line_lower = line.lower()
        
        # 1. BIOS RAS format: McBank = 0xN (hex bank number) — most specific
        mcbank_match = MCBANK_HEX_PATTERN.search(line)
        if mcbank_match:
            return int(mcbank_match.group(1), 16)

        # 1b. Register-name format: MC4_STATUS / MC12_ADDR / MC0_MISC → bank number
        mcreg_match = MCREG_BANK_PATTERN.search(line)
        if mcreg_match:
            return int(mcreg_match.group(1))

        # 2. Memory controller: mc0-7 → banks 19-26
        mc_match = MC_PATTERN.search(line_lower)
        if mc_match:
            mc_num = int(mc_match.group(1))
            if 0 <= mc_num <= 7:
                return 19 + mc_num
        
        # 3. Component-based extraction (pre-compiled word-boundary patterns to avoid
        #    false positives like "ha" in "Handler" and repeated regex compilation)
        for pattern, bank_id in _BANK_COMPONENT_REGEXES:
            if pattern.search(line_lower):
                return bank_id
        
        # 4. D2D requires context (CBB vs IMH)
        if re.search(r'\bd2d\b', line_lower):
            if 'cbb' in line_lower or 'core' in line_lower or 'module' in line_lower:
                return 7  # CBB D2D
            elif 'imh' in line_lower or 'ioh' in line_lower:
                return 15  # IMH D2D
        
        # 5. Punit requires context (CBB vs IMH)
        if re.search(r'\bpunit\b', line_lower):
            if 'cbb' in line_lower or 'core' in line_lower or 'module' in line_lower:
                return 4  # CBB Punit
            elif 'imh' in line_lower or 'ioh' in line_lower:
                return 11  # IMH Punit
        
        # 6. Legacy format: bank #N
        match = BANK_PATTERN.search(line)
        if match:
            return int(match.group(1))
        
        return None

    def generate_summary(self, records: list[dict]) -> str:
        if not records:
            return "No MCA status values found in log.\n"

        grouped = defaultdict(list)
        for record in records:
            key = (record.get("bank"), record.get("mscod"), record.get("mcacod"))
            grouped[key].append(record)

        summary = []
        summary.append("## MCA Status Analysis\n\n")
        summary.append(f"**Total status values found:** {len(records)}\n\n")

        for index, ((bank, mscod, mcacod), entries) in enumerate(grouped.items(), 1):
            status_values = sorted({entry.get("status") for entry in entries if entry.get("status")})
            summary.append(f"### Error #{index}: Bank {bank if bank is not None else 'Unknown'}\n\n")
            summary.append(f"**MSCOD:** {format_code(mscod)}\n\n")
            summary.append(f"**MCACOD:** {format_code(mcacod)}\n\n")
            summary.append(f"**Occurrences:** {len(entries)}\n\n")
            if status_values:
                summary.append("**Status Values:**\n")
                for status in status_values[:5]:
                    summary.append(f"- `{status}`\n")
                if len(status_values) > 5:
                    summary.append(f"- ... and {len(status_values) - 5} more\n")
                summary.append("\n")

            matches = entries[0].get("matches", [])
            if matches:
                summary.append("**Matches:**\n")
                for match in matches[:5]:
                    summary.append(self._format_match(match))
                if len(matches) > 5:
                    summary.append(f"- ... and {len(matches) - 5} more matches\n")
                summary.append("\n")
            else:
                summary.append("**Matches:** None found in database\n\n")

            context = entries[0].get("context")
            if context:
                summary.append("**Example Context:**\n")
                summary.append(f"```\n{context}\n```\n\n")

            summary.append("---\n\n")

        return "".join(summary)

    def format_single_decode(self, decoded: dict) -> str:
        output = []
        output.append("## MCA Status Decode\n\n")
        if decoded.get("status"):
            output.append(f"**Status:** `{decoded['status']}`\n\n")
        if decoded.get("bank") is not None:
            output.append(f"**Bank:** {decoded['bank']}\n\n")
        output.append(f"**MSCOD:** {format_code(decoded.get('mscod'))}\n\n")
        output.append(f"**MCACOD:** {format_code(decoded.get('mcacod'))}\n\n")

        matches = decoded.get("matches", [])
        if not matches:
            output.append("**Matches:** None found in database\n")
            return "".join(output)

        output.append("**Matches:**\n")
        for match in matches[:5]:
            output.append(self._format_match(match))
        if len(matches) > 5:
            output.append(f"- ... and {len(matches) - 5} more matches\n")
        return "".join(output)

    def _format_match(self, match: dict) -> str:
        lines = []
        bank_name = match.get("bank_name")
        error_class = match.get("error_class")
        decode = match.get("decode")
        description = match.get("description")
        action = match.get("action")
        notes = match.get("notes")
        sheet = match.get("sheet")
        port_name = match.get("port_name")

        label = "- "
        if bank_name:
            label += f"**{bank_name}**"
        else:
            label += "**Bank Decode**"
        if sheet:
            label += f" ({sheet})"
        lines.append(label + "\n")

        if port_name:
            lines.append(f"  - **Port:** {port_name}\n")
        if error_class:
            lines.append(f"  - **Error Class:** {error_class}\n")
        if decode:
            lines.append(f"  - **Decode:** {decode}\n")
        if description and description != decode:
            lines.append(f"  - **Description:** {description}\n")
        if action:
            lines.append(f"  - **Action:** {action}\n")
        if notes:
            lines.append(f"  - **Notes:** {notes}\n")

        return "".join(lines)
