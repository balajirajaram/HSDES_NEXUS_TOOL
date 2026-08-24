"""Transferred-ticket sync.

When a platform sighting is transferred to a sub-team (pcode / BIOS / Ocode /
S3M / Linux / BMC / Xucode ...), the fix and root cause land on the *sub-team*
ticket — not on the original sighting. This module finds that transferred-to
ticket, pulls its latest findings (root cause / fix ingredient / status / Axon
recordings) and PREPARES a concise "Update from Transferred Ticket" comment to
post back on the sighting.

Adapted from the intel-prompt-plugin ``hsdes-transferred-sync`` skill. This is
READ-ONLY: it prepares the summary comment (surfaced in the report); it never
auto-posts to HSDES. Posting stays a human, approval-gated action.
"""

import re
from typing import Any, Dict, List, Optional

# --- Axon recording links -------------------------------------------------
AXON_RE = re.compile(
    r"axon(?:sv)?\.(?:app\.)?intel\.com/apps?/(?:view|record-viewer)/"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
    re.IGNORECASE,
)


def extract_axon_uuids(text: str) -> set:
    """Return the set of lowercase Axon recording UUIDs found in Axon URLs."""
    return {m.group(1).lower() for m in AXON_RE.finditer(text or "")}


def canonical_axon_url(uuid: str) -> str:
    return f"https://axon.intel.com/app/view/{uuid}"


# --- Fixed / rejected status detection ------------------------------------
# A transferred ticket carries a usable fix when its workflow `reason` is one of
# these (per the hsdes-transferred-sync skill).
_FIXED_REASONS = {
    "fix_available", "implemented", "validated", "verified",
    "fix_integrated", "fix_in_validation",
}
_REJECT_REASONS = {"rejected", "duplicate", "not_a_bug", "works_as_designed"}


def is_fixed(status: str, reason: str) -> bool:
    status = (status or "").strip().lower()
    reason = (reason or "").strip().lower()
    if reason in _FIXED_REASONS:
        return True
    if status in ("resolved", "closed") and reason not in _REJECT_REASONS:
        return True
    return False


# --- Transfer-target detection --------------------------------------------
# Keywords that, when near an HSD id, strongly imply it is the transfer target.
_TRANSFER_KW = re.compile(
    r"transferr?ed|tracked|filed|cloned?|moved|routed|reassigned|hsd\s*#", re.I)
# Any 10-11 digit HSDES id starting with 15 or 16.
_ID_RE = re.compile(r"\b(1[56]\d{8,9})\b")
# Higher-signal, explicit reference forms.
_EXPLICIT_PATTERNS = [
    re.compile(r"transferr?ed\s+to[^0-9]{0,40}(1[56]\d{8,9})", re.I),
    re.compile(r"tracked\s+in\s+HSD[^0-9]{0,10}(1[56]\d{8,9})", re.I),
    re.compile(r"HSD\s*#\s*(1[56]\d{8,9})", re.I),
    re.compile(r"cloned?\s+to[^0-9]{0,40}(1[56]\d{8,9})", re.I),
    re.compile(r"sighting_central\.sighting\.id\s*=\s*(1[56]\d{8,9})", re.I),
]


def detect_transfer_targets(target: Dict[str, Any], limit: int = 3) -> List[str]:
    """Return candidate transferred-to HSD ids from the ticket text, best first.

    Scans description + comments (HTML already stripped in ``full_text``). Scores
    each distinct id by explicit-reference hits and proximity to transfer
    keywords, then returns the top ``limit`` ids, excluding the ticket itself.
    """
    self_id = str(target.get("id") or "")
    text = target.get("full_text") or ""
    if not text:
        return []

    scores: Dict[str, int] = {}

    def bump(hid: str, pts: int) -> None:
        if hid and hid != self_id:
            scores[hid] = scores.get(hid, 0) + pts

    for pat in _EXPLICIT_PATTERNS:
        for m in pat.finditer(text):
            bump(m.group(1), 5)

    # Proximity scoring: an id within ~60 chars of a transfer keyword.
    for m in _ID_RE.finditer(text):
        hid = m.group(1)
        lo = max(0, m.start() - 60)
        window = text[lo:m.end() + 60]
        if _TRANSFER_KW.search(window):
            bump(hid, 3)
        else:
            bump(hid, 1)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    # Require at least a keyword-adjacent or explicit mention (score >= 3) so a
    # stray id pasted in a log line doesn't get treated as the transfer target.
    return [hid for hid, sc in ranked if sc >= 3][:limit]


# --- Field access on the raw HSDES record ---------------------------------
def _field(rec: Dict[str, Any], *names: str) -> str:
    """Read a field from the tenant-prefixed raw record (e.g. ``bug.root_cause``)."""
    if not isinstance(rec, dict):
        return ""
    for n in names:
        if rec.get(n):
            return str(rec[n]).strip()
    for n in names:
        for k, v in rec.items():
            if v and (k == n or k.endswith("." + n)):
                return str(v).strip()
    return ""


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<p[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Fix ingredient / revision patterns mined from comments as a last resort.
_INGREDIENT_PATTERNS = [
    re.compile(r"\bpcode[\s_]*v?\d+(?:\.\d+){2,3}\b", re.I),
    re.compile(r"\bBIOS\s+(?:build|version)\s+[0-9A-Za-z._-]+", re.I),
    re.compile(r"\bkernel\s+commit\s+[0-9a-f]{7,40}\b", re.I),
    re.compile(r"\bBKC[\s_-]*\d{6,8}\b", re.I),
    re.compile(r"\bingredient\s+[0-9A-Za-z._-]+", re.I),
    re.compile(r"\b(?:version|revision|build)\s+[0-9][0-9A-Za-z._-]*\b", re.I),
]


def _mine_ingredient(text: str) -> str:
    for pat in _INGREDIENT_PATTERNS:
        m = pat.search(text or "")
        if m:
            return m.group(0).strip()
    return ""


def _domain_of(rec: Dict[str, Any]) -> str:
    dom = _field(rec, "component", "sub_component")
    if dom:
        return dom
    sub_forum = _field(rec, "sub_forum")
    if sub_forum and ".sighting_central" in sub_forum:
        return sub_forum.split(".sighting_central")[0]
    return sub_forum or ""


def summarize_transferred(orig: Dict[str, Any],
                          transferred: Dict[str, Any]) -> Dict[str, Any]:
    """Build a structured summary of one transferred ticket's latest findings."""
    rec = transferred.get("raw", {}) or {}
    tid = str(transferred.get("id") or "")
    status = transferred.get("status") or _field(rec, "status")
    reason = _field(rec, "reason")
    root_cause = _strip_html(_field(rec, "root_cause"))
    fix_desc = _strip_html(_field(rec, "fix_description"))
    fix_id = _field(rec, "fix_id")
    fix_build = _field(rec, "fix_build")
    fixed = is_fixed(status, reason)

    comments_text = "\n".join(transferred.get("comments") or [])
    ingredient = fix_id or fix_build or _mine_ingredient(comments_text)

    # Axon recordings that are on the transferred ticket but not the sighting.
    orig_axon = extract_axon_uuids(orig.get("full_text") or "")
    transferred_axon = extract_axon_uuids(transferred.get("full_text") or "")
    new_axon = sorted(transferred_axon - orig_axon)

    return {
        "id": tid,
        "title": transferred.get("title") or _field(rec, "title"),
        "owner": transferred.get("owner") or _field(rec, "owner"),
        "updated_by": _field(rec, "updated_by"),
        "updated_date": _field(rec, "updated_date"),
        "status": status,
        "reason": reason,
        "fixed": fixed,
        "domain": _domain_of(rec),
        "ingredient": ingredient or "Not specified in ticket",
        "fix_build": fix_build,
        "root_cause": root_cause,
        "fix_description": fix_desc,
        "new_axon_uuids": new_axon,
        "error": transferred.get("error"),
    }


def _article_url(hid: str) -> str:
    return f"https://hsdes.intel.com/appstore/article-one/#/article/{hid}"


def build_comment(s: Dict[str, Any]) -> str:
    """Render the ready-to-post 'Update from Transferred Ticket' comment."""
    hid = s["id"]
    date = s.get("updated_date") or ""
    L: List[str] = []
    L.append(f"## Update from Transferred Ticket {hid} ({date})".rstrip())
    L.append("")
    L.append(f"**Transferred HSD:** [{s.get('title') or hid}]({_article_url(hid)})")
    L.append(f"**Owner:** {s.get('owner') or '—'} | "
             f"**Updated by:** {s.get('updated_by') or '—'} | "
             f"**Status:** {s.get('status') or '—'} ({s.get('reason') or '—'})")
    L.append("")
    L.append("---")
    L.append("")
    if s.get("fixed"):
        L.append("### 🔧 Fix Available")
        L.append("")
        L.append(f"**Domain:** {s.get('domain') or '—'}")
        L.append(f"**Fix Ingredient / Revision:** {s.get('ingredient')}")
        if s.get("fix_build"):
            L.append(f"**Fix Build:** {s['fix_build']}")
        L.append("")
        L.append(f"**Root Cause:** {s.get('root_cause') or '(not filled in)'}")
        L.append("")
        L.append(f"**Fix Description:** {s.get('fix_description') or '(not filled in)'}")
        if not s.get("root_cause") and not s.get("fix_description"):
            L.append("")
            L.append("*(root_cause and fix_description fields are empty on the "
                     "transferred ticket — verify details with the ticket owner)*")
    else:
        L.append("### Triage Progress")
        L.append("")
        if s.get("root_cause"):
            L.append(f"- **Root cause:** {s['root_cause']}")
        else:
            L.append("- Root cause not yet confirmed on the transferred ticket.")
        L.append(f"- **Current status:** {s.get('status') or '—'} "
                 f"({s.get('reason') or '—'})")
    L.append("")
    if s.get("new_axon_uuids"):
        L.append("### 📹 Axon Recording(s)")
        L.append("")
        for u in s["new_axon_uuids"]:
            L.append(canonical_axon_url(u))
        L.append("")
    L.append("### Next Step")
    L.append("")
    if s.get("fixed"):
        dom = s.get("domain") or "the responsible"
        L.append(f"Update the {dom} ingredient to `{s.get('ingredient')}` in the "
                 "platform BKC and re-validate to close this sighting.")
    else:
        L.append("Track the transferred ticket for root-cause confirmation and a "
                 "fix ingredient, then re-validate on the platform.")
    return "\n".join(L)


async def sync_transferred(client: Any, target: Dict[str, Any],
                           max_targets: int = 2, follow_chain: bool = True) -> Optional[Dict[str, Any]]:
    """Detect the transferred-to ticket(s), fetch their latest findings, and
    return prepared summaries + ready-to-post comments.

    Returns ``None`` when no transfer reference is found. Safe/read-only.
    """
    if not target or target.get("error") or not getattr(client, "enabled", False):
        return None
    candidate_ids = detect_transfer_targets(target)
    if not candidate_ids:
        return None

    summaries: List[Dict[str, Any]] = []
    seen: set = {str(target.get("id") or "")}
    for hid in candidate_ids[:max_targets]:
        if hid in seen:
            continue
        seen.add(hid)
        try:
            article = await client.get_article(hid)
        except Exception as exc:  # pragma: no cover - network guard
            summaries.append({"id": hid, "error": str(exc)})
            continue
        if not article:
            continue
        summ = summarize_transferred(target, article)
        summ["comment_markdown"] = build_comment(summ)

        # One-level chain follow: a transferred ticket that was itself transferred.
        if (follow_chain and not article.get("error")
                and (_field(article.get("raw", {}) or {}, "reason").lower()
                     == "transferred")):
            deeper = detect_transfer_targets(article)
            for dhid in deeper[:1]:
                if dhid in seen:
                    continue
                seen.add(dhid)
                try:
                    darticle = await client.get_article(dhid)
                except Exception:
                    darticle = None
                if darticle and not darticle.get("error"):
                    dsumm = summarize_transferred(target, darticle)
                    dsumm["comment_markdown"] = build_comment(dsumm)
                    dsumm["chained_from"] = hid
                    summaries.append(dsumm)
        summaries.append(summ)

    if not summaries:
        return None
    return {
        "candidate_ids": candidate_ids,
        "summaries": summaries,
    }
