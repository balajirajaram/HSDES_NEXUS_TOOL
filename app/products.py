"""Product registry — the per-product 'issue database' configuration.

Each product (GNR, SRF, CWF, and future DMR/COR) maps to:
  - aliases:          strings used to detect the product from ticket text
  - families:         HSDES family values (for building/scoping queries)
  - master_queries:   saved HSDES query id(s) that define the similar-issue corpus
  - register_namespace / wiki_scopes: hints for command + spec lookup

Extend by editing products.json — no code change needed to add a new product.
"""

import json
import os
from typing import Dict, List, Optional

_PATH = os.path.join(os.path.dirname(__file__), "products.json")


def _load() -> Dict[str, dict]:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


PRODUCTS: Dict[str, dict] = _load()


def detect_product(text: str) -> Optional[str]:
    """Return the product key whose alias best matches the text (longest wins)."""
    t = (text or "").upper()
    best, best_len = None, 0
    for key, cfg in PRODUCTS.items():
        for alias in cfg.get("aliases", []):
            a = alias.upper()
            if a in t and len(a) > best_len:
                best, best_len = key, len(a)
    return best


def product_display(product: Optional[str]) -> str:
    if not product:
        return ""
    return (PRODUCTS.get(product) or {}).get("display", product)


def master_queries(product: Optional[str]) -> List[str]:
    if not product:
        return []
    return list((PRODUCTS.get(product) or {}).get("master_queries", []))


def register_namespace(product: Optional[str]) -> str:
    return (PRODUCTS.get(product) or {}).get("register_namespace", "sv.socket0")


def all_products() -> Dict[str, dict]:
    return PRODUCTS
