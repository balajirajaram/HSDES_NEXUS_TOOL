"""AXON integration — cross-reference the issue against Intel's Axon validation-
failure database.

Axon (https://axon.intel.com) stores validation test failure records with
failure signatures, buckets, and Val-Log-Archive execution data. Its Explore UI
takes a gzip+base64-url-encoded Snowflake query in the `?query=` param, e.g.
{"mode":"advance","advanceQuery":"SELECT ... FROM AXON_DATA.vw_record ..."}.

We build that query from the detected platform (TLA) + the failure signatures /
suspected-area terms found by log & comment analysis, then emit a ready-to-open
Axon Explore deep-link. The user's browser is already SSO'd to Axon, so this
needs no token and works from the standalone app ("review everything").

Optional live mode: if config.AXON_TOKEN is set, we could POST the same query to
the Axon API — left as a hook; the deep-link is the reliable, shareable path.
"""

import base64
import gzip
import json
import re
from typing import List, Optional
from urllib.parse import quote

from .config import config

_AXON_BASE = "https://axon.intel.com"

# Platform label -> Axon platform.tla short code.
_TLA = {
    "granite rapids": "GNR", "gnr": "GNR", "birch stream": "GNR",
    "sierra forest": "SRF", "srf": "SRF",
    "clearwater forest": "CWF", "cwf": "CWF",
    "diamond rapids": "DMR", "dmr": "DMR",
    "coral rapids": "COR", "cor": "COR",
}


def platform_tla(platform: Optional[str]) -> Optional[str]:
    if not platform:
        return None
    p = platform.lower()
    for key, tla in _TLA.items():
        if key in p:
            return tla
    return None


def _encode_query(sql: str) -> str:
    payload = json.dumps({"mode": "advance", "advanceQuery": sql}).encode("utf-8")
    gz = gzip.compress(payload)
    b64 = base64.b64encode(gz).decode("ascii")
    return b64.replace("+", "-").replace("/", "_").rstrip("=")


def _clean_term(t: str) -> str:
    # keep short, distinctive tokens; strip quotes / SQL-breaking chars
    t = re.sub(r"['\";\\%]", " ", t).strip()
    return t[:40]


def build_explore_link(platform: Optional[str], terms: List[str],
                       days: int = 120, limit: int = 200) -> Optional[dict]:
    """Build an Axon Explore deep-link that filters GNR/SRF/CWF fail records whose
    Val-Log-Archive execution data matches any of the given terms."""
    tla = platform_tla(platform)
    seen: List[str] = []
    for t in terms:
        c = _clean_term(t)
        if c and len(c) >= 3 and c.lower() not in [s.lower() for s in seen]:
            seen.append(c)
    seen = seen[:8]
    if not tla or not seen:
        return None
    ea = 'r."contents.intel-val-log-archive-v1":ExecutionAutomation'
    like = " OR ".join(f"TO_VARCHAR({ea}) ILIKE '%{t}%'" for t in seen)
    sql = (
        'SELECT r."_id", r."platform.tla", r."ts", r."type", '
        f'{ea}:testSuiteName::STRING AS test_suite, '
        f'{ea}:goalName::STRING AS goal '
        'FROM AXON_DATA.vw_record r '
        f"WHERE r.\"platform.tla\" = '{tla}' "
        "AND r.\"type\" = 'fail' "
        "AND ARRAY_CONTAINS('intel-val-log-archive-v1'::VARIANT, r.\"_contentTypes\") "
        f'AND r."ts" >= DATEADD(DAY, -{days}, CURRENT_TIMESTAMP()) '
        f"AND ({like}) "
        f'ORDER BY r."ts" DESC LIMIT {limit}'
    )
    url = f"{_AXON_BASE}/app/explore/?query={_encode_query(sql)}&tab=tabular"
    return {"tla": tla, "terms": seen, "days": days, "url": url}


def axon_cross_reference(platform: Optional[str], signatures: List[str],
                         suspected_area: str = "", extra_terms: Optional[List[str]] = None
                         ) -> Optional[dict]:
    """Assemble Axon search terms from failure signatures + suspected area, and
    return the Explore deep-link payload (or None if we can't form a query)."""
    terms: List[str] = []
    # 1) Most distinctive first: suspected-area mechanism phrases (from attachment).
    for phrase in ("kitportdisable", "topology failover", "s3m", "check-in",
                   "socket removal", "nack"):
        if suspected_area and phrase in suspected_area.lower() and phrase not in terms:
            terms.append(phrase)
    # 2) Then extra caller terms (e.g. UPLR version breadcrumb).
    for t in (extra_terms or []):
        if t and t.lower() not in [x.lower() for x in terms]:
            terms.append(t)
    # 3) Then distinctive tokens from the failure signatures (generic ones last).
    _PRIMARY = {"upi", "kti", "s3m", "caterr", "ierr", "kitportdisable",
                "topology", "nack", "tx_timeout", "ice", "whea"}
    _SECONDARY = {"mca", "machine check", "soft lockup", "pcie", "cxl", "aer",
                  "ddr", "ecc", "hang", "reset", "watchdog", "boot", "post",
                  "checkpoint"}
    primary: List[str] = []
    secondary: List[str] = []
    for s in signatures:
        for tok in re.split(r"[\s/()\-]+", s.lower()):
            if tok in _PRIMARY and tok not in primary:
                primary.append(tok)
            elif tok in _SECONDARY and tok not in secondary:
                secondary.append(tok)
    for t in primary + secondary:
        if t not in terms:
            terms.append(t)
    return build_explore_link(platform, terms)
