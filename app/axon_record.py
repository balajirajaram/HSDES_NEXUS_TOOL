"""Axon record fetch bridge.

Pull a linked Axon recording's metadata (platform / stepping / plugin / config)
and any log content files, and fold them into the log decode so a fresh HSD's
Axon evidence is triaged automatically. Adapted from the intel-prompt-plugin
``analyzing-axon-record`` skill.

Fetch order (first available wins), all read-only:
  1. ``axon`` CLI  — ``axon download --id <UUID> --path <dir>`` then read record.json
     (looked up on PATH, at ``~/bin/axon``, or ``config.AXON_CLI_PATH``).
  2. If the CLI is not present, the record is flagged as not-fetched with the
     reason, and the caller can fall back to the Geni AxonTool over MCP.

Never creates or modifies HSDES/Axon links.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List

import httpx

from .config import config

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_LOG_EXT = (".log", ".txt", ".ewl", ".mca", ".serial", ".sol", ".dmesg", ".json")
_MAX_FILE = 4_000_000


def canonical_axon_url(uuid: str) -> str:
    return f"https://axon.intel.com/app/view/{uuid}"


def _find_cli() -> str:
    """Locate the axon CLI binary, or '' if unavailable."""
    if config.AXON_CLI_PATH and os.path.isfile(config.AXON_CLI_PATH):
        return config.AXON_CLI_PATH
    found = shutil.which("axon")
    if found:
        return found
    home = os.path.expanduser("~/bin/axon")
    return home if os.path.isfile(home) else ""


def _extract_meta(record: Dict[str, Any]) -> Dict[str, str]:
    """Defensively pull platform / stepping / plugin / config from record.json."""
    def dig(*names: str) -> str:
        for n in names:
            if isinstance(record, dict) and record.get(n):
                return str(record[n])
        # one level deep
        for v in (record.values() if isinstance(record, dict) else []):
            if isinstance(v, dict):
                for n in names:
                    if v.get(n):
                        return str(v[n])
        return ""

    return {
        "platform": dig("platform", "product", "project", "soc", "family"),
        "stepping": dig("stepping", "step", "silicon_stepping", "revision"),
        "plugin": dig("plugin", "plugin_name", "test", "testName", "content"),
        "config": dig("config", "configuration", "topology", "bios", "ifwi"),
    }


def _read_content_files(record_dir: str) -> List[Dict[str, str]]:
    """Read small text/log content files sitting next to record.json."""
    out: List[Dict[str, str]] = []
    for root, _dirs, files in os.walk(record_dir):
        for name in files:
            if name == "record.json" or not name.lower().endswith(_LOG_EXT):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > _MAX_FILE:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    out.append({"name": name, "text": f.read(_MAX_FILE)})
            except Exception:
                continue
            if len(out) >= 8:
                return out
    return out


def _download_sync(uuid: str) -> Dict[str, Any]:
    """Download one Axon record via the CLI and parse it. Read-only."""
    url = canonical_axon_url(uuid)
    if not _UUID_RE.match(uuid):
        return {"uuid": uuid, "url": url, "available": False, "note": "invalid UUID"}
    cli = _find_cli()
    if not cli:
        return {"uuid": uuid, "url": url, "available": False,
                "note": "axon CLI not found — install ~/bin/axon or configure the "
                        "Geni AxonTool (GENI_MCP_URL) to auto-fetch the recording"}
    tmp = tempfile.mkdtemp(prefix=f"axon_{uuid[:8]}_")
    try:
        proc = subprocess.run([cli, "download", "--id", uuid, "--path", tmp],
                              capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            note = (proc.stderr or proc.stdout or "download failed").strip()[:200]
            return {"uuid": uuid, "url": url, "available": False, "note": note}
        rec_dir = os.path.join(tmp, uuid)
        rec_json = os.path.join(rec_dir, "record.json")
        record: Dict[str, Any] = {}
        if os.path.isfile(rec_json):
            try:
                with open(rec_json, "r", encoding="utf-8", errors="replace") as f:
                    record = json.load(f)
            except Exception:
                record = {}
        meta = _extract_meta(record)
        content = _read_content_files(rec_dir)
        return {
            "uuid": uuid, "url": url, "available": True, "source": "cli",
            **meta,
            "content_files": [c["name"] for c in content],
            "log_texts": [c["text"] for c in content],
        }
    except subprocess.TimeoutExpired:
        return {"uuid": uuid, "url": url, "available": False, "note": "download timed out"}
    except Exception as exc:  # pragma: no cover - environment guard
        return {"uuid": uuid, "url": url, "available": False, "note": str(exc)[:200]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fetch_all_sync(uuids: List[str]) -> List[Dict[str, Any]]:
    return [_download_sync(u) for u in uuids[:4]]


async def fetch_axon_records(uuids: List[str]) -> List[Dict[str, Any]]:
    """Fetch linked Axon records. Tries the Geni AxonTool (AXON_GENI_TOKEN) first
    for SVTools failure signatures, then falls back to the axon CLI for full log
    content. Returns a status entry per UUID."""
    uuids = [u for u in dict.fromkeys(uuids) if u]
    if not uuids:
        return []
    records = await asyncio.to_thread(_fetch_all_sync, uuids)
    # Geni AxonTool enrichment: re-read from env each call (token refreshed by
    # refresh_axon_token.ps1 / run.ps1 on startup and written back to .env).
    import os as _os
    # Reload .env so a freshly-refreshed token is picked up without restart.
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(override=True)
    except Exception:
        pass
    geni_token = _os.getenv("AXON_GENI_TOKEN", "") or config.AXON_GENI_TOKEN
    if geni_token:
        for rec in records:
            if rec.get("available"):
                continue  # already have full data from CLI
            try:
                sigs = await _geni_axon_signatures(rec["uuid"], geni_token)
                if sigs:
                    rec["svtools_signatures"] = "; ".join(sigs)
                    rec["available"] = True
                    rec["source"] = "geni"
                    rec["note"] = ""
            except Exception:
                pass
    return records


async def _geni_axon_signatures(uuid: str, token: str) -> List[str]:
    """Fetch SVTools failure signatures from the Axon record API.
    Endpoint: GET https://axon.intel.com/api/v1/record/{uuid} with Bearer token.
    HW.* signatures are scattered through the JSON — extract all unique ones.
    """
    try:
        # verify=False mirrors the Kerberos/SSPI pattern used elsewhere in the tool
        # and avoids SSL cert issues with Intel internal services.
        async with httpx.AsyncClient(timeout=30, verify=False) as cx:
            resp = await cx.get(
                f"https://axon.intel.com/api/v1/record/{uuid}",
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/json"})
            resp.raise_for_status()
            full_json = resp.text
            # Extract all unique HW.* SVTools-style signature tokens
            pat = re.compile(r"HW\.[A-Z0-9][A-Z0-9._]+")
            raw_sigs = list(dict.fromkeys(pat.findall(full_json)))
            # Filter out too-short / generic tokens (e.g. HW.MCE.UBOX alone)
            return [s for s in raw_sigs if len(s) > 12][:10]
    except Exception:
        return []
