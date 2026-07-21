"""Comment-thread investigation analyzer — the part that reads the ticket like a
human debug engineer does.

A ticket's comment thread IS the investigation: who observed what, what was tried,
what was ruled out, and where the debug converged (root cause / workaround). The
signature/log scan alone misses all of this. This module mines the structured
comments (author + order preserved) into a crystal-clear narrative:

  - a chronological investigation timeline (per comment: kind + concise point),
  - the CONVERGED root cause (latest strong statement wins — debug converges),
  - any workaround / fix mentioned,
  - what has ALREADY been tried (so next steps don't repeat them),
  - technical breadcrumbs (registers, file:line, socket/port, BIOS builds, logs).

Deterministic (no LLM). Heuristics are conservative and quote the ticket text.
"""

import re
from typing import Any, Dict, List, Optional

# --- classification cues (checked in priority order; first match wins) ---
_KIND_CUES: List[tuple] = [
    ("root_cause", re.compile(
        r"root[\s-]?cause|isolated (?:the )?issue to|isolated to|culprit|"
        r"caused by|due to|because of|leading to|leads to|results? in|"
        r"stuck (?:state|indefinitely)|\bNACK\b|no[\s-]?ack|never (?:reach|recover|"
        r"receive)|not received|hang(?:s)? (?:before|because|when|at)", re.I)),
    ("workaround", re.compile(
        r"work[\s-]?around|\bW/?A\b|temporary (?:fix|workaround)|mitigat|\bBKM\b|"
        r"patched|real fix|proper fix|fix (?:in progress|is|lands|validated)", re.I)),
    ("finding", re.compile(
        r"observ|confirm|reproduc|recreat|\bseen\b|shows?|indicat|detect|found|"
        r"non[\s-]?zero|error(?:s)? (?:detected|re-?assert)|re-?assert|clean|"
        r"experiments? confirm|points? to", re.I)),
    ("action", re.compile(
        r"tried|flash(?:ed|ing)|disabl(?:ed|ing)|enabl(?:ed|ing)|swap|re-?ran|"
        r"re-?run|provided (?:a )?(?:test|debug)|reach(?:ed)? out|promoted to|"
        r"add(?:ed|ing)? (?:extra |debug )?logs|check(?:ed|ing)?|poll|trace|"
        r"bisect|A/B|isolate whether", re.I)),
    ("next_step", re.compile(
        r"next(?:\s*step)?|will (?:try|check|add|work)|working on|plan to|to check|"
        r"need to|todo|going to|follow[\s-]?up", re.I)),
]

# --- technical breadcrumb extractors ---
_BREADCRUMBS: List[tuple] = [
    ("register", re.compile(r"\b[A-Z][A-Z0-9]{3,}_[A-Z0-9_]*REG\b|\bBIOSSCRATCHPAD\d+\w*", re.I)),
    ("code_site", re.compile(r"\b[\w]+\.c:\d+\b", re.I)),
    ("socket_port", re.compile(
        r"\bSocket\s*\d+\b|\bPort\s*\d+\b|UpiAgent\[\d\]\[\d\]|Cpu\d+P\d+KitPortDisable", re.I)),
    ("bios_build", re.compile(r"\b[A-Z]{3,}\d*\.[A-Z]{2,4}\.\d{3,4}\.[A-Za-z0-9._]+", re.I)),
    ("upi_signal", re.compile(r"\bKTI[A-Z0-9_]+REG\b|\bUPLR\d(?:\.\d)?\b", re.I)),
]

_LABELS = {
    "root_cause": "ROOT CAUSE",
    "workaround": "WORKAROUND / FIX",
    "finding": "OBSERVED",
    "action": "TRIED",
    "next_step": "NEXT STEP",
    "note": "NOTE",
}

# strong convergence markers boost a comment's claim to be THE root cause
_STRONG_RC = re.compile(
    r"isolated (?:the )?issue to|root[\s-]?caused?|\bNACK\b|stuck (?:state|indefinitely)|"
    r"never (?:reaches?|recover)|not received|hang.*(?:because|due to|before)", re.I)

# closure / resolution / disposition statements (final verdict of the thread)
_RESOLUTION = re.compile(
    r"no repro|cannot reproduce|not able to reproduce|issue (?:is )?not seen|"
    r"after (?:set|setting|applying|flashing).*(?:not seen|resolved|fixed|no repro)|"
    r"closing as|closed as|marking .* (?:closed|rejected)|fixed (?:in|by)|"
    r"resolved (?:by|in|after)|root[\s-]?caused to|will be fixed in|"
    r"work[\s-]?around", re.I)


def _is_prose(s: str) -> bool:
    """True for human explanation; False for tables / log dumps / timestamp grids
    so we don't mistake a pasted test-indicator table for a root-cause statement."""
    if s.count("|") >= 3 or s.count("@") >= 2:
        return False
    if re.search(r"\d{4} @ \d|kubernetes\.host|metadata\.test|test-(?:start|end)-indicator",
                 s, re.I):
        return False
    if any(tok in s for tok in ("0x", "::", "=>", ".show()", ".read()", "sv.socket")):
        # allow short mentions but reject dump-like lines
        if len(re.findall(r"0x[0-9A-Fa-f]+", s)) >= 2:
            return False
    alpha = sum(c.isalpha() or c.isspace() for c in s)
    return len(s) >= 12 and alpha / max(1, len(s)) >= 0.6


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.;!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 8]


def _classify(sentence: str) -> Optional[str]:
    for kind, pat in _KIND_CUES:
        if pat.search(sentence):
            return kind
    return None


def _salient(text: str) -> Dict[str, str]:
    """Pick the most salient PROSE sentence + kind from one comment (root_cause >
    workaround > finding > action > next_step). Non-prose (tables/log dumps) is
    skipped so noise never becomes the headline."""
    order = {k: i for i, (k, _) in enumerate(_KIND_CUES)}
    best_kind, best_sent = None, ""
    prose = [s for s in _split_sentences(text) if _is_prose(s)]
    for s in prose:
        k = _classify(s)
        if k is None:
            continue
        if best_kind is None or order[k] < order[best_kind]:
            best_kind, best_sent = k, s
        if best_kind == "root_cause":
            break
    if best_kind is None:
        return {"kind": "note", "text": (prose[0] if prose else
                                         (_split_sentences(text)[:1] or [text])[0])[:240]}
    return {"kind": best_kind, "text": best_sent[:240]}


def _breadcrumbs(text: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for name, pat in _BREADCRUMBS:
        hits = list(dict.fromkeys(m.group(0) for m in pat.finditer(text)))
        if hits:
            out[name] = hits[:12]
    return out


def analyze_comments(structured: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Return the mined investigation narrative, or None if no comments."""
    if not structured:
        return None

    narrative: List[Dict[str, str]] = []
    tried: List[str] = []
    next_steps: List[str] = []
    crumbs: Dict[str, List[str]] = {}
    rc_candidates: List[tuple] = []      # (index, strength, author, text)
    wa_candidates: List[tuple] = []
    res_candidates: List[tuple] = []     # (index, author, text) — closure/disposition

    for idx, c in enumerate(structured):
        author = c.get("author", "") or "unknown"
        text = c.get("text", "") or ""
        if not text:
            continue
        sal = _salient(text)
        narrative.append({"seq": idx + 1, "author": author,
                          "kind": sal["kind"], "text": sal["text"]})

        # accumulate breadcrumbs across the whole thread
        for k, v in _breadcrumbs(text).items():
            crumbs.setdefault(k, [])
            for item in v:
                if item not in crumbs[k]:
                    crumbs[k].append(item)

        # root-cause candidates: PROSE only; later comments + strong markers win
        for s in _split_sentences(text):
            if not _is_prose(s):
                continue
            if _classify(s) == "root_cause":
                strength = idx + (5 if _STRONG_RC.search(s) else 0)
                rc_candidates.append((idx, strength, author, s[:300]))
            if _RESOLUTION.search(s):
                res_candidates.append((idx, author, s[:300]))
            if _classify(s) == "workaround":
                wa_candidates.append((idx, author, s[:240]))
        if sal["kind"] == "action":
            tried.append(f"{author}: {sal['text']}")
        if sal["kind"] == "next_step":
            next_steps.append(f"{author}: {sal['text']}")

    root_cause = ""
    rc_author = ""
    if rc_candidates:
        rc_candidates.sort(key=lambda x: x[1], reverse=True)
        _, _, rc_author, root_cause = rc_candidates[0]

    # Resolution / closure statement (final disposition) — latest wins.
    resolution = ""
    res_author = ""
    if res_candidates:
        res_candidates.sort(key=lambda x: x[0], reverse=True)
        _, res_author, resolution = res_candidates[0]

    workaround = ""
    wa_author = ""
    if wa_candidates:
        # prefer the latest workaround mention
        wa_candidates.sort(key=lambda x: x[0], reverse=True)
        _, wa_author, workaround = wa_candidates[0]
    # A closure/resolution statement is also a valid "workaround/fix" headline.
    if not workaround and resolution:
        workaround, wa_author = resolution, res_author

    # If we have a closure but no prose root cause, use the resolution as the
    # converged conclusion (e.g. "after setting CPU straps, no repro").
    if not root_cause and resolution:
        root_cause, rc_author = resolution, res_author

    # status hint from the convergence of the thread
    joined = " ".join(c.get("text", "") for c in structured).lower()
    closed = any(w in joined for w in ("no repro", "cannot reproduce", "closing as",
                                       "closed as", "rejected", "not seen"))
    if closed and resolution:
        status_hint = "closed / resolved (see disposition)"
    elif workaround and root_cause:
        status_hint = "root-caused; workaround validated; real fix in progress"
    elif root_cause:
        status_hint = "root cause identified (unverified/fix pending)"
    elif "promoted to" in joined or "in progress" in joined:
        status_hint = "under active debug"
    else:
        status_hint = "early investigation"

    return {
        "count": len(structured),
        "narrative": narrative,
        "root_cause": root_cause,
        "root_cause_author": rc_author,
        "workaround": workaround,
        "workaround_author": wa_author,
        "resolution": resolution,
        "resolution_author": res_author,
        "tried": tried[:10],
        "next_steps": next_steps[:6],
        "breadcrumbs": crumbs,
        "status_hint": status_hint,
    }
