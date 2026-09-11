"""Export saved HSDES query pools for candidate-only Golden Case review.

This exports article summaries plus comments and attachment metadata. It never
writes to golden_cases/. The output is intended for build_golden_candidates.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

from app.hsdes_client import HSDESClient

QUERY_IDS = (
    "16026853717", "16027811005", "16022833305", "14012297882",
    "16027523187", "16027357901",
)


async def export(limit_per_query: int, concurrency: int = 12,
                 query_ids: tuple[str, ...] = QUERY_IDS) -> List[Dict[str, Any]]:
    client = HSDESClient()
    records: List[Dict[str, Any]] = []
    seen = set()
    for query_id in query_ids:
        ids = await client.get_query_results(query_id, limit=limit_per_query)
        batch = [hsd_id for hsd_id in ids if hsd_id not in seen]
        seen.update(batch)
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_one(hsd_id: str) -> Dict[str, Any]:
            async with semaphore:
                article = await client.get_article(hsd_id) or {"id": hsd_id}
                article["source_query_id"] = query_id
                try:
                    article["attachments"] = await client.list_attachments(hsd_id)
                except Exception as exc:
                    article["attachments_error"] = str(exc)
                    article["attachments"] = []
                return article

        records.extend(await asyncio.gather(*(fetch_one(hsd_id) for hsd_id in batch)))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Export HSDES candidate records")
    parser.add_argument("--output", type=Path, default=Path("hsdes_candidates.json"))
    parser.add_argument("--limit-per-query", type=int, default=200,
                        help="Maximum records fetched from each saved query")
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--query-id", action="append", dest="query_ids",
                        help="Saved query ID; repeat for multiple historical pools")
    args = parser.parse_args()
    query_ids = tuple(args.query_ids) if args.query_ids else QUERY_IDS
    records = asyncio.run(export(max(1, args.limit_per_query), max(1, args.concurrency), query_ids))
    args.output.write_text(json.dumps({"articles": records}, indent=2), encoding="utf-8")
    print(f"Exported {len(records)} unique HSD records to {args.output}")
    print("Candidate-only export; no golden_cases files were written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
