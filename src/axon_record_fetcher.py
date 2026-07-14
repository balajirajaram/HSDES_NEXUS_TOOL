#!/usr/bin/env python3
"""
axon_record_fetcher.py
======================
Downloads all content objects from an Axon failure record into a local directory.

Axon (https://axon.intel.com) stores test failure records — crashdumps, serial logs,
kernel logs, and other debug artefacts — indexed by a string record ID.

This script mirrors the shape of hsd_log_fetcher.py so BugScout skills can call both
via a uniform interface.

Usage (standalone):
    python axon_record_fetcher.py <record_id> [--output-dir <path>]

    # Look up records linked to HSD ticket 15012329795
    python axon_record_fetcher.py --hsd-id 15012329795

    # Machine-readable JSON summary
    python axon_record_fetcher.py <record_id> --json

Returns (when imported):
    result dict with keys: record_id, output_dir, downloaded, skipped, errors
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent.resolve()
_DEFAULT_RECORDS_ROOT = _SCRIPT_DIR.parent / "Axon_Records"


def fetch_axon_record(
    record_id: str,
    output_dir: Path | str | None = None,
    skip_existing: bool = True,
    content_types: list[str] | None = None,
) -> dict[str, Any]:
    """Download all content objects from an Axon record.

    Args:
        record_id: Axon failure / record ID (string).
        output_dir: Directory to save files.  Defaults to
            ``Axon_Records/<record_id>/`` relative to the BugScout root.
        skip_existing: If True, skip files already present locally.
        content_types: If given, download only these content types; otherwise
            download all content types on the record.

    Returns:
        Dict with keys:
            record_id (str): The record ID used.
            output_dir (str): Absolute path where files were saved.
            downloaded (list[str]): Filenames successfully downloaded.
            skipped (list[str]): Filenames skipped (already existed).
            errors (list[str]): Error messages for any failures.
            metadata (dict): Top-level record metadata returned by Axon.
    """
    try:
        from axon_client import AxonClient
    except ImportError:
        sys.path.insert(0, str(_SCRIPT_DIR))
        from axon_client import AxonClient

    record_id = str(record_id)
    client = AxonClient()

    # Resolve output directory
    if output_dir is None:
        output_dir = _DEFAULT_RECORDS_ROOT / record_id
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "record_id": record_id,
        "output_dir": str(output_dir.resolve()),
        "downloaded": [],
        "skipped": [],
        "errors": [],
        "metadata": {},
    }

    # Step 1: Fetch record metadata
    logger.info("Fetching record metadata for Axon ID %s ...", record_id)
    try:
        record_data = client.get_record(record_id)
        result["metadata"] = record_data
    except Exception as exc:
        result["errors"].append(f"Failed to fetch record {record_id}: {exc}")
        logger.error(result["errors"][-1])
        return result

    # Step 2: List content types
    logger.info("Listing content types ...")
    try:
        available_types = client.list_content_types(record_id)
    except Exception as exc:
        result["errors"].append(f"Failed to list content types: {exc}")
        logger.error(result["errors"][-1])
        return result

    if not available_types:
        logger.info("No content objects found on Axon record %s.", record_id)
        return result

    # Filter if caller requested specific types
    types_to_download = (
        [t for t in available_types if t in content_types]
        if content_types
        else available_types
    )

    logger.info(
        "Found %d content type(s) on Axon record %s: %s",
        len(available_types),
        record_id,
        ", ".join(available_types),
    )

    # Step 3: Download each content object
    for ct in types_to_download:
        try:
            dest = client.download_content(
                record_id=record_id,
                content_type=ct,
                dest_dir=output_dir,
                skip_existing=skip_existing,
            )
        except Exception as exc:
            msg = f"Download failed for content type '{ct}': {exc}"
            result["errors"].append(msg)
            logger.warning(msg)
            continue

        if dest is None:
            # Skipped by download_content (file existed)
            result["skipped"].append(f"{ct}.bin")
        else:
            result["downloaded"].append(dest.name)

    return result


def fetch_axon_records_for_hsd(
    hsd_id: int | str,
    output_root: Path | str | None = None,
    skip_existing: bool = True,
) -> list[dict[str, Any]]:
    """Find and download all Axon records linked to an HSD ticket.

    Executes an Axon query for ``hsd_id`` and calls :func:`fetch_axon_record`
    for each matching record.

    Args:
        hsd_id: HSD article ID.
        output_root: Root directory; each record gets its own sub-directory.
            Defaults to ``Axon_Records/HSD_<hsd_id>/``.
        skip_existing: Passed through to :func:`fetch_axon_record`.

    Returns:
        List of result dicts (one per Axon record found).
    """
    try:
        from axon_client import AxonClient
    except ImportError:
        sys.path.insert(0, str(_SCRIPT_DIR))
        from axon_client import AxonClient

    hsd_id = str(hsd_id)
    client = AxonClient()

    if output_root is None:
        output_root = _DEFAULT_RECORDS_ROOT / f"HSD_{hsd_id}"
    output_root = Path(output_root)

    logger.info("Searching Axon for records linked to HSD %s ...", hsd_id)
    try:
        records = client.search_by_hsd_id(hsd_id)
    except Exception as exc:
        logger.error("Axon query failed for HSD %s: %s", hsd_id, exc)
        return [{"hsd_id": hsd_id, "errors": [str(exc)]}]

    if not records:
        logger.info("No Axon records found for HSD %s.", hsd_id)
        return []

    logger.info("Found %d Axon record(s) for HSD %s.", len(records), hsd_id)
    results = []
    for rec in records:
        rid = rec.get("id") or rec.get("record_id")
        if not rid:
            logger.warning("Record entry missing 'id': %s", rec)
            continue
        sub_dir = output_root / str(rid)
        res = fetch_axon_record(rid, output_dir=sub_dir, skip_existing=skip_existing)
        results.append(res)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(result: dict[str, Any]) -> None:
    print(f"\nAxon Record {result['record_id']} — Fetch Summary")
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
        print("  (no content objects on this record)")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(
        description="Download all content objects from an Axon failure record.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("record_id", nargs="?", help="Axon record ID string")
    group.add_argument(
        "--hsd-id",
        metavar="HSD_ID",
        help="HSD article ID — searches Axon for linked records and downloads all",
    )
    parser.add_argument(
        "--output-dir",
        metavar="PATH",
        help="Directory to save downloaded files (default: Axon_Records/<record_id>/)",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Re-download files that already exist locally",
    )
    parser.add_argument(
        "--content-types",
        metavar="TYPE",
        nargs="+",
        help="Download only these content types (e.g. crashdump serial_log)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print result as JSON instead of human-readable summary",
    )

    args = parser.parse_args()
    skip = not args.no_skip
    out_dir = Path(args.output_dir) if args.output_dir else None

    if args.hsd_id:
        results = fetch_axon_records_for_hsd(
            hsd_id=args.hsd_id,
            output_root=out_dir,
            skip_existing=skip,
        )
        if args.json_output:
            print(json.dumps(results, indent=2))
        else:
            if not results:
                print(f"No Axon records found for HSD {args.hsd_id}.")
            for r in results:
                _print_summary(r)
        has_errors = any(r.get("errors") for r in results)
        return 1 if has_errors else 0
    else:
        result = fetch_axon_record(
            record_id=args.record_id,
            output_dir=out_dir,
            skip_existing=skip,
            content_types=args.content_types,
        )
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            _print_summary(result)
        return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
