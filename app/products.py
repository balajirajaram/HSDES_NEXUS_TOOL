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


def specs_project(product: Optional[str]) -> str:
    """docs.intel.com project index name for this product (empty if unknown)."""
    return (PRODUCTS.get(product) or {}).get("specs_project", "")


def spec_docs(product: Optional[str]) -> List[dict]:
    """Verified SOC-guide / HAS document references for this product."""
    return list((PRODUCTS.get(product) or {}).get("spec_docs", []))


_CORPUS_PATH = os.path.join(os.path.dirname(__file__), "knowledge", "spec_corpus.json")


def _load_corpus() -> Dict[str, dict]:
    try:
        with open(_CORPUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def spec_corpus(product: Optional[str]) -> Dict[str, list]:
    """Tiered MCA/RAS document corpus (tier1/tier2/tier3) for a product.

    Returns {} when the product is unknown. Docs with an empty 'url' are known
    to be needed but not yet located — never fabricate the URL."""
    if not product:
        return {}
    corpus = _load_corpus().get("products", {})
    return corpus.get(product, {})


def all_products() -> Dict[str, dict]:
    return PRODUCTS
