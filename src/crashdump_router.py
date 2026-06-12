"""Crashdump routing and structured parsing helpers for BugScout.

This module adds a lightweight crashdump-oriented lane that mirrors the
LogIQ-ACD operating model without altering the existing log-centric flow.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass
class CrashBank:
    bank_id: int
    status: str
    address: str = ""
    misc: str = ""


@dataclass
class CrashdumpSummary:
    platform: str = "Unknown"
    stepping: str = ""
    crash_signature: str = ""
    error_type: str = "Unknown"
    subsystem: str = "Unknown"
    primary_bank: dict[str, Any] | None = None
    all_banks: list[dict[str, Any]] = None  # type: ignore[assignment]
    timestamp: str = ""
    node_id: str = ""
    socket_id: str | int = ""
    raw_signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["all_banks"] = self.all_banks or []
        return payload


_PLATFORM_HINTS = {
    "SPR": ["SPR", "SAPPHIRE RAPIDS", "EMERALD RAPIDS", "EMR"],
    "GNR": ["GNR", "GRANITE RAPIDS", "BHS", "BIRCH STREAM", "SRF", "SIERRA FOREST"],
    "DMR": ["DMR", "DIAMOND RAPIDS", "OKS", "OAK STREAM"],
}

_SUBSYSTEM_BANK_MAP = [
    ((0, 3), "IFU/DCU"),
    ((4, 5), "MLC"),
    ((6, 7), "LLC"),
    ((8, 9), "UPI"),
    ((10, 13), "IMC"),
    ((14, 15), "IIO/PCIe"),
]


def detect_input_kind(path: Path) -> str:
    """Return 'json' for structured crash dumps, otherwise 'text'."""
    if path.suffix.lower() == ".json":
        return "json"
    try:
        sample = path.read_text(encoding="utf-8", errors="ignore")[:2048]
    except Exception:
        return "text"
    stripped = sample.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    return "text"


def parse_crashdump(path: Path) -> CrashdumpSummary:
    """Parse a crashdump file into a compact structured summary."""
    if detect_input_kind(path) == "json":
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return parse_crashdump_json(payload, source_name=path.name)

    text = path.read_text(encoding="utf-8", errors="ignore")
    return parse_crashdump_text(text, source_name=path.name)


def parse_crashdump_json(payload: dict[str, Any], source_name: str = "") -> CrashdumpSummary:
    """Parse a structured JSON crashdump payload."""
    platform = _first_non_empty(
        _extract_field(payload, ["platform", "cpu_platform", "programName", "stepping"]),
        _platform_from_text(source_name),
        "Unknown",
    )
    stepping = _first_non_empty(_extract_field(payload, ["stepping", "cpu_stepping", "step"]), "")

    raw_signature = _first_non_empty(
        _extract_field(payload, ["crashSignature", "signature", "errorSignature"]),
        "",
    )

    banks = _extract_banks(payload)
    primary_bank = _pick_primary_bank(banks)
    subsystem = _subsystem_from_bank(primary_bank.get("bank_id")) if primary_bank else "Unknown"
    error_type = _error_type_from_status(primary_bank.get("status", "")) if primary_bank else "Unknown"

    if not raw_signature and primary_bank:
        raw_signature = f"{platform}_MCA_Bank{primary_bank['bank_id']}_{error_type}_{subsystem.replace('/', '_')}"

    return CrashdumpSummary(
        platform=platform,
        stepping=stepping,
        crash_signature=raw_signature or "",
        error_type=error_type,
        subsystem=subsystem,
        primary_bank=primary_bank or None,
        all_banks=banks,
        timestamp=_first_non_empty(_extract_field(payload, ["timestamp", "crashTime", "date"]), ""),
        node_id=_first_non_empty(_extract_field(payload, ["nodeId", "node", "host"]), ""),
        socket_id=_first_non_empty(_extract_field(payload, ["socketId", "socket", "packageId"]), ""),
        raw_signature=raw_signature,
    )


def parse_crashdump_text(text: str, source_name: str = "") -> CrashdumpSummary:
    """Best-effort parse for text crash dumps."""
    platform = _platform_from_text(text) or _platform_from_text(source_name) or "Unknown"
    stepping = _match_first(r"\bstepping\s*[:=]\s*([A-Za-z0-9._-]+)", text)
    raw_signature = _match_first(r"\b(crashSignature|signature)\s*[:=]\s*([A-Za-z0-9._:-]+)", text, group=2)
    timestamp = _match_first(r"\b(timestamp|crashTime|date)\s*[:=]\s*([^\n]+)", text, group=2)
    node_id = _match_first(r"\b(nodeId|node|host)\s*[:=]\s*([^\n]+)", text, group=2)
    socket_id = _match_first(r"\b(socketId|socket|packageId)\s*[:=]\s*([^\n]+)", text, group=2)

    banks = []
    for bank_id, status, address, misc in _extract_text_banks(text):
        banks.append({"bank_id": bank_id, "status": status, "address": address, "misc": misc})

    primary_bank = _pick_primary_bank(banks)
    subsystem = _subsystem_from_bank(primary_bank.get("bank_id")) if primary_bank else "Unknown"
    error_type = _error_type_from_status(primary_bank.get("status", "")) if primary_bank else "Unknown"

    if not raw_signature and primary_bank:
        raw_signature = f"{platform}_MCA_Bank{primary_bank['bank_id']}_{error_type}_{subsystem.replace('/', '_')}"

    return CrashdumpSummary(
        platform=platform,
        stepping=stepping or "",
        crash_signature=raw_signature or "",
        error_type=error_type,
        subsystem=subsystem,
        primary_bank=primary_bank or None,
        all_banks=banks,
        timestamp=timestamp or "",
        node_id=node_id or "",
        socket_id=socket_id or "",
        raw_signature=raw_signature or "",
    )


def route_crashdump(path: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Parse a crashdump and emit a structured summary artifact.

    Returns the summary dict so callers can render their own reports.
    """
    path = Path(path)
    summary = parse_crashdump(path)
    out_dir = Path(output_dir) if output_dir else path.parent / f"crashdump_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "crashdump_summary.json"
    md_path = out_dir / "crashdump_summary.md"

    json_path.write_text(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_markdown(summary, path.name), encoding="utf-8")

    return {
        "summary": summary.to_dict(),
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "output_dir": str(out_dir),
    }


def _render_markdown(summary: CrashdumpSummary, source_name: str) -> str:
    banks = summary.all_banks or []
    lines = [
        f"# Crashdump Summary - {source_name}",
        "",
        f"- Platform: {summary.platform}",
        f"- Stepping: {summary.stepping or 'Unknown'}",
        f"- Signature: {summary.crash_signature or 'Unknown'}",
        f"- Error type: {summary.error_type}",
        f"- Subsystem: {summary.subsystem}",
        f"- Timestamp: {summary.timestamp or 'Unknown'}",
        f"- Node: {summary.node_id or 'Unknown'}",
        f"- Socket: {summary.socket_id or 'Unknown'}",
        "",
        "## Primary Bank",
    ]
    if summary.primary_bank:
        bank = summary.primary_bank
        lines.extend([
            f"- Bank ID: {bank.get('bank_id', '')}",
            f"- Status: {bank.get('status', '')}",
            f"- Address: {bank.get('address', '')}",
            f"- Misc: {bank.get('misc', '')}",
        ])
    else:
        lines.append("- None detected")

    if banks:
        lines += ["", "## All Banks"]
        for bank in banks:
            lines.append(f"- Bank {bank.get('bank_id', '')}: {bank.get('status', '')}")

    return "\n".join(lines)


def _extract_field(payload: dict[str, Any], names: Iterable[str]) -> list[Any]:
    values: list[Any] = []
    for name in names:
        value = payload.get(name)
        if value not in (None, "", [], {}):
            values.append(value)
    return values


def _first_non_empty(values: Iterable[Any], default: Any = "") -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return default


def _platform_from_text(text: str) -> str:
    upper = text.upper()
    for platform, hints in _PLATFORM_HINTS.items():
        if any(hint in upper for hint in hints):
            return platform
    return ""


def _extract_banks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidate_keys = ["mca_banks", "mcaBanks", "MCA_BANKS", "error_records", "machine_check_banks"]
    for key in candidate_keys:
        value = payload.get(key)
        if isinstance(value, list):
            banks = []
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                bank_id = entry.get("bank") or entry.get("bankId") or entry.get("bank_number")
                status = entry.get("status") or entry.get("MCI_STATUS") or entry.get("statusRegister")
                address = entry.get("address") or entry.get("MCI_ADDR") or entry.get("addressRegister") or ""
                misc = entry.get("misc") or entry.get("MCI_MISC") or entry.get("miscRegister") or ""
                if bank_id is None or status in (None, ""):
                    continue
                banks.append({
                    "bank_id": int(bank_id),
                    "status": _hexify(status),
                    "address": _hexify(address) if address not in (None, "") else "",
                    "misc": _hexify(misc) if misc not in (None, "") else "",
                })
            if banks:
                return banks
    return []


def _extract_text_banks(text: str) -> list[tuple[int, str, str, str]]:
    banks = []
    patterns = [
        r"(?:MCA|MCE)\s*Bank\s*(\d+)\s*[:=]\s*status\s*[:=]\s*(0x[0-9a-fA-F]+)(?:\s*addr\s*[:=]\s*(0x[0-9a-fA-F]+))?(?:\s*misc\s*[:=]\s*(0x[0-9a-fA-F]+))?",
        r"Bank\s*(\d+)\s*[:=]\s*(0x[0-9a-fA-F]+)(?:\s*[:\-]\s*(0x[0-9a-fA-F]+))?(?:\s*[:\-]\s*(0x[0-9a-fA-F]+))?",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            groups = match.groups()
            bank_id = int(groups[0])
            status = groups[1]
            address = groups[2] or ""
            misc = groups[3] or ""
            banks.append((bank_id, _hexify(status), _hexify(address) if address else "", _hexify(misc) if misc else ""))
    return banks


def _pick_primary_bank(banks: list[dict[str, Any]]) -> dict[str, Any]:
    if not banks:
        return {}

    def severity(bank: dict[str, Any]) -> tuple[int, int]:
        status = str(bank.get("status", "0x0"))
        uc = _status_bit(status, 61)
        pcc = _status_bit(status, 52)
        if uc == 0:
            rank = 0
        elif uc == 1 and pcc == 0:
            rank = 1
        else:
            rank = 2
        return rank, int(bank.get("bank_id", 0))

    return sorted(banks, key=severity, reverse=True)[0]


def _error_type_from_status(status: str) -> str:
    uc = _status_bit(status, 61)
    pcc = _status_bit(status, 52)
    if uc == 0:
        return "CORRECTED"
    if uc == 1 and pcc == 0:
        return "UNCORRECTED"
    if uc == 1 and pcc == 1:
        return "FATAL"
    return "Unknown"


def _subsystem_from_bank(bank_id: Any) -> str:
    try:
        bank_num = int(bank_id)
    except Exception:
        return "Unknown"
    for bounds, subsystem in _SUBSYSTEM_BANK_MAP:
        start, end = bounds
        if start <= bank_num <= end:
            return subsystem
    return "Uncore/M2M/CHA"


def _status_bit(status_hex: str, bit: int) -> int:
    try:
        value = int(str(status_hex), 16)
    except Exception:
        return 0
    return (value >> bit) & 1


def _hexify(value: Any) -> str:
    if isinstance(value, str):
        s = value.strip()
        return s if s.startswith("0x") else s
    if isinstance(value, int):
        return hex(value)
    return str(value)


def _match_first(pattern: str, text: str, group: int = 1) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return match.group(group).strip()
    return ""
