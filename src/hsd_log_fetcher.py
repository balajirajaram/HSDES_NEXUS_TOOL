#!/usr/bin/env python3
"""
hsd_log_fetcher.py
══════════════════
Downloads all attachments from an HSD ticket into a local directory.

Used by BugScout skills (hsd-triage, live-debug) to auto-populate
HSD_Logs_Details/<hsd_id>/ before analysis begins.

Usage (standalone):
    python hsd_log_fetcher.py <hsd_id> [--output-dir <path>]

Returns (when imported):
    result dict with keys: hsd_id, output_dir, downloaded, skipped, errors
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default output root — same folder structure used by BugScout manually today
_SCRIPT_DIR = Path(__file__).parent.resolve()
_DEFAULT_LOGS_ROOT = _SCRIPT_DIR.parent / "HSD_Logs_Details"


def _safe_filename(name: str, fallback: str) -> str:
    """Sanitize a filename, removing path traversal characters."""
    if not name:
        return fallback
    # Strip any directory components an attacker could inject
    name = Path(name).name
    # Remove characters unsafe for Windows/Linux filenames
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name or fallback


def _filename_from_response(response: Any, attachment_id: int) -> str:
    """Extract filename from Content-Disposition header, or fall back to attachment_<id>."""
    cd = response.headers.get("Content-Disposition", "")
    # Try RFC 5987 encoded filename first (filename*=UTF-8''...)
    m = re.search(r"filename\*=(?:UTF-8'')?([^\s;]+)", cd, re.IGNORECASE)
    if m:
        from urllib.parse import unquote
        return _safe_filename(unquote(m.group(1)), f"attachment_{attachment_id}")
    # Fall back to plain filename=
    m = re.search(r'filename=["\']?([^"\';\r\n]+)["\']?', cd, re.IGNORECASE)
    if m:
        return _safe_filename(m.group(1).strip(), f"attachment_{attachment_id}")
    return f"attachment_{attachment_id}"


def fetch_hsd_logs(
    hsd_id: int | str,
    output_dir: Path | str | None = None,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """Download all attachments from an HSD ticket.

    Args:
        hsd_id: HSD article ID.
        output_dir: Directory to save files. Defaults to
            HSD_Logs_Details/<hsd_id>/ relative to BugScout root.
        skip_existing: If True, skip files that already exist locally.

    Returns:
        Dict with keys:
            hsd_id (int): The article ID used.
            output_dir (str): Absolute path where files were saved.
            downloaded (list[str]): Filenames successfully downloaded.
            skipped (list[str]): Filenames skipped (already existed).
            errors (list[str]): Error messages for any failures.
    """
    try:
        from hsdes_client import HSDESComprehensiveClient
    except ImportError:
        # Allow running from outside src/ directory
        sys.path.insert(0, str(_SCRIPT_DIR))
        from hsdes_client import HSDESComprehensiveClient

    hsd_id = int(hsd_id)
    client = HSDESComprehensiveClient()

    # Resolve output directory
    if output_dir is None:
        output_dir = _DEFAULT_LOGS_ROOT / f"HSD_{hsd_id}"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "hsd_id": hsd_id,
        "output_dir": str(output_dir.resolve()),
        "downloaded": [],
        "skipped": [],
        "errors": [],
    }

    # Step 1: List attachments on the article
    logger.info(f"Fetching attachment list for HSD {hsd_id} ...")
    try:
        children = client.get_article_children(
            article_id=hsd_id,
            child_subject="attachment",
            fields="id,rev,owner,title,description",
        )
    except Exception as exc:
        result["errors"].append(f"Failed to list attachments: {exc}")
        logger.error(result["errors"][-1])
        return result

    attachments = children.get("data", [])
    if not attachments:
        logger.info(f"No attachments found on HSD {hsd_id}.")
        return result

    logger.info(f"Found {len(attachments)} attachment(s) on HSD {hsd_id}.")

    # Step 2: Download each attachment
    for att in attachments:
        att_id = att.get("id")
        if not att_id:
            result["errors"].append(f"Attachment entry missing 'id': {att}")
            continue

        # Use title field as hint for filename (may be empty)
        title_hint = att.get("title") or ""

        # Download — we need the response object to extract the real filename
        # so we do a raw GET here rather than calling client.download_attachment()
        url = f"{client.base_url}/binary/{att_id}"
        try:
            response = client.session.get(url)
            response.raise_for_status()
        except Exception as exc:
            msg = f"Download failed for attachment {att_id}: {exc}"
            result["errors"].append(msg)
            logger.warning(msg)
            continue

        filename = _filename_from_response(response, att_id)
        # If Content-Disposition gave nothing useful, fall back to title hint
        if filename == f"attachment_{att_id}" and title_hint:
            filename = _safe_filename(title_hint, filename)

        dest = output_dir / filename

        # Handle duplicate filenames by appending the attachment ID
        if dest.exists() and skip_existing:
            result["skipped"].append(filename)
            logger.info(f"  Skipped (exists): {filename}")
            continue

        # If same name but different ID exists, suffix with ID
        if dest.exists() and not skip_existing:
            stem = dest.stem
            suffix = dest.suffix
            dest = output_dir / f"{stem}_{att_id}{suffix}"
            filename = dest.name

        try:
            dest.write_bytes(response.content)
            result["downloaded"].append(filename)
            logger.info(f"  Downloaded: {filename} ({len(response.content):,} bytes)")
        except Exception as exc:
            msg = f"Failed to write {filename}: {exc}"
            result["errors"].append(msg)
            logger.warning(msg)

    return result


def _print_summary(result: dict[str, Any]) -> None:
    print(f"\nHSD {result['hsd_id']} — Log Fetch Summary")
    print(f"Output dir : {result['output_dir']}")
    print(f"Downloaded : {len(result['downloaded'])} file(s)")
    for f in result["downloaded"]:
        print(f"  + {f}")
    if result["skipped"]:
        print(f"Skipped    : {len(result['skipped'])} already present")
        for f in result["skipped"]:
            print(f"  ~ {f}")
    if result["errors"]:
        print(f"Errors     : {len(result['errors'])}")
        for e in result["errors"]:
            print(f"  ! {e}")
    if not result["downloaded"] and not result["errors"]:
        print("  (no attachments on this ticket)")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(
        description="Download all HSD attachments into HSD_Logs_Details/<hsd_id>/",
    )
    parser.add_argument("hsd_id", type=int, help="HSD article ID")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override download directory (default: HSD_Logs_Details/<hsd_id>/)",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Re-download files that already exist (appends _<id> to avoid overwrite)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print result as JSON instead of human-readable summary",
    )
    args = parser.parse_args()

    result = fetch_hsd_logs(
        hsd_id=args.hsd_id,
        output_dir=args.output_dir,
        skip_existing=not args.no_skip,
    )

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        _print_summary(result)

    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
