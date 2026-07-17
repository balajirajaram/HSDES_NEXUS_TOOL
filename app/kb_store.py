"""Self-learning Knowledge Base backed by SQLite.

Implements the RECALL (search) and WRITE-BACK (upsert) steps of the agent's
self-learning loop. The KB never fabricates data — it only stores what the
analyzer confirmed or hypothesized, tagged accordingly.
"""

import json
import math
import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "and", "or", "to", "for", "with",
    "is", "at", "by", "this", "that", "from", "was", "were",
}


def normalize_terms(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9_]+", (text or "").lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


class KBStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sig_key TEXT UNIQUE,
                    family TEXT,
                    stepping TEXT,
                    unit TEXT,
                    signature_text TEXT,
                    key_terms TEXT,
                    similar_hsds TEXT,
                    root_cause TEXT,
                    root_cause_confidence TEXT,
                    debug_steps TEXT,
                    resolution TEXT,
                    source_hsd TEXT,
                    confidence_tag TEXT,
                    provenance TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    hits INTEGER DEFAULT 0
                )
                """
            )

    def _sig_key(self, family: str, unit: str, signature_text: str) -> str:
        terms = "_".join(normalize_terms(signature_text)[:8])
        return f"{(family or '').upper()}|{(unit or '').upper()}|{terms}"

    # ---- RECALL ----
    def search(self, symptoms: str, family: Optional[str] = None,
               top_k: int = 5, exclude_id: Optional[str] = None) -> Dict[str, Any]:
        q_terms = set(normalize_terms(symptoms))
        with self._conn() as c:
            rows = c.execute("SELECT * FROM entries").fetchall()

        # Build the eligible candidate set + their term sets.
        docs: List[tuple] = []
        for r in rows:
            if family and r["family"] and family.upper() != r["family"].upper():
                continue
            if exclude_id and str(r["source_hsd"]) == str(exclude_id):
                continue
            hay = set(normalize_terms(f"{r['key_terms']} {r['signature_text']}"))
            docs.append((r, hay))

        # IDF weights: rare shared terms (e.g. 'kitportdisable', 'upi') count more
        # than common ones (e.g. 'system', 'gnr', 'ap').
        df: Dict[str, int] = {}
        for _, hay in docs:
            for t in hay:
                df[t] = df.get(t, 0) + 1
        n_docs = max(1, len(docs))

        def idf(t: str) -> float:
            return math.log((n_docs + 1) / (df.get(t, 0) + 1)) + 1.0

        denom = sum(idf(t) for t in q_terms) or 1.0
        scored: List[tuple] = []
        for r, hay in docs:
            matched = q_terms & hay
            if not matched:
                continue
            score = sum(idf(t) for t in matched) / denom
            # rank shared terms by specificity for display
            ordered = sorted(matched, key=lambda t: idf(t), reverse=True)
            scored.append((score, ordered, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:top_k]
        best = scored[0][0] if scored else 0.0
        if best >= 0.6:
            confidence = "High"
        elif best >= 0.35:
            confidence = "Medium"
        elif best > 0:
            confidence = "Low"
        else:
            confidence = "None"
        return {
            "confidence": confidence,
            "best_score": round(best, 3),
            "matches": [self._row_to_dict(r, s, m) for s, m, r in scored],
        }

    def _row_to_dict(self, r: sqlite3.Row, score: Optional[float] = None,
                     matched: Optional[List[str]] = None) -> Dict[str, Any]:
        d = {k: r[k] for k in r.keys()}
        for f in ("similar_hsds", "debug_steps", "provenance"):
            try:
                d[f] = json.loads(d[f]) if d[f] else ([] if f != "provenance" else {})
            except Exception:
                pass
        if score is not None:
            d["match_score"] = round(score, 3)
        if matched is not None:
            d["matched_terms"] = matched
        return d

    # ---- WRITE-BACK ----
    def upsert(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sig = entry.get("signature", {}) or {}
        family = sig.get("family", "") or ""
        unit = sig.get("unit", "") or ""
        signature_text = (
            entry.get("signature_text")
            or " ".join(sig.get("key_terms", []) or [])
            or sig.get("error_string", "")
        )
        sig_key = self._sig_key(family, unit, signature_text)
        key_terms = " ".join(sig.get("key_terms", []) or normalize_terms(signature_text))
        payload = dict(
            sig_key=sig_key,
            family=family,
            stepping=sig.get("stepping", ""),
            unit=unit,
            signature_text=signature_text,
            key_terms=key_terms,
            similar_hsds=json.dumps(entry.get("similar_hsds", [])),
            root_cause=(entry.get("root_cause") or {}).get("text", ""),
            root_cause_confidence=(entry.get("root_cause") or {}).get("confidence", "hypothesis"),
            debug_steps=json.dumps(entry.get("debug_steps", [])),
            resolution=(entry.get("resolution") or {}).get("text", ""),
            source_hsd=(entry.get("resolution") or {}).get("source_hsd", ""),
            confidence_tag=(entry.get("provenance") or {}).get("confidence_tag", "Low"),
            provenance=json.dumps(entry.get("provenance", {})),
        )
        with self._conn() as c:
            existing = c.execute(
                "SELECT id FROM entries WHERE sig_key=?", (sig_key,)
            ).fetchone()
            if existing:
                sets = ", ".join(f"{k}=?" for k in payload)
                c.execute(
                    f"UPDATE entries SET {sets}, updated_at=?, hits=hits+1 WHERE sig_key=?",
                    (*payload.values(), now, sig_key),
                )
                action = "updated"
            else:
                cols = ", ".join(payload) + ", created_at, updated_at"
                ph = ", ".join(["?"] * (len(payload) + 2))
                c.execute(
                    f"INSERT INTO entries ({cols}) VALUES ({ph})",
                    (*payload.values(), now, now),
                )
                action = "created"
        return {"action": action, "sig_key": sig_key}

    def all(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM entries ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
