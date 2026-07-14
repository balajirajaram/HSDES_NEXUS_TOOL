#!/usr/bin/env python3
"""
statusscope_ingest.py
=====================
Source resolver for StatusScope svtools reports.  Locates a StatusScope
``*-intel-svtools-report-v1.json`` document from one of three sources and
parses it into a :class:`StatusScopeRecord`:

    * ``from_json(path)``  — a report JSON already on disk (primary path)
    * ``from_dir(path)``   — a directory (e.g. ``HSD_Logs_Details/HSD_<id>/``);
                             finds the newest ``*svtools-report*.json`` inside
    * ``from_zip(path)``   — a StatusScope result zip; extracts + finds the report
    * ``from_axon(id)``    — an Axon record; downloads the svtools-report content
                             type then parses it

It also exposes ``bridge_to_crashdump`` to feed StatusScope error insights into
the existing :mod:`crashdump_router` lane where a crash signature is present.

Usage (standalone)::

    python statusscope_ingest.py --json  <report.json>
    python statusscope_ingest.py --dir   HSD_Logs_Details/HSD_15012329795
    python statusscope_ingest.py --zip   result.zip
    python statusscope_ingest.py --axon  <record_id>
    # add --full for the full record, otherwise the compact summary payload is printed
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from statusscope_parser import StatusScopeRecord, parse_report

logger = logging.getLogger(__name__)

# Filename globs that identify a StatusScope report document, most specific first.
_REPORT_GLOBS = (
    "*-intel-svtools-report-v1.json",
    "*svtools-report*.json",
    "*svtools_report*.json",
)


def _find_report_in_dir(directory: Path) -> Path | None:
    """Return the newest StatusScope report JSON under ``directory`` (recursive)."""
    for pattern in _REPORT_GLOBS:
        hits = sorted(
            directory.rglob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if hits:
            return hits[0]
    return None


def from_json(path: str | Path) -> StatusScopeRecord:
    """Parse a StatusScope report JSON already on disk."""
    return parse_report(path)


def from_dir(path: str | Path) -> StatusScopeRecord | None:
    """Find and parse a StatusScope report inside a directory.

    Returns None if no report file is present (non-blocking for callers).
    """
    directory = Path(path)
    if not directory.is_dir():
        return None
    report = _find_report_in_dir(directory)
    if report is None:
        logger.info("No StatusScope report found under %s", directory)
        return None
    logger.info("Found StatusScope report: %s", report)
    return parse_report(report)


def from_zip(path: str | Path) -> StatusScopeRecord | None:
    """Extract a StatusScope result zip and parse the report inside it."""
    zip_path = Path(path)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"{zip_path} is not a zip file")
    with tempfile.TemporaryDirectory(prefix="statusscope_") as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        return from_dir(tmp)


def from_axon(
    record_id: str,
    content_type: str | None = None,
    dest_dir: str | Path | None = None,
) -> StatusScopeRecord | None:
    """Download the svtools-report content from an Axon record and parse it.

    Args:
        record_id: Axon record / failure ID.
        content_type: Exact svtools-report content-type name.  If omitted, the
            content types on the record are scanned for one that looks like a
            StatusScope report (name containing ``svtools`` or ``status_scope``).
        dest_dir: Where to save the downloaded report.  Defaults to a temp dir.

    Returns:
        Parsed record, or None if no matching content type is found.
    """
    # Imported lazily so the local (json/dir/zip) paths carry no Axon/auth deps.
    from axon_client import AxonClient

    client = AxonClient()
    if content_type is None:
        available = client.list_content_types(record_id)
        content_type = _pick_svtools_content_type(available)
        if content_type is None:
            logger.info(
                "No svtools-report content type on Axon record %s (have: %s)",
                record_id,
                ", ".join(available) or "none",
            )
            return None

    target = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="statusscope_axon_"))
    downloaded = client.download_content(
        record_id,
        content_type,
        target,
        filename_hint=f"{record_id}-svtools-report-v1.json",
        skip_existing=False,
    )
    if downloaded is None:
        return None
    return parse_report(downloaded)


def _pick_svtools_content_type(content_types: list[str]) -> str | None:
    """Heuristically select the StatusScope report content type."""
    lowered = [(ct, ct.lower()) for ct in content_types]
    for ct, low in lowered:
        if "svtools" in low and "report" in low:
            return ct
    for ct, low in lowered:
        if "svtools" in low or "status_scope" in low or "statusscope" in low:
            return ct
    return None


def bridge_to_crashdump(record: StatusScopeRecord, output_dir: str | Path | None = None):
    """Feed StatusScope error insights into the crashdump_router lane.

    On DMR the ``mca`` plugin is intentionally empty (crashlog collaterals not
    yet delivered), so the ``error`` analyzer namespace is the real error
    source.  Other captures may surface errors under different namespaces
    (crashlog, sideband, IP-specific error tables), so we gather error-bearing
    tables from any high-value namespace rather than a single fixed one.  This
    writes a small crashdump-shaped JSON and routes it so the existing handbook
    flow can act on it.  Returns the router result dict, or None when there is
    nothing crash-like to route.
    """
    error_tables: list[dict[str, Any]] = []
    for ns, sub in record.namespaces.items():
        low = ns.lower()
        if any(kw in low for kw in ("error", "mca", "crashlog", "sideband")):
            error_tables.extend(sub.get("tables", []))
    error_insights = [
        i.to_dict() for i in record.insights if i.type.upper().startswith("HW.")
    ]
    if not error_tables and not error_insights:
        return None

    from crashdump_router import parse_crashdump_json

    payload = {
        "platform": record.platform,
        "stepping": record.stepping,
        "source": "statusscope",
        "error_tables": error_tables,
        "insights": error_insights,
    }
    summary = parse_crashdump_json(payload, source_name=record.source_path)
    result = {"summary": summary.to_dict()}
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "statusscope_crashdump_bridge.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve + parse a StatusScope report.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", metavar="PATH", help="Report JSON on disk")
    group.add_argument("--dir", metavar="PATH", help="Directory containing a report")
    group.add_argument("--zip", metavar="PATH", help="StatusScope result zip")
    group.add_argument("--axon", metavar="RECORD_ID", help="Axon record ID")
    parser.add_argument("--content-type", help="Axon content type override (with --axon)")
    parser.add_argument("--full", action="store_true", help="Emit the full record JSON")
    args = parser.parse_args(argv)

    try:
        if args.json:
            record = from_json(args.json)
        elif args.dir:
            record = from_dir(args.dir)
        elif args.zip:
            record = from_zip(args.zip)
        else:
            record = from_axon(args.axon, content_type=args.content_type)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if record is None:
        print("No StatusScope report found.", file=sys.stderr)
        return 2

    payload = record.to_dict() if args.full else record.to_summary_dict()
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
