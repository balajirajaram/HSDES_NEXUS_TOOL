"""AutoHSD Phase 2 — live node triage.

A one-liner AutoHSD ticket only carries a title (e.g.
``[Cluster][CTRLS GNR_SP B3][cs16ca101ks1206][2S] Node hang``). This module
parses the node hostname from that title, SSHes into the node, collects the RAS /
boot logs (dmesg, journalctl, mcelog/messages, IPMI SEL, EDAC/ras-mc), and feeds
them into the analyzer so a full root-cause report + ticket comment is produced.

If the node is unreachable ("dead"), it reports that the node is down instead.

Secrets (SSH password) are read ONLY from the environment via ``config`` and are
never logged, returned to the UI, or written to any report/session file.
"""

import asyncio
import re
import socket
from typing import Any, Dict, List, Optional, Tuple

from .config import config

try:
    import paramiko
    _PARAMIKO = True
except Exception:  # pragma: no cover
    _PARAMIKO = False

# Read-only log collection commands (name -> shell command). Tail-bounded so a
# huge journal can't blow up memory. All are best-effort (2>/dev/null).
_LOG_CMDS: List[Tuple[str, str]] = [
    ("dmesg", "dmesg -T 2>/dev/null | tail -n 4000"),
    ("journalctl", "journalctl -k -n 4000 --no-pager 2>/dev/null"),
    ("mcelog", "cat /var/log/mcelog 2>/dev/null | tail -n 2000"),
    ("messages", "(cat /var/log/messages 2>/dev/null || cat /var/log/syslog 2>/dev/null) | tail -n 4000"),
    ("ipmi_sel", "ipmitool sel elist 2>/dev/null | tail -n 800"),
    ("edac", "grep -r . /sys/devices/system/edac/mc/*/ 2>/dev/null | tail -n 500"),
    ("ras_mc", "ras-mc-ctl --errors 2>/dev/null | tail -n 500"),
]

# A hostname-like bracket token: starts with letters, followed by digits, and has
# at least 3 digits overall (rules out rev/config codes like B3, 2S, UPLR6).
_HOST_TOKEN = re.compile(r"^[a-z]{2,}\d[a-z0-9]*\d$", re.I)


def extract_node_host(title: str) -> Optional[str]:
    """Parse the SUT node hostname from an HSD title. The node id is one of the
    bracketed tokens, e.g. ``[cs16ca101ks1206]``. Returns lowercase host or None."""
    if not title:
        return None
    for tok in re.findall(r"\[([^\]]+)\]", title):
        t = tok.strip()
        if " " in t or len(t) < 8:
            continue
        if _HOST_TOKEN.fullmatch(t) and len(re.findall(r"\d", t)) >= 3:
            return t.lower()
    # Fallback: a bare cs-prefixed host anywhere in the title.
    m = re.search(r"\b(cs\d[a-z0-9]{5,})\b", title, re.I)
    return m.group(1).lower() if m else None


def _resolve_host(host: str) -> str:
    if config.SUT_SSH_DOMAIN and "." not in host:
        return f"{host}.{config.SUT_SSH_DOMAIN.lstrip('.')}"
    return host


def _tcp_open(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _collect_sync(host: str) -> Dict[str, Any]:
    port = config.SUT_SSH_PORT
    fqdn = _resolve_host(host)
    if not _tcp_open(fqdn, port):
        return {"reachable": False, "host": fqdn,
                "error": "SSH port unreachable (node down / powered off / no route)"}
    if not _PARAMIKO:
        return {"reachable": False, "host": fqdn, "error": "paramiko is not installed"}
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw: Dict[str, Any] = dict(hostname=fqdn, port=port, username=config.SUT_SSH_USER,
                              timeout=15, banner_timeout=20, auth_timeout=20)
    try:
        if config.SUT_SSH_KEY:
            cli.connect(key_filename=config.SUT_SSH_KEY, **kw)
        else:
            cli.connect(password=config.SUT_SSH_PASSWORD, look_for_keys=False,
                        allow_agent=False, **kw)
    except Exception as exc:
        # Never include the password; only the exception type/host.
        return {"reachable": False, "host": fqdn,
                "error": f"SSH connect/auth failed ({type(exc).__name__})"}
    logs: Dict[str, str] = {}
    try:
        for name, cmd in _LOG_CMDS:
            try:
                _in, out, _err = cli.exec_command(cmd, timeout=30)
                logs[name] = out.read().decode("utf-8", "replace")
            except Exception as exc:
                logs[name] = f"[collect error: {type(exc).__name__}]"
    finally:
        cli.close()
    combined = "\n".join(f"===== {n} =====\n{t}" for n, t in logs.items() if t.strip())
    return {"reachable": True, "host": fqdn, "logs": logs, "combined": combined}


async def collect_node_logs(host: str) -> Dict[str, Any]:
    """Reachability check + SSH log collection, off the event loop."""
    return await asyncio.to_thread(_collect_sync, host)


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _node_down_comment(host: str, err: str) -> str:
    return (
        "<b>NEXUS AutoHSD Triage</b>\n"
        f"<i>Attempted live log collection from node <b>{_esc(host)}</b>.</i>\n"
        "<ul>"
        f"<li><b>Node status:</b> DOWN / unreachable over SSH — {_esc(err)}</li>"
        "<li>No live logs could be collected. Check power / BMC state and re-run "
        "AutoHSD triage once the node is back online.</li>"
        "</ul>"
    )


async def triage_auto_hsd(hsd_id: str, post: bool = False) -> Dict[str, Any]:
    """Full AutoHSD flow: read the ticket title, SSH the named node, collect logs,
    analyze, and (optionally) post the RCA comment. When ``post`` is False nothing
    is written to HSDES — the comment is returned for review (dry-run)."""
    from .analyzer import analyze, update_hsd_report
    from .hsdes_client import HSDESClient

    hsd_id = re.sub(r"\D", "", str(hsd_id))
    client = HSDESClient()
    target = await client.get_article(hsd_id)
    if not target or target.get("error"):
        return {"ok": False, "hsd_id": hsd_id,
                "error": (target or {}).get("error", "HSD not found")}
    title = target.get("title", "") or ""
    host = extract_node_host(title)
    if not host:
        return {"ok": False, "hsd_id": hsd_id, "host": None, "title": title,
                "error": "Could not parse a node hostname from the HSD title"}

    node = await collect_node_logs(host)
    if not node.get("reachable"):
        comment = _node_down_comment(node.get("host", host), node.get("error", ""))
        out = {"ok": True, "hsd_id": hsd_id, "host": node.get("host", host),
               "node_down": True,
               "message": f"Node {node.get('host', host)} is down / unreachable.",
               "comment_html": comment}
        if post:
            out["posted"] = await client.add_comment(hsd_id, comment)
        return out

    collected = [k for k, v in node["logs"].items() if v.strip()]
    analysis = await analyze(hsd_id, f"AutoHSD triage: {title}",
                             log_text=node["combined"], fetch_attachments=True)
    upd = await update_hsd_report(hsd_id, result=analysis, dry_run=not post)
    return {**analysis, "ok": True, "hsd_id": hsd_id, "host": node["host"],
            "node_down": False, "autohsd": True, "logs_collected": collected,
            "comment_html": upd.get("comment_html"),
            "posted": (upd if post else None)}
