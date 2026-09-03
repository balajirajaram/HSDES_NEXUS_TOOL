"""DMR PUNIT / MCTile MCA sub-decoder.

PUNIT machine-checks carry MCACOD=0x402 and hide the real cause in the
UC[19:16] / HW[23:20] / FW[31:24] sub-fields of MCi_STATUS (decoded in that
priority order — first non-zero wins). Memory-controller (MCTile) errors set
bit 7 of MCACOD and carry the cause in MSCOD[31:16].

Data: app/decoders/dmr_punit_mca.json (transcribed from the bugninja-agents
kokua `mca-decoder` skill / DMR primecode_mca.xml). This only applies to DMR;
callers should gate on product == DMR.
"""

import json
import os
from typing import Any, Dict, Optional

_PATH = os.path.join(os.path.dirname(__file__), "dmr_punit_mca.json")
_CACHE: Optional[Dict[str, Any]] = None


def _data() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {}
    return _CACHE


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16 if value.lower().startswith("0x") else 10)
        except ValueError:
            return None
    return None


def decode_punit(mc_status: Any) -> Optional[Dict[str, str]]:
    """Decode a DMR PUNIT (MCACOD=0x402) MCi_STATUS.

    Returns {sub_field, code, name, description} for the first non-zero of
    UC -> HW -> FW, or None if this isn't a PUNIT status word."""
    status = _to_int(mc_status)
    if status is None:
        return None
    if (status & 0xFFFF) != 0x402:
        return None
    d = _data()
    uc = (status >> 16) & 0xF
    if uc:
        desc = d.get("punit_uc", {}).get("codes", {}).get(f"0x{uc:X}")
        return {"sub_field": "UC", "code": f"0x{uc:X}",
                "name": d.get("punit_uc", {}).get("name", "PUNIT UC ERROR"),
                "description": desc or "Unknown PUNIT UC code"}
    hw = (status >> 20) & 0xF
    if hw:
        desc = d.get("punit_hw", {}).get("codes", {}).get(f"0x{hw:X}")
        return {"sub_field": "HW", "code": f"0x{hw:X}",
                "name": d.get("punit_hw", {}).get("name", "PUNIT HW ERROR"),
                "description": desc or "Unknown PUNIT HW code"}
    fw = (status >> 24) & 0xFF
    if fw:
        desc = d.get("punit_fw", {}).get("codes", {}).get(str(fw))
        return {"sub_field": "FW", "code": str(fw),
                "name": d.get("punit_fw", {}).get("name", "PUNIT FW ERROR"),
                "description": desc or f"Unknown/undefined PUNIT FW code {fw}"}
    return None


def decode_mctile_mscod(mscod: Any) -> Optional[str]:
    """Return the DMR MCTile (memory) MSCOD description, or None."""
    val = _to_int(mscod)
    if val is None:
        return None
    return _data().get("mctile", {}).get("mscod", {}).get(f"0x{val:04X}")


def decode(mc_status: Any, product: str = "") -> Optional[Dict[str, str]]:
    """Product-gated entry point: DMR only. Returns the PUNIT sub-decode when
    the status word is a PUNIT (0x402) machine-check, else None."""
    if product and product.upper() != "DMR":
        return None
    return decode_punit(mc_status)
