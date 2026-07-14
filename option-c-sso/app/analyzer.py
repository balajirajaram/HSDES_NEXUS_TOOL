"""Orchestrates the self-learning triage loop.

Flow (runs on every request):
  Step 0 RECALL      -> KB search + confidence
  Step 1 DECIDE      -> High = KB-first; else HSDES fallback
  Step 2 INVESTIGATE -> target HSD + similar HSDs
  Step 3 WRITE-BACK  -> upsert KB entry (confirmed vs hypothesis)
  Step 4 REPORT      -> A-H markdown report

HSDES access uses a PER-REQUEST token supplied by the caller (each user's own
token, passed from the browser). No shared secret is stored on the server.
Uses the LLM when configured; otherwise produces a deterministic OFFLINE report
from the retrieved KB + HSDES data (never fabricates HSD IDs).
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import config
from .hsdes_client import HSDESClient
from .kb_store import KBStore, normalize_terms
from .llm_client import llm

kb = KBStore(config.KB_DB_PATH)

SYSTEM_PROMPT = """You are an expert Intel silicon debug engineer specializing in GNR
(Granite Rapids), SRF (Sierra Forest), and CWF (Clearwater Forest). You triage HSD-ES
tickets for RDT and UPI failures. You reason strictly from the evidence provided and
NEVER fabricate HSD IDs, register names, or commands.

You are given: the target HSD data (from HSDES, may be empty), matched cases from a
learned Knowledge Base (KB), and similar HSDs from a fresh HSDES lookup. Produce a
Markdown report with EXACTLY these sections:

A. Target HSD summary (title, component, stepping, status, owner, failure signature)
B. KB recall result (confidence + matched learned cases)
C. Similar HSDs table (ID | Source: KB/HSDES | Similarity reason | Root cause | Status)
D. Ranked root-cause hypotheses, each tied to supporting evidence
E. Detailed next debug steps - numbered, each with: what to check & why, exact PythonSV
   command(s) (e.g. sv.socket0.<unit>.<reg>.read(), MCE decode, log/RPT greps), and a
   decision branch (if X -> conclusion, else -> next step)
F. Data to request/collect (RPT/rpt.gz fields, ucode/BIOS rev, cluster, bucket)
G. Learning summary (what KB entry was created/updated + confidence tag)
H. Known-issue verdict (known + cite HSD, or new sighting)

Rules: Only cite HSD IDs present in the provided data. If unsure of a register path,
say so and give the closest known path plus how to confirm it. Clearly separate
"confirmed from data" vs "hypothesis".

Return a SINGLE JSON object (no prose outside it) with keys:
  "report_markdown": string  (the full A-H report)
  "kb_entry": object matching this schema:
    {
      "signature": {"family","stepping","unit","bucket","mce_bank","rip","signal",
                    "error_string","key_terms":[...]},
      "similar_hsds": [{"id","why_matched"}],
      "root_cause": {"text","confidence":"confirmed|hypothesis"},
      "debug_steps": ["..."],
      "resolution": {"text","source_hsd"},
      "provenance": {"source":"KB|HSDES","timestamp","confidence_tag":"High|Medium|Low"}
    }
Store only confirmed/observed content in kb_entry. Tag unproven items as hypothesis.
"""


def _detect_family(text: str) -> Optional[str]:
    t = (text or "").upper()
    for fam in ("GNR", "SRF", "CWF"):
        if fam in t:
            return fam
    return None


async def analyze(hsd_id: str, symptoms: str,
                  hsdes_token: Optional[str] = None) -> Dict[str, Any]:
    # Request-scoped HSDES client using the caller's own token.
    client = HSDESClient(hsdes_token)
    family = _detect_family(f"{symptoms} {hsd_id}")

    # Step 0 - RECALL
    recall = kb.search(symptoms, family=family)

    # Step 2 - INVESTIGATE (target always fetched; similar only if KB not High)
    target = await client.get_article(hsd_id)
    similar: List[Dict[str, Any]] = []
    if recall["confidence"] != "High":
        similar = await client.search_similar(symptoms)

    # Step 4 - REPORT
    if llm.enabled:
        report_md, kb_entry = await _llm_report(
            hsd_id, symptoms, family, recall, target, similar, client.enabled
        )
    else:
        report_md, kb_entry = _offline_report(
            hsd_id, symptoms, family, recall, target, similar, client.enabled
        )

    # Step 3 - WRITE-BACK
    kb_action = kb.upsert(kb_entry) if kb_entry else {"action": "skipped"}

    return {
        "mode": "llm" if llm.enabled else "offline",
        "hsdes_enabled": client.enabled,
        "family": family,
        "kb_recall": recall,
        "target": target,
        "similar": similar,
        "kb_action": kb_action,
        "report_markdown": report_md,
    }


async def _llm_report(hsd_id, symptoms, family, recall, target, similar,
                      hsdes_enabled) -> Tuple[str, Dict[str, Any]]:
    context = {
        "input": {"hsd_id": hsd_id, "symptoms": symptoms, "family": family},
        "kb_recall": recall,
        "target_hsd": target,
        "similar_hsds": similar,
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "CONTEXT:\n" + json.dumps(context, indent=2)},
    ]
    raw = await llm.chat(messages)
    parsed = _extract_json(raw)
    if parsed and "report_markdown" in parsed:
        return parsed["report_markdown"], parsed.get("kb_entry") or _fallback_entry(
            hsd_id, symptoms, family, target, hsdes_enabled
        )
    # LLM returned prose only - use it as the report, still learn a basic entry.
    return raw, _fallback_entry(hsd_id, symptoms, family, target, hsdes_enabled)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _fallback_entry(hsd_id, symptoms, family, target, hsdes_enabled) -> Dict[str, Any]:
    from time import gmtime, strftime
    target = target or {}
    # Learn from the full ticket text when available (title + description + comments),
    # not just the typed symptoms.
    ticket_text = target.get("full_text") or target.get("description") or ""
    error_string = (symptoms + ("\n" + ticket_text if ticket_text else "")).strip()
    fam = family or target.get("family") or ""
    return {
        "signature": {
            "family": fam,
            "stepping": target.get("stepping", ""),
            "unit": "RDT" if "rdt" in error_string.lower() else (
                "UPI" if "upi" in error_string.lower() else ""),
            "error_string": error_string[:2000],
            "key_terms": normalize_terms(f"{symptoms} {target.get('title', '')}"),
        },
        "similar_hsds": [],
        "root_cause": {"text": "", "confidence": "hypothesis"},
        "debug_steps": [],
        "resolution": {"text": "", "source_hsd": hsd_id if target.get("title") else ""},
        "provenance": {
            "source": "HSDES" if hsdes_enabled else "KB",
            "timestamp": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
            "confidence_tag": "Medium" if target.get("full_text") else "Low",
        },
    }


def _offline_report(hsd_id, symptoms, family, recall, target, similar,
                    hsdes_enabled) -> Tuple[str, Dict[str, Any]]:
    fam = family or "unknown"
    unit = "RDT" if "rdt" in symptoms.lower() else (
        "UPI" if "upi" in symptoms.lower() else "unknown")

    def tval(k, default="_not available_"):
        if target and target.get(k):
            return target[k]
        return default

    lines: List[str] = []
    lines.append(f"# Auto HSD Analyser report — {hsd_id}")
    lines.append("")
    lines.append("> **OFFLINE mode** — no LLM configured. This is a deterministic "
                 "report built from KB + HSDES data. Configure `LLM_BASE_URL` / "
                 "`LLM_API_KEY` for full reasoning.")
    lines.append("")

    lines.append("## A. Target HSD summary")
    if target and not target.get("error"):
        lines.append(f"- **ID:** {hsd_id}")
        lines.append(f"- **Title:** {tval('title')}")
        lines.append(f"- **Family / Release:** {tval('family')} / {tval('release')}")
        lines.append(f"- **Component:** {tval('component')}")
        lines.append(f"- **Stepping:** {tval('stepping')}")
        lines.append(f"- **Status:** {tval('status')}  |  **Priority:** {tval('priority')}")
        lines.append(f"- **Owner:** {tval('owner')}")
        desc = target.get("description") or ""
        if desc:
            snippet = desc if len(desc) <= 600 else desc[:600] + "…"
            lines.append(f"- **Description:** {snippet}")
        ncomments = len(target.get("comments") or [])
        lines.append(f"- **Comments read:** {ncomments}")
    else:
        reason = (target.get("error") if target
                  else "no HSDES token supplied for this request")
        lines.append(f"- **ID:** {hsd_id}")
        lines.append(f"- HSDES data unavailable ({reason}).")
    lines.append(f"- **Reported signature (from input):** {symptoms}")
    lines.append("")

    lines.append("## B. KB recall result")
    lines.append(f"- **Confidence:** {recall['confidence']} "
                 f"(best score {recall['best_score']})")
    if recall["matches"]:
        for m in recall["matches"]:
            lines.append(f"  - `{m.get('sig_key','')}` — root cause: "
                         f"{m.get('root_cause') or '_none recorded_'} "
                         f"(score {m.get('match_score')})")
    else:
        lines.append("- No matching learned cases yet — this will seed the KB.")
    lines.append("")

    lines.append("## C. Similar HSDs")
    lines.append("| ID | Source | Similarity reason | Root cause | Status |")
    lines.append("|----|--------|-------------------|------------|--------|")
    for m in recall["matches"]:
        lines.append(f"| {m.get('source_hsd') or '—'} | KB | "
                     f"terms: {', '.join(m.get('matched_terms', []))} | "
                     f"{m.get('root_cause') or '—'} | {m.get('confidence_tag','—')} |")
    for s in similar:
        lines.append(f"| {s.get('id','')} | HSDES | keyword match | — | "
                     f"{s.get('status','')} |")
    if not recall["matches"] and not similar:
        lines.append("| — | — | no matches | — | — |")
    lines.append("")

    lines.append("## D. Ranked root-cause hypotheses")
    lines.append(f"1. *(hypothesis)* {unit} failure on {fam} consistent with the "
                 "reported signature. Evidence: input symptoms; "
                 f"{'KB match' if recall['matches'] else 'no prior KB match'}.")
    lines.append("2. *(hypothesis)* Configuration / stepping-specific behavior — "
                 "confirm stepping and ucode before deeper isolation.")
    lines.append("")

    lines.append("## E. Detailed next debug steps")
    if unit == "UPI":
        lines.append("1. **Check UPI link/CRC error status** — read the UPI error "
                     "registers to confirm the failing link and error type.")
        lines.append("   - `sv.socket0.upi.upi<port>.ktilk_dfx_error_status.read()` "
                     "*(confirm exact reg name for your stepping)*")
        lines.append("   - If CRC/retry counters are set → link-integrity path; "
                     "else → protocol/transaction path.")
        lines.append("2. **Decode the MCE** for the reported bank (RIP + status).")
        lines.append("   - `sv.socket0.uncore.mca_bank<N>.status.read()` then decode "
                     "MCACOD/MSCOD.")
    elif unit == "RDT":
        lines.append("1. **Check RDT (RMID/CLOS) programming and QoS event state.**")
        lines.append("   - `sv.socket0.uncore.rdt.<reg>.read()` "
                     "*(confirm exact path for your stepping)*")
        lines.append("   - If monitoring counters mismatch → RMID mapping issue; "
                     "else → enforcement path.")
        lines.append("2. **Decode the associated MCE** if any bank is flagged.")
    else:
        lines.append("1. **Identify failing unit** from the bucket / MCE bank in the "
                     "symptom signature, then read that unit's error status register.")
        lines.append("   - `sv.socket0.<unit>.<error_status_reg>.read()`")
    lines.append("3. **Collect logs** — grep the RPT for the error string and bucket "
                 "id; capture ucode/BIOS rev.")
    lines.append("")

    lines.append("## F. Data to request/collect")
    lines.append("- RPT / rpt.gz (full), failing bucket id, cluster")
    lines.append("- Silicon stepping, ucode patch rev, BIOS/IFWI rev")
    lines.append("- MCE bank number + RIP, relevant waveform if available")
    lines.append("")

    lines.append("## G. Learning summary")
    lines.append("- A KB entry is being created/updated for this signature, tagged "
                 "**Low / hypothesis** (offline mode collects the signature but not a "
                 "confirmed root cause).")
    lines.append("")

    lines.append("## H. Known-issue verdict")
    if recall["confidence"] in ("High", "Medium"):
        lines.append("- **Likely known** — see KB matches in section C. Verify against "
                     "HSDES before closing.")
    else:
        lines.append("- **Likely new sighting** — no confident KB/HSDES match found.")

    entry = _fallback_entry(hsd_id, symptoms, family, target, hsdes_enabled)
    entry["signature"]["unit"] = unit if unit != "unknown" else ""
    return "\n".join(lines), entry
