"""Best-effort HSDES REST client.

NOTE: Intel's HSDES REST field names and endpoints vary by tenant. The
normalizer below maps the most common fields; adjust `_normalize` /
`search_similar` to match your environment's actual API contract.
When no token is configured, the client is disabled and the analyzer
falls back to OFFLINE mode instead of fabricating data.
"""

from typing import Any, Dict, List, Optional

import httpx

from .config import config


class HSDESClient:
    def __init__(self):
        self.base = config.HSDES_BASE_URL.rstrip("/")
        self.token = config.HSDES_API_TOKEN
        self.enabled = config.hsdes_enabled

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def get_article(self, hsd_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        url = f"{self.base}/article/{hsd_id}"
        try:
            async with httpx.AsyncClient(timeout=30) as cx:
                r = await cx.get(url, headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # network / auth / not found
            return {"id": hsd_id, "error": str(exc)}
        return self._normalize(hsd_id, data)

    def _normalize(self, hsd_id: str, data: Any) -> Dict[str, Any]:
        try:
            rec = (data.get("data") or [{}])[0]
        except Exception:
            rec = data if isinstance(data, dict) else {}

        def g(*keys: str) -> str:
            for k in keys:
                if isinstance(rec, dict) and rec.get(k):
                    return rec[k]
            return ""

        return {
            "id": hsd_id,
            "title": g("title", "subject"),
            "component": g("component", "subcomponent", "family_affected"),
            "stepping": g("stepping", "silicon_stepping", "release_affected"),
            "status": g("status"),
            "owner": g("owner", "assignee", "engineering_owner"),
            "description": g("description", "reason", "comments"),
            "raw": rec,
        }

    async def search_similar(self, symptoms: str, limit: int = 8) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        url = f"{self.base}/query"
        payload = {"query": symptoms, "max": limit}
        try:
            async with httpx.AsyncClient(timeout=30) as cx:
                r = await cx.post(url, headers=self._headers(), json=payload)
                r.raise_for_status()
                data = r.json()
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


hsdes = HSDESClient()
