"""Summarize one HSD and SAVE the report to disk.

Usage:
    python -m app.summarize 22022875184
    python -m app.summarize 22022875184 "optional symptom hint"

Writes the report to  output/hsd_<id>_<timestamp>.md  and prints the path.
"""

import argparse
import asyncio
import os
import sys
import time

# Console may be cp1252 on Windows; force UTF-8 so report glyphs (e.g. ⟵) print.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from .analyzer import analyze
from .log_analyzer import read_log
from .report_html import render_report_html

_OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


async def summarize(hsd_id: str, symptoms: str = "",
                    log_path: str = "", fetch_attachments: bool = True,
              follow_transferred: bool = True) -> tuple[str, str]:
    log_text = read_log(log_path) if log_path else None
    result = await analyze(hsd_id, symptoms, log_text=log_text,
                           fetch_attachments=fetch_attachments,
                           follow_transferred=follow_transferred)
    md = result.get("report_markdown", "")
    os.makedirs(_OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(_OUT_DIR, f"hsd_{hsd_id}_{stamp}.md")
    html_path = os.path.join(_OUT_DIR, f"hsd_{hsd_id}_{stamp}.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    html_doc = render_report_html(md, title=f"HSD {hsd_id} Analysis")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return md_path, html_path


def _main() -> None:
    ap = argparse.ArgumentParser(description="Summarize an HSD and save the report.")
    ap.add_argument("hsd_id")
    ap.add_argument("symptoms", nargs="?", default="")
    ap.add_argument("--log", default="", help="Path to a log file (.txt/.log/.gz) to analyze.")
    ap.add_argument("--no-attachments", action="store_true",
                    help="Do NOT download the ticket's attached logs (they are fetched by default).")
    ap.add_argument("--no-transferred", action="store_true",
                    help="Do NOT follow / sync the transferred sub-team ticket (synced by default).")
    args = ap.parse_args()
    md_path, html_path = asyncio.run(summarize(args.hsd_id, args.symptoms, args.log,
                                               fetch_attachments=not args.no_attachments,
                                               follow_transferred=not args.no_transferred))
    with open(md_path, "r", encoding="utf-8") as f:
        print(f.read())
    print("\n" + "=" * 80)
    print(f"Saved markdown report to: {md_path}")
    print(f"Saved HTML report to: {html_path}")


if __name__ == "__main__":
    _main()
