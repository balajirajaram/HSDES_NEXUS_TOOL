"""Batch-learn: read many HSDs (from a saved query or an explicit id list),
analyze each, and grow the KB. Feed it the GNR/CWF/SRF master query id to
pre-seed the Knowledge Base with hundreds of resolved cases at once.

Usage (CLI, uses .env creds / HSDES_AUTH_MODE):
    python -m app.batch_learn --query-id 1234567
    python -m app.batch_learn --ids 16030948515 16028631740
"""

import argparse
import asyncio
from typing import Any, Dict, List, Optional

from .analyzer import analyze
from .hsdes_client import HSDESClient
from .products import master_queries as product_master_queries


async def batch_learn(hsd_ids: Optional[List[str]] = None,
                      query_id: Optional[str] = None,
                      product: Optional[str] = None,
                      token: Optional[str] = None,
                      username: Optional[str] = None,
                      password: Optional[str] = None,
                      limit: int = 100) -> Dict[str, Any]:
    client = HSDESClient(token, username, password)
    ids: List[str] = [str(x) for x in (hsd_ids or [])]

    # Gather saved-query ids from an explicit id and/or a product's master queries.
    query_ids: List[str] = []
    if query_id:
        query_ids.append(query_id)
    if product:
        query_ids.extend(product_master_queries(product))
    for qid in query_ids:
        try:
            ids.extend(await client.get_query_results(qid, limit))
        except Exception:
            continue
    # de-dup, preserve order
    seen = set()
    ids = [x for x in ids if not (x in seen or seen.add(x))]

    results: List[Dict[str, Any]] = []
    for hid in ids[:limit]:
        try:
            res = await analyze(str(hid), f"batch-learn HSD {hid}",
                                hsdes_token=token, username=username, password=password)
            results.append({
                "id": hid,
                "platform": res.get("family"),
                "kb_action": res.get("kb_action", {}).get("action"),
                "recall": res.get("kb_recall", {}).get("confidence"),
            })
        except Exception as exc:
            results.append({"id": hid, "error": str(exc)})

    learned = [r for r in results if r.get("kb_action") in ("created", "updated")]
    return {
        "requested": len(ids),
        "processed": len(results),
        "learned": len(learned),
        "results": results,
    }


def _main() -> None:
    ap = argparse.ArgumentParser(description="Batch-learn HSDs into the KB.")
    ap.add_argument("--query-id", help="Saved HSDES query id.")
    ap.add_argument("--product", help="Product key (GNR/SRF/CWF/DMR/COR) — learns all its master queries.")
    ap.add_argument("--ids", nargs="*", help="Explicit HSD IDs.")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    out = asyncio.run(batch_learn(hsd_ids=args.ids, query_id=args.query_id,
                                  product=args.product, limit=args.limit))
    print(f"requested={out['requested']} processed={out['processed']} learned={out['learned']}")
    for r in out["results"]:
        print(" ", r)


if __name__ == "__main__":
    _main()
