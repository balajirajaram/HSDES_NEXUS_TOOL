"""Product-aware MCA bank -> component/unit resolver.

Names the failing MCA bank for the report (e.g. GNR bank 7 -> "CHA (CPU Uncore)").
GNR uses bank_mapping_gnr.json (from the SPIV GNR MCA Bank Assignments wiki);
other products fall back to the DMR layout in bank_mapping.json.
"""

from __future__ import annotations

import json
import os
from typing import Optional

_DIR = os.path.dirname(__file__)
_CACHE: dict[str, dict] = {}


def _load(name: str) -> dict:
    if name not in _CACHE:
        try:
            with open(os.path.join(_DIR, name), encoding="utf-8") as fh:
                _CACHE[name] = json.load(fh)
        except Exception:
            _CACHE[name] = {}
    return _CACHE[name]


def _is_gnr(product: str) -> bool:
    p = (product or "").upper()
    return "GNR" in p or "GRANITE" in p


def _is_srf(product: str) -> bool:
    p = (product or "").upper()
    return "SRF" in p or "SIERRA" in p


def _is_cwf(product: str) -> bool:
    p = (product or "").upper()
    return "CWF" in p or "CLEARWATER" in p


def bank_component(bank, product: str = "") -> Optional[dict]:
    """Return {'component', 'category', 'source'} for a bank, or None if unknown.

    Product-specific maps are used so the same bank number resolves to the right
    silicon unit (e.g. bank 7 = CHA on GNR/SRF/CWF but HA/MVF on DMR). GNR, SRF,
    CWF and DMR each have their own map; empty/reserved banks return None.
    """
    if bank is None:
        return None
    try:
        b = int(str(bank).strip(), 0) if isinstance(bank, str) else int(bank)
    except (TypeError, ValueError):
        return None

    if _is_gnr(product):
        m = _load("bank_mapping_gnr.json").get(str(b))
        if m and m.get("component") and m.get("component") != "(Empty)":
            return {"component": m["component"], "category": m.get("category", ""),
                    "source": "GNR MCA Bank Assignments"}
        return None

    if _is_srf(product):
        m = _load("bank_mapping_srf.json").get(str(b))
        if m and m.get("component") and not m["component"].startswith(("(Empty)", "Reserved")):
            return {"component": m["component"], "category": m.get("category", ""),
                    "source": "SRF MCA Bank Assignments"}
        return None

    if _is_cwf(product):
        m = _load("bank_mapping_cwf.json").get(str(b))
        if m and m.get("component") and not m["component"].startswith(("(Unused)", "Reserved")):
            return {"component": m["component"], "category": m.get("category", ""),
                    "source": "CWF MCA Bank Assignments"}
        return None

    # Default: DMR bank layout (existing customer-doc map).
    m = _load("bank_mapping.json").get(str(b))
    if m and m.get("domain0_component"):
        comp = m["domain0_component"]
        if comp and comp not in ("Reserved/Undefined",):
            return {"component": comp, "category": m.get("location", ""),
                    "source": "DMR MCA bank map"}
    return None


def bank_label(bank, product: str = "") -> str:
    """Human label like 'CHA (CPU Uncore)' or '' when the bank is unknown."""
    info = bank_component(bank, product)
    if not info:
        return ""
    cat = info.get("category")
    return f"{info['component']} ({cat})" if cat else info["component"]
