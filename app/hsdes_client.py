"""HSDES REST client — unified auth (token / username+password / Kerberos-auto).

Auth modes:
  - token:    Bearer token (HSDES_API_TOKEN or per-request).
  - basic:    HTTP Basic with the user's Intel username + password.
  - auto/kerberos: Negotiate/SSPI using the logged-in Intel user (no prompt).
               Requires `requests-negotiate-sspi` on Windows.

Reads the ticket FULLY (header + description + comments). Also resolves saved
HSDES queries by id (for batch-learn). Field/endpoint names vary per tenant;
adjust `_normalize` / `_fetch_comments` / `get_query_results` if needed.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional

import httpx

from .config import config

try:  # Kerberos/Negotiate (proven method: requests + requests-kerberos + verify=False)
    import requests
    _REQUESTS_AVAILABLE = True
except Exception:
    _REQUESTS_AVAILABLE = False
try:
    from requests_kerberos import HTTPKerberosAuth
    _KERBEROS_KIND = "kerberos"
except Exception:
    try:
        from requests_negotiate_sspi import HttpNegotiateAuth
        _KERBEROS_KIND = "sspi"
    except Exception:
        _KERBEROS_KIND = None

_ARTICLE_FIELDS = ",".join([
    "id", "title", "status", "owner", "priority", "exposure", "reason",
    "report_type", "family", "soc_family", "soc_version", "release",
    "release_affected", "family_affected", "component", "subcomponent",
    "stepping", "silicon_stepping", "suspect_area", "days_open",
    "description", "executive_summary",
])


class HSDESClient:
    def __init__(self, token: Optional[str] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None):
        self.base = config.HSDES_BASE_URL.rstrip("/")
        self.token = (token or "").strip() or config.HSDES_API_TOKEN
        self.username = (username or "").strip()
        self.password = password or ""
        self._auth = httpx.BasicAuth(self.username, self.password) if (
            self.username and self.password) else None
        self.kerberos = config.HSDES_AUTH_MODE.lower() in ("auto", "kerberos")
        self.enabled = bool(self.token or self._auth or self.kerberos)

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.token and not self._auth:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _use_kerberos(self) -> bool:
        return self.kerberos and not (self.token or self._auth)

    # ---- transport ----
    def _kerberos_auth(self):
        if _KERBEROS_KIND == "kerberos":
            return HTTPKerberosAuth()
        if _KERBEROS_KIND == "sspi":
            return HttpNegotiateAuth()
        return None

    def _kerberos_request(self, method: str, url: str, **kw) -> Any:
        if not (_REQUESTS_AVAILABLE and _KERBEROS_KIND):
            raise RuntimeError(
                "Kerberos mode needs 'requests-kerberos' "
                "(pip install requests-kerberos)")
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        resp = requests.request(method, url, auth=self._kerberos_auth(),
                                verify=False,
                                headers={"Content-type": "application/json"},
                                timeout=45, **kw)
        resp.raise_for_status()
        return resp.json()

    async def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if self._use_kerberos():
            return await asyncio.to_thread(self._kerberos_request, "GET", url, params=params)
        async with httpx.AsyncClient(timeout=45, auth=self._auth) as cx:
            r = await cx.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            return r.json()

    async def _post_json(self, url: str, payload: Dict[str, Any]) -> Any:
        if self._use_kerberos():
            return await asyncio.to_thread(self._kerberos_request, "POST", url, json=payload)
        async with httpx.AsyncClient(timeout=45, auth=self._auth) as cx:
            r = await cx.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()

    # ---- reads ----
    async def get_article(self, hsd_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        try:
            # Full record: title/description/comments come back unprefixed and
            # structured fields are tenant-prefixed (e.g. bug.exposure). The
            # comment thread lives in the 'comments' field (no separate endpoint).
            data = await self._get_json(f"{self.base}/article/{hsd_id}")
        except Exception as exc:
            return {"id": hsd_id, "error": str(exc)}
        return self._normalize(hsd_id, data)

    @staticmethod
    def _clean(text: Any) -> str:
        if not isinstance(text, str):
            return ""
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = re.sub(r"<[^>]+>", " ", text)          # strip HTML tags
        return re.sub(r"[ \t]+", " ", text).strip()

    @classmethod
    def _split_comments(cls, blob: Any) -> List[str]:
        """HSDES stores the thread in one 'comments' string; entries begin with
        '++++<epoch> <user>'. Split into individual, cleaned comments."""
        if not isinstance(blob, str) or not blob.strip():
            return []
        parts = re.split(r"\++\d{6,}", blob)  # split on the ++++<timestamp> marker
        out = [cls._clean(p) for p in parts]
        return [p for p in out if p]

    def _normalize(self, hsd_id: str, data: Any,
                   _comments: Optional[List[str]] = None) -> Dict[str, Any]:
        try:
            rec = (data.get("data") or [{}])[0]
        except Exception:
            rec = data if isinstance(data, dict) else {}

        def g(*names: str) -> str:
            # exact key first, then tenant-prefixed suffix match (bug.exposure -> exposure)
            for n in names:
                if isinstance(rec, dict) and rec.get(n):
                    return rec[n]
            for n in names:
                if isinstance(rec, dict):
                    for k, v in rec.items():
                        if v and (k == n or k.endswith("." + n)):
                            return v
            return ""

        title = self._clean(g("title", "subject"))
        description = self._clean(g("description", "reason"))
        comments = self._split_comments(g("comments"))
        full_text = "\n\n".join(filter(None, [
            f"TITLE: {title}",
            f"DESCRIPTION:\n{description}" if description else "",
            ("COMMENTS:\n" + "\n".join(comments)) if comments else "",
        ]))
        return {
            "id": hsd_id,
            "title": title,
            "family": g("family", "family_affected", "soc_family"),
            "release": g("release", "release_affected"),
            "priority": g("priority", "exposure"),
            "exposure": g("exposure"),
            "report_type": g("report_type"),
            "reason": g("reason"),
            "component": g("component", "subcomponent"),
            "stepping": g("stepping", "silicon_stepping"),
            "status": g("status"),
            "owner": g("owner", "assignee", "engineering_owner"),
            "phase_found": g("phase_found"),
            "team_found": g("team_found"),
            "product_found": g("product_found"),
            "description": description,
            "comments": comments,
            "full_text": full_text,
            "raw": rec,
        }

    async def search_similar(self, symptoms: str, limit: int = 8) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            data = await self._post_json(f"{self.base}/query",
                                         {"query": symptoms, "max": limit})
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for rec in (data.get("data") or [])[:limit]:
            out.append({
                "id": rec.get("id", ""),
                "title": rec.get("title", ""),
                "status": rec.get("status", ""),
                "component": rec.get("component", ""),
            })
        return out

    async def get_query_results(self, query_id: str, limit: int = 200) -> List[str]:
        """Resolve a saved HSDES query id to a list of HSD IDs via the REST
        /query/{id} endpoint with pagination (start_at / max_results)."""
        if not self.enabled:
            return []
        url = f"{self.base}/query/{query_id}"
        ids: List[str] = []
        start_at, page = 0, 100
        while len(ids) < limit:
            try:
                data = await self._get_json(
                    url, {"start_at": start_at, "max_results": page})
            except Exception:
                break
            rows = (data or {}).get("data") or []
            if not rows:
                break
            for r in rows:
                v = r.get("id") if isinstance(r, dict) else r
                if v:
                    ids.append(str(v))
            if len(rows) < page:
                break
            start_at += page
        return ids[:limit]


def get_client(token: Optional[str] = None, username: Optional[str] = None,
               password: Optional[str] = None) -> "HSDESClient":
    return HSDESClient(token, username, password)


hsdes = HSDESClient()
