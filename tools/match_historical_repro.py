"""Suggest a read-only historical reproduction from Golden Cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.historical_repro import load_cases, match_historical_repro, render_section


def main() -> int:
    parser = argparse.ArgumentParser(description="Match a failure signature to Golden Case repros")
    parser.add_argument("--dir", type=Path, default=Path("golden_cases"))
    parser.add_argument("--platform", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--mcacod", default="")
    parser.add_argument("--mscod", default="")
    parser.add_argument("--bank", default="")
    parser.add_argument("--socket", default="")
    parser.add_argument("--keywords", default="")
    args = parser.parse_args()
    signature = vars(args).copy()
    signature.pop("dir")
    result = match_historical_repro(signature, load_cases(args.dir))
    print(render_section(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
