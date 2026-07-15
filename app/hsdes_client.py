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
from typing import Any, Dict, List, Optional

import httpx

from .config import config

try:  # optional, Windows-only Kerberos/Negotiate
    import requests
    from requests_negotiate_sspi import HttpNegotiateAuth
    _SSPI_AVAILABLE = True
except Exception:
    _SSPI_AVAILABLE = False

_ARTICLE_FIELDS = ",".join([
    "id", "title", "status", "owner", "priority", "family", "release",
    "component", "subcomponent", "stepping", "silicon_stepping",
    "release_affected", "family_affected", "description", "reason",
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
    def _kerberos_request(self, method: str, url: str, **kw) -> Any:
        if not _SSPI_AVAILABLE:
            raise RuntimeError(
                "Kerberos mode needs 'requests-negotiate-sspi' "
                "(pip install requests-negotiate-sspi)")
        resp = requests.request(method, url, auth=HttpNegotiateAuth(),
                                headers={"Accept": "application/json"},
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
            data = await self._get_json(f"{self.base}/article/{hsd_id}",
                                        {"fields": _ARTICLE_FIELDS})
            comments = await self._fetch_comments(hsd_id)
        except Exception as exc:
            return {"id": hsd_id, "error": str(exc)}
        return self._normalize(hsd_id, data, comments)

    async def _fetch_comments(self, hsd_id: str) -> List[str]:
        for path in (f"/article/{hsd_id}/comments", f"/article/{hsd_id}/history"):
            try:
                data = await self._get_json(f"{self.base}{path}")
            except Exception:
                continue
            rows = (data or {}).get("data") or (data or {}).get("comments") or []
            out: List[str] = []
            for row in rows:
                if isinstance(row, dict):
                    txt = (row.get("comment") or row.get("text")
                           or row.get("body") or row.get("value") or "")
                    who = row.get("updated_by") or row.get("author") or ""
                    when = row.get("updated_date") or row.get("date") or ""
                    if txt:
                        out.append(f"[{when} {who}] {txt}".strip())
                elif isinstance(row, str):
                    out.append(row)
            if out:
                return out
        return []

    def _normalize(self, hsd_id: str, data: Any,
                   comments: Optional[List[str]] = None) -> Dict[str, Any]:
        try:
            rec = (data.get("data") or [{}])[0]
        except Exception:
            rec = data if isinstance(data, dict) else {}

        def g(*keys: str) -> str:
            for k in keys:
                if isinstance(rec, dict) and rec.get(k):
                    return rec[k]
            return ""

        comments = comments or []
        description = g("description", "reason")
        full_text = "\n\n".join(filter(None, [
            f"TITLE: {g('title', 'subject')}",
            f"DESCRIPTION:\n{description}" if description else "",
            ("COMMENTS:\n" + "\n".join(comments)) if comments else "",
        ]))
        return {
            "id": hsd_id,
            "title": g("title", "subject"),
            "family": g("family", "family_affected"),
            "release": g("release", "release_affected"),
            "priority": g("priority"),
            "component": g("component", "subcomponent", "family_affected"),
            "stepping": g("stepping", "silicon_stepping", "release_affected"),
            "status": g("status"),
            "owner": g("owner", "assignee", "engineering_owner"),
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
        """Resolve a saved HSDES query id to a list of HSD IDs (best-effort)."""
        if not self.enabled:
            return []
        for path in (f"/query/{query_id}", f"/appstore/query/{query_id}",
                     f"/query/execution/{query_id}"):
            try:
                data = await self._get_json(f"{self.base}{path}", {"max": limit})
            except Exception:
                continue
            rows = (data or {}).get("data") or (data or {}).get("results") or []
            ids: List[str] = []
            for r in rows:
                if isinstance(r, dict):
                    v = r.get("id") or r.get("ID") or r.get("article_id")
                    if v:
                        ids.append(str(v))
                elif isinstance(r, (str, int)):
                    ids.append(str(r))
            if ids:
                return ids[:limit]
        return []


def get_client(token: Optional[str] = None, username: Optional[str] = None,
               password: Optional[str] = None) -> "HSDESClient":
    return HSDESClient(token, username, password)


hsdes = HSDESClient()
