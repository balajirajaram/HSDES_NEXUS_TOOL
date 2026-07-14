"""Best-effort HSDES REST client (reads the ticket FULLY: header + description + comments).

NOTE: Intel's HSDES REST field names and endpoints vary by tenant. The
normalizer below maps the most common fields; adjust `_normalize`,
`_fetch_comments` and `search_similar` to match your environment's actual API
contract. When no token is configured, the client is disabled and the analyzer
falls back to OFFLINE mode instead of fabricating data.
"""

from typing import Any, Dict, List, Optional

import httpx

from .config import config

# Fields we ask HSDES for so the analyzer has the full debug narrative.
_ARTICLE_FIELDS = ",".join([
    "id", "title", "status", "owner", "priority", "family", "release",
    "component", "subcomponent", "stepping", "silicon_stepping",
    "release_affected", "family_affected", "description", "reason",
])


class HSDESClient:
    def __init__(self, token: Optional[str] = None):
        # Per-user token (from the SSO session) takes precedence over any
        # server-side fallback. Used only for this request; never persisted.
        self.base = config.HSDES_BASE_URL.rstrip("/")
        self.token = (token or "").strip() or config.HSDES_API_TOKEN
        self.enabled = bool(self.token)

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def get_article(self, hsd_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the full ticket: header fields + description + comments."""
        if not self.enabled:
            return None
        url = f"{self.base}/article/{hsd_id}"
        try:
            async with httpx.AsyncClient(timeout=45) as cx:
                r = await cx.get(url, headers=self._headers(),
                                 params={"fields": _ARTICLE_FIELDS})
                r.raise_for_status()
                data = r.json()
                comments = await self._fetch_comments(cx, hsd_id)
        except Exception as exc:  # network / auth / not found
            return {"id": hsd_id, "error": str(exc)}
        return self._normalize(hsd_id, data, comments)

    async def _fetch_comments(self, cx: httpx.AsyncClient, hsd_id: str) -> List[str]:
        """Best-effort: pull the comment/update thread (the debug narrative)."""
        for path in (f"/article/{hsd_id}/comments", f"/article/{hsd_id}/history"):
            try:
                r = await cx.get(f"{self.base}{path}", headers=self._headers())
                if r.status_code != 200:
                    continue
                data = r.json()
                rows = data.get("data") or data.get("comments") or []
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
            except Exception:
                continue
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
        # A single blob the LLM can reason over (title + description + comments).
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


def get_client(token: Optional[str] = None) -> "HSDESClient":
    """Build a request-scoped client using the caller's own token."""
    return HSDESClient(token)


# Default client using server-side config only (optional local/dev fallback).
hsdes = HSDESClient()
