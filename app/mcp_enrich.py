"""Optional MCP enrichment — query internal Geni HSDES and Co-Design HSDES agent
gateways over MCP (Streamable HTTP JSON-RPC) and fold their answers into the
ticket context, so a report is grounded in HSDES REST + Geni + Co-Design at once.

Each source is independent and OFF unless its ``*_MCP_URL`` + ``*_MCP_TOKEN`` env
vars are set (see app/config.py). On ANY failure a source returns an ``error`` and
is simply skipped — enrichment never blocks the core REST-based analysis.

The MCP handshake (initialize -> notifications/initialized -> tools/call) mirrors
the validated client in option-c-sso/app/mcp_reader.py. Exact tool name / argument
schema varies per gateway; override via ``GENI_MCP_TOOL`` / ``CODESIGN_MCP_TOOL``.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional

import httpx

from .config import config


class _MCPSource:
    """A single MCP gateway (one tool call per HSD)."""

    def __init__(self, name: str, url: str, tool: str, token: str,
                 category: str = "general"):
        self.name = name
        self.url = (url or "").rstrip("/")
        self.tool = tool
        self.token = (token or "").strip()
        # "general" sources run whenever enabled; gated sources ("bios", "kernel",
        # "redfish") run only when the ticket evidence is relevant to them.
        self.category = category
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
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    if payload and payload != "[DONE]":
                        try:
                            import json
                            return json.loads(payload)
                        except Exception:
                            continue
            return {}
        try:
            return resp.json()
        except Exception:
            return {}

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
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

    async def ask(self, hsd_id: str, prompt: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"source": self.name, "error": "not configured"}
        try:
            async with httpx.AsyncClient(timeout=90) as cx:
                init = await cx.post(self.url, headers=self._headers(), json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": config.MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "auto-hsd-analyser", "version": "1.0"},
                    },
                })
                init.raise_for_status()
                sid = (init.headers.get("mcp-session-id")
                       or init.headers.get("Mcp-Session-Id"))
                await cx.post(self.url, headers=self._headers(sid), json={
                    "jsonrpc": "2.0", "method": "notifications/initialized",
                })
                call = await cx.post(self.url, headers=self._headers(sid), json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": self.tool,
                               "arguments": {"message": prompt, "query": prompt}},
                })
                call.raise_for_status()
                data = self._parse(call)
        except Exception as exc:  # pragma: no cover - network guard
            return {"source": self.name, "error": f"{exc}"}
        text = self._extract_text(data)
        if not text:
            return {"source": self.name, "error": "no content"}
        return {"source": self.name, "text": text}


class _SpecsSource(_MCPSource):
    """Intel Specs (docs.intel.com HAS / SOC guide / EDS-R) reader.

    Differs from a plain _MCPSource: its tool (find_document/search_in_document)
    takes ``{query, project}`` — not ``{message}`` — and it scopes the search to
    the detected product's docs.intel.com project when known.
    """

    def __init__(self, url: str, tool: str, token: str, project: str = ""):
        super().__init__("Intel Specs (HAS/SOC guide)", url, tool, token,
                         category="specs")
        self.project = (project or "").strip()

    async def ask(self, hsd_id: str, prompt: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"source": self.name, "error": "not configured"}
        args: Dict[str, Any] = {"query": prompt}
        if self.project:
            args["project"] = self.project
        try:
            async with httpx.AsyncClient(timeout=90) as cx:
                init = await cx.post(self.url, headers=self._headers(), json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": config.MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "auto-hsd-analyser", "version": "1.0"},
                    },
                })
                init.raise_for_status()
                sid = (init.headers.get("mcp-session-id")
                       or init.headers.get("Mcp-Session-Id"))
                await cx.post(self.url, headers=self._headers(sid), json={
                    "jsonrpc": "2.0", "method": "notifications/initialized",
                })
                call = await cx.post(self.url, headers=self._headers(sid), json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": self.tool, "arguments": args},
                })
                call.raise_for_status()
                data = self._parse(call)
        except Exception as exc:  # pragma: no cover - network guard
            return {"source": self.name, "error": f"{exc}"}
        text = self._extract_text(data)
        if not text:
            return {"source": self.name, "error": "no content"}
        return {"source": self.name, "text": text}


def _sources(geni_token: str = "", codesign_token: str = "",
             product: str = "") -> List[_MCPSource]:
    try:
        from .products import specs_project
        specs_proj = specs_project(product)
    except Exception:
        specs_proj = ""
    return [
        _MCPSource("Geni HSDES", config.GENI_MCP_URL, config.GENI_MCP_TOOL,
                   geni_token or config.GENI_MCP_TOKEN),
        _MCPSource("Co-Design HSDES", config.CODESIGN_MCP_URL, config.CODESIGN_MCP_TOOL,
                   codesign_token or config.CODESIGN_MCP_TOKEN),
        # DCG Marketplace debug agents (optional; each OFF unless URL+token set).
        _MCPSource("Wiki KB", config.WIKI_MCP_URL, config.WIKI_MCP_TOOL,
                   config.WIKI_MCP_TOKEN, category="general"),
        _MCPSource("BIOS/S3M expert", config.BIOS_MCP_URL, config.BIOS_MCP_TOOL,
                   config.BIOS_MCP_TOKEN, category="bios"),
        _MCPSource("Linux kernel crash", config.KERNEL_MCP_URL, config.KERNEL_MCP_TOOL,
                   config.KERNEL_MCP_TOKEN, category="kernel"),
        _MCPSource("Redfish/iDRAC", config.REDFISH_MCP_URL, config.REDFISH_MCP_TOOL,
                   config.REDFISH_MCP_TOKEN, category="redfish"),
        # Intel Specs (HAS / SOC guide / EDS-R) — SOC-guide/HAS validation for
        # DMR/COR/etc. Scoped to the product's docs.intel.com project when known.
        _SpecsSource(config.SPECS_MCP_URL, config.SPECS_MCP_TOOL,
                     config.SPECS_MCP_TOKEN, project=specs_proj),
    ]



# Keyword gates deciding when a specialised (non-"general") source is relevant.
_CATEGORY_GATES = {
    "bios": re.compile(
        r"\bbios\b|ifwi|\bpost\b|checkpoint|boot[\s-]?hang|s3m|rc[\s_-]?fatal|"
        r"mcheck|dxe|\bpei\b|memory training|cold\s?reset|\bcpld\b|bmc\s?boot", re.I),
    "kernel": re.compile(
        r"kernel|panic|oops|call\s?trace|segfault|\bvfio\b|\bidxd\b|dmesg|"
        r"null\s?pointer|soft\s?lockup|rcu\s?stall|\bBUG:\b|linux|driver", re.I),
    "redfish": re.compile(
        r"redfish|idrac|\bbmc\b|\bsel\b|out[\s-]?of[\s-]?band|power\s?(?:state|cycle)|"
        r"sensor|thermal|unreachable|hung|no\s?ssh|failed\s?node", re.I),
    # Specs (HAS / SOC guide / EDS-R) — consulted for MCA/RAS/register/architecture
    # questions where the SOC guide or HAS defines correct behaviour.
    "specs": re.compile(
        r"\bmca\b|mcacod|mscod|\bbank\s?\d|machine\s?check|\bras\b|\bcha\b|\bupi\b|"
        r"\bpunit\b|\bllc\b|mcchan|\bmse\b|\beds\b|\bhas\b|soc\s?guide|register|"
        r"errata|architecture|ierr|caterr|shutdown\s?error", re.I),
}


def _relevant_categories(text: str) -> set:
    hay = text or ""
    return {cat for cat, pat in _CATEGORY_GATES.items() if pat.search(hay)}


def enrichment_enabled(geni_token: str = "", codesign_token: str = "") -> bool:
    return any(s.enabled for s in _sources(geni_token, codesign_token))


async def enrich(hsd_id: str, symptoms: str,
                 geni_token: str = "", codesign_token: str = "",
                 context_text: str = "", product: str = "") -> List[Dict[str, Any]]:
    """Query every configured MCP source in parallel; return successful answers.

    "general" sources (HSDES, Wiki KB) run whenever enabled. Specialised sources
    (BIOS/S3M, Linux kernel crash, Redfish/iDRAC, Specs/HAS) run only when the
    ticket text / symptoms indicate they are relevant, so they're consulted on
    need — not always. ``product`` scopes the Specs source to that project.
    """
    relevant = _relevant_categories(f"{symptoms}\n{context_text}")
    sources = [
        s for s in _sources(geni_token, codesign_token, product)
        if s.enabled and (s.category == "general" or s.category in relevant)
    ]
    if not sources:
        return []
    prompt = (f"Read HSD ticket {hsd_id} and summarise the failure, latest debug "
              f"findings, suspected root cause, and any linked recordings or fixes. "
              f"Reported symptom: {symptoms}")
    results = await asyncio.gather(*(s.ask(hsd_id, prompt) for s in sources),
                                   return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, dict) and r.get("text"):
            out.append(r)
    return out
