"""HTTPS reader that pulls HSD content from an internal MCP server (e.g. the Geni
agent-gateway) using the signed-in user's OAuth bearer token.

Implements a minimal MCP **Streamable HTTP** JSON-RPC client:
  1. POST initialize            -> capture Mcp-Session-Id
  2. POST notifications/initialized
  3. POST tools/call {name, arguments}

The tool result text is returned as `full_text` so the analyzer can reason over
the full ticket exactly like the REST reader. On ANY failure this returns an
`error` dict so the caller can fall back to HSDES REST (MCP-first, REST-fallback).

NOTE: exact tool name / argument schema varies per MCP server. `MCP_TOOL_NAME`
and the argument mapping in `read_article` may need a one-line tweak to match the
server's actual `tools/list` contract. Validate against the live endpoint once a
real OAuth token is available.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

import httpx

from .config import config


class MCPReader:
    def __init__(self, token: Optional[str] = None):
        self.url = (config.MCP_SERVER_URL or "").rstrip("/")
        self.token = (token or "").strip()
        self.tool_name = config.MCP_TOOL_NAME
        self.enabled = bool(self.url and self.token)

    def _headers(self, session_id: Optional[str] = None) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if session_id:
            h["Mcp-Session-Id"] = session_id
        return h

    @staticmethod
    def _parse(resp: httpx.Response) -> Dict[str, Any]:
        """Parse a JSON or SSE (text/event-stream) MCP response."""
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    if payload and payload != "[DONE]":
                        try:
                            return json.loads(payload)
                        except Exception:
                            continue
            return {}
        try:
            return resp.json()
        except Exception:
            return {}

    async def read_article(self, hsd_id: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"id": hsd_id, "error": "MCP reader not configured"}
        try:
            async with httpx.AsyncClient(timeout=90) as cx:
                # 1) initialize
                init = await cx.post(self.url, headers=self._headers(), json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": config.MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "auto-hsd-analyser", "version": "1.0"},
                    },
                })
                init.raise_for_status()
                session_id = init.headers.get("mcp-session-id") or init.headers.get("Mcp-Session-Id")

                # 2) initialized notification
                await cx.post(self.url, headers=self._headers(session_id), json={
                    "jsonrpc": "2.0", "method": "notifications/initialized",
                })

                # 3) call the HSD tool
                call = await cx.post(self.url, headers=self._headers(session_id), json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": self.tool_name,
                        "arguments": {
                            "message": (
                                f"Read HSD ticket {hsd_id} fully and return title, "
                                f"family, component, status, owner, priority, the full "
                                f"description and the latest debug comments."
                            ),
                        },
                    },
                })
                call.raise_for_status()
                data = self._parse(call)
        except Exception as exc:
            return {"id": hsd_id, "error": f"MCP call failed: {exc}"}

        text = self._extract_text(data)
        if not text:
            return {"id": hsd_id, "error": "MCP returned no content"}
        return {
            "id": hsd_id,
            "title": "",           # LLM parses specifics from full_text
            "description": "",
            "comments": [],
            "full_text": text,
            "raw": data,
            "source": "MCP",
        }

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        """Pull the text out of an MCP tools/call result envelope."""
        result = data.get("result", data)
        content = result.get("content") if isinstance(result, dict) else None
        parts: List[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    parts.append(item)
        elif isinstance(result, dict) and isinstance(result.get("text"), str):
            parts.append(result["text"])
        elif isinstance(data.get("final_answer"), str):
            parts.append(data["final_answer"])
        return "\n".join(p for p in parts if p).strip()


def get_mcp_reader(token: Optional[str] = None) -> MCPReader:
    return MCPReader(token)
