"""Summarize one HSD and SAVE the report to disk.

Usage:
    python -m app.summarize 22022875184
    python -m app.summarize 22022875184 "optional symptom hint"

Writes the report to  output/hsd_<id>_<timestamp>.md  and prints the path.
"""

import argparse
import asyncio
import os
import time

from .analyzer import analyze

_OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


async def summarize(hsd_id: str, symptoms: str = "") -> str:
    result = await analyze(hsd_id, symptoms)
    md = result.get("report_markdown", "")
    os.makedirs(_OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(_OUT_DIR, f"hsd_{hsd_id}_{stamp}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path


def _main() -> None:
    ap = argparse.ArgumentParser(description="Summarize an HSD and save the report.")
    ap.add_argument("hsd_id")
    ap.add_argument("symptoms", nargs="?", default="")
    args = ap.parse_args()
    path = asyncio.run(summarize(args.hsd_id, args.symptoms))
    with open(path, "r", encoding="utf-8") as f:
        print(f.read())
    print("\n" + "=" * 80)
    print(f"Saved report to: {path}")


if __name__ == "__main__":
    _main()
