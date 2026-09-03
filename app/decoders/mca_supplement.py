"""MCA supplement resolver — verified IP-specific MSCOD, generic MCACOD, and
RAS recovery-class lookups that complement the bank->IP maps.

Data: app/decoders/mca_codes_supplemental.json (verified EDS-R / BHS RAS / BWG
values only). GNR/SRF/CWF share the BHS family encoding; DMR uses dmr_punit.
Nothing is guessed — an unknown code returns None.
"""

import json
import os
from typing import Any, Dict, Optional

_PATH = os.path.join(os.path.dirname(__file__), "mca_codes_supplemental.json")
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
    if isinstance(value, str) and value.strip():
        try:
            v = value.strip()
            return int(v, 16 if v.lower().startswith("0x") else 10)
        except ValueError:
            return None
    return None


def _family(product: str) -> str:
    return _data().get("_product_family", {}).get((product or "").upper(), "")


def mcacod_meaning(mcacod: Any, product: str) -> Optional[str]:
    fam = _family(product)
    val = _to_int(mcacod)
    if not fam or val is None:
        return None
    return _data().get("families", {}).get(fam, {}).get("mcacod", {}).get(f"0x{val:X}") \
        or _data().get("families", {}).get(fam, {}).get("mcacod", {}).get(f"0x{val:03X}")


def mscod_meaning(mscod: Any, ip: str, product: str) -> Optional[str]:
    """IP-specific MSCOD meaning (ip is a component name like 'UPI'/'CHA')."""
    fam = _family(product)
    val = _to_int(mscod)
    if not fam or val is None or not ip:
        return None
    ip_key = next((k for k in _data().get("families", {}).get(fam, {})
                   .get("mscod_by_ip", {}) if k.upper() in ip.upper()), None)
    if not ip_key:
        return None
    table = _data()["families"][fam]["mscod_by_ip"][ip_key]
    return table.get(f"0x{val:X}") or table.get(f"0x{val:04X}")


def recovery_for_status(status: Any) -> Optional[Dict[str, str]]:
    """Classify OS/RAS recovery from MCi_STATUS severity bits.

    UC=bit61, PCC=bit57, AR=bit55, S=bit56 (per Intel SDM MCi_STATUS)."""
    val = _to_int(status)
    if val is None:
        return None
    uc = (val >> 61) & 1
    classes = _data().get("recovery", {}).get("classes", {})
    if not uc:
        return classes.get("CE")
    pcc = (val >> 57) & 1
    if pcc:
        return classes.get("FATAL")
    ar = (val >> 55) & 1
    s = (val >> 56) & 1
    if ar:
        return classes.get("SRAR")
    if s:
        return classes.get("SRAO")
    return classes.get("UCNA")
