#!/usr/bin/env python3
"""
statusscope_parser.py
=====================
Parse a StatusScope ``*-intel-svtools-report-v1.json`` report into a compact,
AI-friendly structured record for BugScout.

StatusScope is the PythonSV failure-time capture framework.  Its canonical
output is a single JSON document (the HTML report is just a rendering of the
same object), shaped as::

    {"format": "full", "format_version": 3, "name": "status_scope",
     "sub_reports": [ {sub_report}, ... ]}

Each sub-report is one plugin/analyzer namespace::

    {"name": "status_scope.analyzers.error",   # dotted namespace
     "type_name": null, "instance": null,
     "tables":   [ {pandas orient=table object}, ... ],
     "summary":  "markdown string" | null,
     "insights": [ {insight}, ... ],
     "next_steps": [ ... ]}

**Insights are the high-value payload.**  Each insight looks like::

    {"ip_domain": "PCIe6 Controller", "ip_domain_instance": null,
     "location": "none", "message": "...", "name": "...",
     "side_effect": null, "source": "namednodes",
     "type": "HW.CFG.ERR", "url": "https://hsdes.intel.com/.../#/22021086054"}

This module is **stdlib-only** — pandas ``orient=table`` JSON is decoded by
iterating ``schema.fields`` + ``data`` directly, so no pandas dependency.

Usage (standalone)::

    python statusscope_parser.py <report.json>          # human summary
    python statusscope_parser.py <report.json> --json    # compact JSON payload

Programmatic::

    from statusscope_parser import parse_report
    record = parse_report("019d...-intel-svtools-report-v1.json")
    payload = record.to_summary_dict()
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# Insight ``type`` codes with an explicit triage rank.  This is only a
# refinement over the prefix-based ordering in ``insight_priority`` below —
# any code not listed here still sorts by its HW/SW/other prefix, so reports
# that introduce new type codes are handled without edits.
_INSIGHT_TYPE_PRIORITY = {
    "HW.KNOWN_ISSUE": 0,
    "HW.RELATED_ISSUE": 1,
    "HW.CFG.ERR": 2,
    "HW.CFG_ERR": 2,
    "SW.FW.ERR": 10,
    "SW.ERR": 11,
}


def insight_priority(itype: str) -> int:
    """Triage rank for an insight type. Lower sorts first.

    Known codes use their explicit rank; unknown codes fall back to their
    domain prefix so any ``HW.*`` outranks any ``SW.*`` outranks everything
    else — keeping the ordering sensible for reports with unseen type codes.
    """
    if itype in _INSIGHT_TYPE_PRIORITY:
        return _INSIGHT_TYPE_PRIORITY[itype]
    upper = itype.upper()
    if upper.startswith("HW."):
        return 5
    if upper.startswith("SW."):
        return 15
    return 50


# Substrings that mark a namespace's tables as high-value (surfaced in the
# compact payload).  Matched against the *plugin* segment of the dotted
# namespace — i.e. the segment right after the tier
# (``status_scope.<tier>.<plugin>...``).  This catches the plugin and all its
# subsections (e.g. ``analyzers.error`` and ``analyzers.error.IP Errors``, or a
# future ``analyzers.crashlog``) while keeping deep per-instance register dumps
# (e.g. ``analyzers.ccf.Ccf.socket0_...cbo0.nd_cbo_mca_status``) out of the
# compact payload.  The full data is always available via ``to_dict()``.
_HIGH_VALUE_TABLE_KEYWORDS = (
    "error",
    "sideband",
    "mca",
    "crashlog",
    "known_sightings",
    "fault",
    "hang",
    "assert",
)


def is_high_value_namespace(namespace: str) -> bool:
    """True if a namespace's tables should appear in the compact payload.

    Matches high-value keywords against the plugin segment of the namespace
    (``status_scope.<tier>.<plugin>``), so plugin-level error/mca/sideband/etc.
    namespaces and their subsections qualify, but deep per-instance register
    tables under an unrelated plugin do not.
    """
    segments = namespace.split(".")
    if len(segments) < 3:
        return False
    plugin = segments[2].lower()
    return any(kw in plugin for kw in _HIGH_VALUE_TABLE_KEYWORDS)


@dataclass
class StatusScopeInsight:
    """One normalized StatusScope insight."""

    type: str = ""
    message: str = ""
    ip_domain: str = ""
    source: str = ""
    url: str = ""
    location: str = ""
    side_effect: str = ""
    namespace: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("raw", None)
        return payload


@dataclass
class StatusScopeRecord:
    """Structured view of a StatusScope svtools report."""

    source_path: str = ""
    report_name: str = ""
    format_version: int = 0
    platform: str = "Unknown"
    stepping: str = ""
    qdf: str = ""
    sku: str = ""
    probe_type: str = ""
    run_command: str = ""
    run_time: str = ""
    tool_versions: dict[str, str] = field(default_factory=dict)
    insights: list[StatusScopeInsight] = field(default_factory=list)
    namespaces: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "report_name": self.report_name,
            "format_version": self.format_version,
            "platform": self.platform,
            "stepping": self.stepping,
            "qdf": self.qdf,
            "sku": self.sku,
            "probe_type": self.probe_type,
            "run_command": self.run_command,
            "run_time": self.run_time,
            "tool_versions": self.tool_versions,
            "insights": [i.to_dict() for i in self.insights],
            "namespaces": self.namespaces,
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """Compact, high-value payload suitable for feeding to a model.

        Includes metadata + all insights + the decoded tables from any
        high-value namespace (error/sideband/mca/crashlog/known-sightings and
        similar, including sub-namespaces such as ``error.IP Errors``) — never
        the whole report blob.  Bulk metadata tables (fuse info, device lists,
        package inventories) stay out of the compact payload but remain
        available via ``to_dict()``/``namespaces``.
        """
        tables: dict[str, list[dict[str, Any]]] = {}
        for ns, sub in self.namespaces.items():
            decoded = sub.get("tables", [])
            if decoded and is_high_value_namespace(ns):
                tables[ns] = decoded
        return {
            "platform": self.platform,
            "stepping": self.stepping,
            "qdf": self.qdf,
            "sku": self.sku,
            "probe_type": self.probe_type,
            "run_command": self.run_command,
            "run_time": self.run_time,
            "insight_count": len(self.insights),
            "insights": [i.to_dict() for i in self.insights],
            "tables": tables,
            "hsd_links": self.hsd_links(),
        }

    def hsd_links(self) -> list[str]:
        """Unique HSD article URLs referenced by insights."""
        seen: list[str] = []
        for ins in self.insights:
            url = ins.url or ""
            if "hsdes.intel.com" in url and url not in seen:
                seen.append(url)
        return seen


# --------------------------------------------------------------------------- #
# Loading + flattening
# --------------------------------------------------------------------------- #

def load_report(path: str | Path) -> dict[str, Any]:
    """Load the svtools report JSON. Raises ValueError if it is not a report."""
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("name") != "status_scope":
        raise ValueError(
            f"{p} is not a StatusScope report "
            "(expected top-level name == 'status_scope')"
        )
    return payload


def flatten_sub_reports(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return sub-reports keyed by their dotted ``name`` namespace."""
    out: dict[str, dict[str, Any]] = {}
    for sub in payload.get("sub_reports", []) or []:
        name = sub.get("name")
        if name:
            out[name] = sub
    return out


# --------------------------------------------------------------------------- #
# Table decoding (pandas orient=table, stdlib only)
# --------------------------------------------------------------------------- #

def decode_table(table_obj: dict[str, Any]) -> dict[str, Any]:
    """Decode one pandas ``orient=table`` object into columns + rows.

    Returns ``{"title", "type", "columns", "rows"}``.  ``rows`` is already a
    list of record dicts (that is how orient=table stores ``data``), so no
    reshaping is needed — we just surface the column order from the schema.

    Robust to variants where ``table`` is a bare list of rows (some AD_HOC
    tables) rather than a ``{schema, data}`` object.
    """
    if not isinstance(table_obj, dict):
        return {"title": "", "type": "", "columns": [], "rows": []}
    inner = table_obj.get("table", {}) or {}
    if isinstance(inner, list):
        rows = inner
        columns: list[Any] = []
    elif isinstance(inner, dict):
        schema = inner.get("schema", {}) or {}
        fields = schema.get("fields", []) or []
        columns = [f.get("name") for f in fields if isinstance(f, dict) and f.get("name") is not None]
        rows = inner.get("data", []) or []
    else:
        rows, columns = [], []
    return {
        "title": table_obj.get("title", ""),
        "type": table_obj.get("type", ""),
        "columns": columns,
        "rows": rows,
    }


def decode_tables(sub_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Decode every table in a sub-report."""
    return [decode_table(t) for t in (sub_report.get("tables") or [])]


def find_table(
    namespaces: dict[str, dict[str, Any]], namespace: str, title: str
) -> dict[str, Any] | None:
    """Find a decoded table by namespace + (case-insensitive) title."""
    sub = namespaces.get(namespace)
    if not sub:
        return None
    want = title.strip().lower()
    for tbl in decode_tables(sub):
        if str(tbl.get("title", "")).strip().lower() == want:
            return tbl
    return None


# --------------------------------------------------------------------------- #
# Insight extraction
# --------------------------------------------------------------------------- #

def _norm_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return "" if value.strip().lower() == "none" else value
    return str(value)


def extract_insights(sub_reports: dict[str, dict[str, Any]]) -> list[StatusScopeInsight]:
    """Merge, normalize, dedup and priority-sort insights across sub-reports."""
    merged: list[StatusScopeInsight] = []
    seen: set[tuple[str, str, str]] = set()
    for namespace, sub in sub_reports.items():
        for raw in sub.get("insights", []) or []:
            if not isinstance(raw, dict):
                continue
            itype = _norm_str(raw.get("type"))
            message = _norm_str(raw.get("message")) or _norm_str(raw.get("name"))
            url = _norm_str(raw.get("url"))
            key = (itype, message, url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                StatusScopeInsight(
                    type=itype,
                    message=message,
                    ip_domain=_norm_str(raw.get("ip_domain")),
                    source=_norm_str(raw.get("source")),
                    url=url,
                    location=_norm_str(raw.get("location")),
                    side_effect=_norm_str(raw.get("side_effect")),
                    namespace=namespace,
                    raw=raw,
                )
            )

    def sort_key(ins: StatusScopeInsight) -> tuple[int, str]:
        return (insight_priority(ins.type), ins.message.lower())

    merged.sort(key=sort_key)
    return merged


# --------------------------------------------------------------------------- #
# Metadata extraction (best-effort, never raises)
# --------------------------------------------------------------------------- #

def _platform_from_openipc(namespaces: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Return (platform, probe_type) best-effort from the openipc analyzer."""
    sub = namespaces.get("status_scope.analyzers.openipc")
    if not sub:
        return "", ""
    platform, probe = "", ""
    for tbl in decode_tables(sub):
        for row in tbl.get("rows", []):
            if not isinstance(row, dict):
                continue
            platform = platform or _norm_str(row.get("platformtype"))
            probe = probe or _norm_str(row.get("probetype"))
    # Fall back to the summary line "Report of <platform> platformtype ...".
    if not platform:
        summary = _norm_str(sub.get("summary"))
        marker = "Report of "
        if marker in summary:
            tail = summary.split(marker, 1)[1]
            platform = tail.split(" platformtype", 1)[0].strip()
    return platform, probe


def _fuse_info(namespaces: dict[str, dict[str, Any]]) -> tuple[str, str, str]:
    """Return (qdf, sku, stepping) from the sys_cfg 'Fuse Info' table."""
    tbl = find_table(namespaces, "status_scope.analyzers.sys_cfg", "Fuse Info")
    if not tbl:
        return "", "", ""
    qdf = sku = stepping = ""
    for row in tbl.get("rows", []):
        if not isinstance(row, dict):
            continue
        qdf = qdf or _norm_str(row.get("qdf"))
        sku = sku or _norm_str(row.get("sku_type")) or _norm_str(row.get("sku"))
        stepping = stepping or _norm_str(row.get("stepping")) or _norm_str(
            row.get("fuse_rev")
        )
    return qdf, sku, stepping


def _stepping_from_device_list(namespaces: dict[str, dict[str, Any]]) -> str:
    tbl = find_table(namespaces, "status_scope.analyzers.openipc", "Device List")
    if not tbl:
        return ""
    for row in tbl.get("rows", []):
        if isinstance(row, dict):
            step = _norm_str(row.get("Stepping"))
            if step:
                return step
    return ""


# Curated set of triage-relevant tools (matched by exact package name).
_KEY_TOOLS = {
    "pysvtools.status_scope",
    "pysvtools.crashlog",
    "pysvtools.debug_mca",
    "pysvtools.nanoscope",
    "pysvtools.state_dump",
    "pysvtools.openipc_utils",
    "pysvtools.run_control",
    "namednodes",
    "svtools.report",
    "svtools.pysv2axon",
}


def _tool_versions(namespaces: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Pull versions for the handful of tools relevant to triage."""
    tbl = find_table(
        namespaces, "status_scope.analyzers.python_packages", "Python Packages"
    )
    if not tbl:
        # Title may differ; scan any table in the namespace with package/version cols.
        sub = namespaces.get("status_scope.analyzers.python_packages")
        if sub:
            for candidate in decode_tables(sub):
                if {"package", "version"} <= {c.lower() for c in candidate.get("columns", [])}:
                    tbl = candidate
                    break
    if not tbl:
        return {}
    versions: dict[str, str] = {}
    for row in tbl.get("rows", []):
        if not isinstance(row, dict):
            continue
        pkg = _norm_str(row.get("package"))
        ver = _norm_str(row.get("version"))
        if pkg in _KEY_TOOLS:
            versions[pkg] = ver
    return versions


def _runner_info(namespaces: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Return (run_command, run_time) best-effort from telemetry.

    Run time lives in the ``status_scope.telemetry`` summary
    ("Total run time: 0:05:22.210922").  The runner's ``run command`` table is
    a Name/Value listing whose ``analyzers`` row captures what was executed.
    """
    command = run_time = ""

    # Overall run time from the telemetry summary line.
    tel = namespaces.get("status_scope.telemetry")
    if tel:
        summary = _norm_str(tel.get("summary"))
        marker = "Total run time:"
        if marker in summary:
            run_time = summary.split(marker, 1)[1].strip()

    # Run command / analyzers list from the runner Name/Value table.
    sub = namespaces.get("status_scope.telemetry.runner")
    if sub:
        for tbl in decode_tables(sub):
            for row in tbl.get("rows", []):
                if not isinstance(row, dict):
                    continue
                name = _norm_str(row.get("Name")).lower()
                value = _norm_str(row.get("Value"))
                if name == "analyzers" and value:
                    command = value
                    break
            if command:
                break
    return command, run_time


# --------------------------------------------------------------------------- #
# Top-level parse
# --------------------------------------------------------------------------- #

def parse_report(path: str | Path) -> StatusScopeRecord:
    """Parse a StatusScope svtools report JSON into a StatusScopeRecord."""
    p = Path(path)
    payload = load_report(p)
    sub_reports = flatten_sub_reports(payload)

    platform, probe = _platform_from_openipc(sub_reports)
    qdf, sku, stepping = _fuse_info(sub_reports)
    if not stepping:
        stepping = _stepping_from_device_list(sub_reports)
    run_command, run_time = _runner_info(sub_reports)

    # Build the namespace map with decoded tables + summaries + raw insights.
    namespaces: dict[str, dict[str, Any]] = {}
    for name, sub in sub_reports.items():
        namespaces[name] = {
            "summary": sub.get("summary"),
            "tables": decode_tables(sub),
            "insights": sub.get("insights", []) or [],
        }

    return StatusScopeRecord(
        source_path=str(p),
        report_name=_norm_str(payload.get("name")),
        format_version=int(payload.get("format_version") or 0),
        platform=platform or "Unknown",
        stepping=stepping,
        qdf=qdf,
        sku=sku,
        probe_type=probe,
        run_command=run_command,
        run_time=run_time,
        tool_versions=_tool_versions(sub_reports),
        insights=extract_insights(sub_reports),
        namespaces=namespaces,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _render_summary(record: StatusScopeRecord) -> str:
    lines = [
        f"StatusScope report: {record.report_name} (fmt v{record.format_version})",
        f"Platform : {record.platform}"
        + (f"  stepping={record.stepping}" if record.stepping else ""),
        f"QDF/SKU  : {record.qdf or '-'} / {record.sku or '-'}   probe={record.probe_type or '-'}",
    ]
    if record.run_time:
        lines.append(f"Run time : {record.run_time}")
    if record.run_command:
        lines.append(f"Run cmd  : {record.run_command}")
    if record.tool_versions:
        tv = ", ".join(f"{k}={v}" for k, v in record.tool_versions.items())
        lines.append(f"Tools    : {tv}")
    lines.append("")
    lines.append(f"Insights ({len(record.insights)}):")
    for ins in record.insights:
        dom = f" [{ins.ip_domain}]" if ins.ip_domain else ""
        url = f"  {ins.url}" if ins.url else ""
        lines.append(f"  - {ins.type or '?':<16}{dom} {ins.message}{url}")
    links = record.hsd_links()
    if links:
        lines.append("")
        lines.append(f"HSD links ({len(links)}):")
        lines.extend(f"  - {u}" for u in links)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse a StatusScope svtools report into a compact record."
    )
    parser.add_argument("report", help="Path to *-intel-svtools-report-v1.json")
    parser.add_argument(
        "--json", action="store_true", help="Emit the compact JSON payload"
    )
    parser.add_argument(
        "--full", action="store_true", help="With --json, emit the full record"
    )
    args = parser.parse_args(argv)

    try:
        record = parse_report(args.report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = record.to_dict() if args.full else record.to_summary_dict()
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(_render_summary(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
