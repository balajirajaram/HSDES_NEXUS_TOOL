"""Orchestrates the self-learning triage loop — DOMAIN-AGNOSTIC.

Works for ANY Intel server-platform HSD (silicon RAS/UPI/MCA, memory, PCIe/CXL,
power / S-states, BIOS/IFWI/BMC/boot, OS/driver, manageability, etc.) — it is
NOT tied to any single unit or domain.

Flow (runs on every request):
  Step 0 RECALL      -> KB search + confidence
  Step 1 DECIDE      -> High = KB-first; else source fallback
  Step 2 INVESTIGATE -> read target HSD (fully) + similar HSDs
  Step 3 WRITE-BACK  -> upsert KB entry (confirmed vs hypothesis)
  Step 4 REPORT      -> A-H markdown report

Reads via the configured reader (MCP reader if enabled, else HSDES REST). Uses
the LLM when configured; otherwise a deterministic OFFLINE report. Never
fabricates HSD IDs, register names, or commands.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import config
from .hsdes_client import HSDESClient
from .kb_store import KBStore, normalize_terms
from .llm_client import llm
from .log_analyzer import analyze_log
from .comment_analyzer import analyze_comments
from .knowledge_base import match_knowledge, lookup_bios_code
from .products import detect_product, master_queries, product_display
from .transferred_sync import sync_transferred, extract_axon_uuids, canonical_axon_url
from .mcp_enrich import enrich as mcp_enrich, enrichment_enabled
from .log_triage import triage_logs
from .axon_record import fetch_axon_records

kb = KBStore(config.KB_DB_PATH)


def _short(text: Any, n: int = 140) -> str:
    """Collapse whitespace/newlines and truncate for clean table display."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return (s[:n] + "…") if len(s) > n else s

SYSTEM_PROMPT = """You are an expert Intel server-platform debug engineer. You triage
HSD-ES tickets across ANY domain — CPU/silicon RAS (MCA/MCE/IERR/CATERR), UPI/coherency,
memory (DDR/DIMM/training), IO (PCIe/CXL), power and sleep states (S3/S4/S5/Sx, ACPI),
BIOS/IFWI/BMC/CPLD and boot/hang/reset, OS/driver (Windows/Linux), and manageability.
You cover GNR, SRF and CWF today and the SAME method extends to future products (DMR, COR).

You act as an AGENTIC end-to-end director. Ground every answer in evidence from:
  1. the target HSD (title + description + comments),
  2. the product's HSDES master-query corpus of similar/known issues (the KB + provided
     similar HSDs) — use it to say whether this is a known issue and how it was resolved,
  3. internal wikis/specs for architectural context, and
  4. register/code sources for the EXACT PythonSV commands.
You reason strictly from evidence and NEVER fabricate HSD IDs, register names, or commands.

You are given: the target HSD data (title, description, comments — may be partial),
matched cases from a learned Knowledge Base (KB), similar HSDs, attached-log findings,
the comment investigation, and (optionally) transferred sub-team ticket findings. Produce a
professional **Root Cause Analysis** report in Markdown with a clear, sectioned structure
modelled on a formal RCA (like a silicon-debug RCA memo). Use EXACTLY these sections and
headings, in this order:

# Root Cause Analysis — HSD <id>
A metadata block (Markdown table) with: Date, Platform/Family, Component/Domain,
Status/Priority, Owner.

## Artifacts Under Analysis
The ticket, number of comments parsed, attachments/log files scanned (name each file).

## Findings Summary
A short, scannable overview: the failure signature (from logs/comments), the proposed root
the proposed root cause in one line, and a confidence read.

## Analysis Methodology
Bullet list of exactly what you inspected and how (ticket read, N comments, M log lines,
signatures/MCA decode, KB recall, and transferred-ticket follow).

## Measured Data / Evidence
Where logs or comments contain concrete values (signatures, MCA status words, event timeline,
bandwidth/error counters, register values), present them as Markdown TABLES (source→value,
or event timeline). If no measured data is available, say so briefly.

## Root Cause
The primary root cause, labelled clearly as **confirmed from data** vs **hypothesis**, tied
to specific supporting evidence. Then a numbered list of ranked alternative hypotheses, each
with its supporting/contradicting evidence.

## Secondary Observations
Other signatures, secondary domains, already-tried paths — numbered.

## Recommended Fix
A NUMBERED method (concrete, ordered steps — e.g. exact PythonSV reads, revision A/B,
ingredient/BKC update, re-validate) and end with a bold **Expected result:** line stating what
success looks like.

## Appendix
Similar-HSDs table (ID | Source: KB/HSDES | Similarity reason | Root cause | Status), KB
recall detail. Only include Axon recording links that are ACTUALLY present in the provided
ticket data — never invent an Axon search/Explore URL. Cite only HSD IDs present in the
provided data.

Rules: Only cite HSD IDs present in the provided data. If unsure of an exact register/command
path, say so and give the closest known one plus how to confirm it. Clearly separate
"confirmed from data" vs "hypothesis". NEVER fabricate HSD IDs, register names, values, or
commands.

Return a SINGLE JSON object (no prose outside it) with keys:
  "report_markdown": string  (the full RCA report in the section order above)
  "kb_entry": object matching this schema:
    {
      "signature": {"family","platform","stepping","domain","component","error_string",
                    "key_terms":[...]},
      "similar_hsds": [{"id","why_matched"}],
      "root_cause": {"text","confidence":"confirmed|hypothesis"},
      "debug_steps": ["..."],
      "resolution": {"text","source_hsd"},
      "provenance": {"source":"KB|HSDES|MCP","timestamp","confidence_tag":"High|Medium|Low"}
    }
Store only confirmed/observed content in kb_entry. Tag unproven items as hypothesis.
"""

# Broad platform tag list (extend freely). Used only as a label, not a filter.
_PLATFORMS = [
    "GNR AP", "GNR-AP", "GNR", "SRF", "CWF", "SPR", "EMR", "ICX", "CLX",
    "Eagle Stream", "Birch Stream", "Mountain Stream", "Diamond Rapids", "DMR",
]

# Domain hint library: keyword -> (domain label, [representative commands]).
_DOMAIN_HINTS: List[Tuple[str, str, List[str]]] = [
    (r"\bupi|ktil|kti\b|coheren|link\s*retrain",
     "UPI / coherency",
     ["`sv.socket0.upi.upi<port>.ktilk_ph_ctr_status.read()`  # confirm reg via tab-complete",
      "If CRC/retry counters set -> link-integrity path; else protocol/transaction path."]),
    (r"\brdt|rmid|clos|\bmba\b|qos|cmt|mbm",
     "RDT / QoS (RAS)",
     ["`sv.socket0.uncore.rdt.<reg>.read()`  # confirm path for your stepping",
      "Counter mismatch -> RMID/CLOS mapping; else enforcement path."]),
    (r"\bmca|mce|machine\s*check|ierr|caterr|mcerr|\bmsmi\b",
     "RAS / MCA",
     ["`sv.socket0.uncore.mca_bank<N>.status.read()` then decode MCACOD/MSCOD/RIP",
      "Bank + RIP identify the failing unit."]),
    (r"\bddr|dimm|memory|mrc|\btrain|rank|\bce\b|\bue\b|patrol\s*scrub",
     "Memory",
     ["Grep MRC/BIOS log for training step + channel/rank; capture DIMM SPD/config.",
      "Correlate CE/UE address to channel/rank/bank."]),
    (r"pcie|\bcxl\b|ltssm|link\s*train|lane|aer|retimer",
     "IO / PCIe / CXL",
     ["OS: `lspci -vvv` (Windows: check Device Manager / PnP); inspect LTSSM state + AER.",
      "Degraded width/speed -> equalization/retimer; AER errors -> correctable vs fatal."]),
    (r"\bs3\b|\bs4\b|\bs5\b|\bsx\b|hibernat|suspend|resume|\bacpi\b|sleep|\bdpmo\b|power\s*state",
     "Power / Sleep-state (Sx)",
     ["OS: `powercfg /a` (S-states available?), `powercfg /lastwake`, `powercfg /waketimers`.",
      "PythonSV/PMC: `pmc.Sx_check()`; inspect PMC SLP_Sx status registers.",
      "Kernel-Power events: Get-WinEvent System | where Id -in 41,42,107,187."]),
    (r"bios|ifwi|\bbmc\b|cpld|\bpost\b|\bboot|\bhang|\breset|coldboot|\bsbsp\b|\bs3m\b|softstrap",
     "BIOS / firmware / boot-hang",
     ["Capture serial/BIOS boot log; find last successful POST/checkpoint before hang.",
      "PythonSV: `sv.socket0.uncore.ubox.ncdecs.biosscratchpad<N>_cfg...read()` for progress.",
      "Compare firmware/ucode/IFWI/BMC revisions across passing vs failing runs."]),
    (r"windows|linux|driver|\bos\b|bsod|\bhang\b|watchdog|\bwhea\b",
     "OS / driver",
     ["Collect OS event/kernel logs; note OS build and driver versions.",
      "A/B the OS build (passing vs failing) to isolate OS vs firmware."]),
]


def _detect_platform(text: str) -> Optional[str]:
    # Product registry (products.json) drives detection — extensible to DMR/COR
    # without code changes. Falls back to the inline platform list.
    p = detect_product(text)
    if p:
        return product_display(p)
    t = (text or "").upper()
    for name in _PLATFORMS:
        if name.upper() in t:
            return name
    return None


def _detect_domains(text: str) -> List[Tuple[str, List[str]]]:
    """Return domains ranked by how strongly they appear (match frequency),
    strongest first, so the report focuses on the dominant domain(s)."""
    t = (text or "").lower()
    scored: List[Tuple[int, str, List[str]]] = []
    for pattern, label, cmds in _DOMAIN_HINTS:
        n = len(re.findall(pattern, t))
        if n:
            scored.append((n, label, cmds))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(label, cmds) for _, label, cmds in scored]


_RC_PAT = re.compile(
    r"(root[\s_-]?cause|caused by|due to|because of|\brca\b|culprit|isolated to)", re.I)
_FIX_PAT = re.compile(
    r"(fixed in|fix\s*[:=]|resolution\s*[:=]|resolved by|work[\s-]?around|\bw/?a\b|"
    r"mitigat|bkm|patched|corrected)", re.I)


def _extract_findings(target: Optional[Dict[str, Any]],
                      comment_findings: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Deterministically pull root-cause / resolution text. The ticket's COMMENT
    THREAD is the primary source (that's where debug converges); ticket fields
    and phrase-matching are fallbacks."""
    if not target:
        return {"root_cause": "", "resolution": "", "confidence": "hypothesis"}
    rec = target.get("raw", {}) or {}

    def gf(*names: str) -> str:
        for n in names:
            for k, v in rec.items():
                if v and (k == n or k.endswith("." + n)):
                    return str(v)
        return ""

    def is_prose(s: str) -> bool:
        # Skip code / logs / URLs so we capture human explanation, not snippets.
        if any(tok in s for tok in ("def ", "self.", "{", "}", "=>", "::", "http",
                                    ".py", "</", "/>", "import ", "()")):
            return False
        alpha = sum(c.isalpha() or c.isspace() for c in s)
        return len(s) >= 12 and alpha / max(1, len(s)) >= 0.65

    text = target.get("full_text", "") or ""
    rc_lines: List[str] = []
    fix_lines: List[str] = []
    for chunk in re.split(r"[\n.;]", text):
        s = chunk.strip()
        if not is_prose(s):
            continue
        if _RC_PAT.search(s) and len(rc_lines) < 2:
            rc_lines.append(s)
        if _FIX_PAT.search(s) and len(fix_lines) < 2:
            fix_lines.append(s)

    # Comment-mined findings take precedence — they reflect where debug converged.
    cf = comment_findings or {}
    root_cause = cf.get("root_cause") or " ".join(rc_lines) or gf(
        "fix_description", "executive_summary")
    resolution = cf.get("workaround") or " ".join(fix_lines) or gf(
        "closed_reason", "status_reason")
    status = (target.get("status") or "").lower()
    strong_comment_rc = bool(cf.get("root_cause") and cf.get("workaround"))
    confirmed = (status in ("closed", "complete", "verified")
                 and bool(root_cause or resolution)) or strong_comment_rc
    return {
        "root_cause": root_cause[:400],
        "resolution": resolution[:400],
        "confidence": "confirmed" if confirmed else "hypothesis",
    }


async def analyze(hsd_id: str, symptoms: str,
                  hsdes_token: Optional[str] = None,
                  username: Optional[str] = None,
                  password: Optional[str] = None,
                  log_text: Optional[str] = None,
                  fetch_attachments: bool = False,
                  follow_transferred: bool = True,
                  reference_hsd_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    def _normalize_ref_ids(ids: Optional[List[str]], self_id: str) -> List[str]:
        out: List[str] = []
        seen: set = set()
        for raw in (ids or []):
            rid = re.sub(r"\D", "", str(raw or "").strip())
            if not rid or rid == self_id or rid in seen:
                continue
            seen.add(rid)
            out.append(rid)
        return out

    def _extract_clone_ref_ids(tgt: Optional[Dict[str, Any]], self_id: str) -> List[str]:
        text = (tgt or {}).get("full_text", "") or ""
        if not text:
            return []
        hits: List[str] = []
        pats = [
            r"clon(?:e|ed|ing)?[^0-9]{0,80}(1[56]\d{8,9})",
            r"parent\s+record[^0-9]{0,80}(1[56]\d{8,9})",
            r"original\s+hsd[^0-9]{0,80}(1[56]\d{8,9})",
        ]
        for p in pats:
            hits.extend(re.findall(p, text, re.I))
        return _normalize_ref_ids(hits, self_id)

    def _has_strong_log_evidence(findings: Optional[Dict[str, Any]]) -> bool:
        if not findings:
            return False
        if findings.get("mca_decode"):
            return True
        sigs = findings.get("signatures") or []
        fatal = sum(int(s.get("count", 0)) for s in sigs if str(s.get("severity", "")).lower() == "fatal")
        high = sum(int(s.get("count", 0)) for s in sigs if str(s.get("severity", "")).lower() == "high")
        return fatal >= 2 or (fatal >= 1 and high >= 3)

    client = HSDESClient(hsdes_token, username, password)
    # Text we reason over = typed symptoms (target text is added after fetch).
    platform = _detect_platform(f"{symptoms} {hsd_id}")

    # Step 0 - RECALL (domain-agnostic: no family filter; exclude self-match)
    recall = kb.search(symptoms, exclude_id=hsd_id)

    # Step 2 - INVESTIGATE
    target = await client.get_article(hsd_id)
    # Discover REAL file attachments via the HSDES attachments API (SOL zips,
    # PythonSV dumps, crashdump JSON), falling back to inline resource links.
    attachment_meta: List[Dict[str, Any]] = []
    if target and not target.get("error"):
        try:
            _tenant = str((target.get("raw") or {}).get("tenant") or "server_platf")
            attachment_meta = await client.list_attachments(hsd_id, tenant=_tenant)
        except Exception:
            attachment_meta = []
    if not attachment_meta and target:
        attachment_meta = [{"id": rid, "name": ""}
                           for rid in client.attachment_ids(target)]
    attachments = [a["id"] for a in attachment_meta]

    reference_hsds: List[Dict[str, Any]] = []

    # Read the comment thread like a human analyst — this is where debug converges.
    comment_source: List[Dict[str, str]] = list((target or {}).get("comments_structured", [])) if target else []
    comment_findings = analyze_comments(comment_source) if comment_source else None

    # Optional MCP enrichment: also ask the Geni + Co-Design HSDES agents and fold
    # their answers into the ticket context (grounds the report in every source).
    mcp_sources: List[str] = []
    if target and not target.get("error") and enrichment_enabled():
        try:
            mcp_context = await mcp_enrich(hsd_id, symptoms)
        except Exception:
            mcp_context = []
        if mcp_context:
            extra = "\n\n".join(
                f"### {c['source']} (MCP)\n{c['text']}" for c in mcp_context)
            target = dict(target)
            target["full_text"] = (
                (target.get("full_text", "") or "")
                + "\n\n== EXTERNAL SOURCES (Geni / Co-Design MCP) ==\n" + extra).strip()
            mcp_sources = [c["source"] for c in mcp_context]

    # Transferred-ticket sync is decided later by the auto-orchestrator.
    transferred = None

    # Logs: any pasted log + (optionally) the logs already attached to the ticket.
    combined_log = log_text or ""
    fetched = 0
    attach_files: List[str] = []
    if fetch_attachments and attachments:
        atext = await client.fetch_attachment_text(target, attachments=attachment_meta)
        if atext:
            combined_log = (combined_log + "\n" + atext).strip()
            fetched = len(attachments)
            # Reduce each marker to "<resource_id>:<basename>" then de-duplicate,
            # so multi-member zips / long paths don't show repeated entries.
            clean_files: List[str] = []
            for f in re.findall(r"### attachment ([^\n]+)", atext):
                f = f.strip()
                if ":" in f:
                    rid, name = f.split(":", 1)
                    name = re.split(r"[\\/]", name.strip())[-1]
                    f = f"{rid.strip()}:{name}"
                clean_files.append(f)
            attach_files = list(dict.fromkeys(clean_files))

    # Axon: fetch linked recordings (CLI) and fold their log content into the
    # decode + metadata into the report, so Axon evidence is triaged too.
    axon_records: List[Dict[str, Any]] = []
    axon_uuids = sorted(extract_axon_uuids((target or {}).get("full_text", "") or ""))
    if axon_uuids and target and not target.get("error"):
        try:
            axon_records = await fetch_axon_records(axon_uuids)
        except Exception:
            axon_records = []
        for rec in axon_records:
            for i, ctext in enumerate(rec.get("log_texts", []) or []):
                combined_log = (combined_log + f"\n### attachment axon:{rec['uuid'][:8]}#{i}\n"
                                + ctext).strip()
        if target is not None:
            target = dict(target)
            target["axon_records"] = axon_records
            # Collect SVTools failure signatures from Axon for precise root cause
            axon_sigs: List[str] = []
            for rec in axon_records:
                sigs_str = rec.get("svtools_signatures") or ""
                if sigs_str:
                    axon_sigs.extend(s.strip() for s in sigs_str.split(";") if s.strip())
            if axon_sigs:
                target["axon_svtools_signatures"] = axon_sigs
            # Even without CLI/Geni, surface known SVTools sigs from the Axon URL
            # if the ticket description/comments already contain them (e.g. from
            # a PythonSV Axon paste).  Nothing extra needed — already in full_text.

    log_findings = analyze_log(combined_log) if combined_log.strip() else None
    # End-to-end decode of SOL / PythonSV / POST logs via the bundled Intel
    # decoder databases (EWL / RC-Fatal / MCHECK / MCA / POST) — attached to the
    # findings so a fresh HSD with logs is triaged without manual effort.
    if log_findings is not None:
        try:
            log_findings["decoded"] = triage_logs(combined_log)
        except Exception:
            log_findings["decoded"] = None

    # Auto depth orchestration (no user knobs):
    # 1) KB recall, 2) current-ticket logs/comments, 3) clones/similar/transferred only if needed.
    top_match = (recall.get("matches") or [{}])[0]
    kb_known = (recall.get("confidence") == "High") and bool(
        top_match.get("root_cause") or top_match.get("resolution"))
    comment_known = bool((comment_findings or {}).get("root_cause"))
    log_known = _has_strong_log_evidence(log_findings)
    auto_history = not (kb_known or comment_known or log_known)

    if auto_history and target and not target.get("error"):
        merged_ref_ids = _normalize_ref_ids(reference_hsd_ids, str(hsd_id))
        auto_ref_ids = _extract_clone_ref_ids(target, str(hsd_id))
        merged_ref_ids = _normalize_ref_ids(merged_ref_ids + auto_ref_ids, str(hsd_id))
        if merged_ref_ids and client.enabled:
            for rid in merged_ref_ids[:5]:
                try:
                    ref = await client.get_article(rid)
                except Exception:
                    ref = None
                if not ref or ref.get("error"):
                    continue
                reference_hsds.append(ref)

        if target and reference_hsds:
            target = dict(target)
            summaries: List[Dict[str, Any]] = []
            ref_blocks: List[str] = []
            merged_comments: List[Dict[str, str]] = list((target or {}).get("comments_structured", []))
            for ref in reference_hsds:
                rid = str(ref.get("id") or "")
                rtitle = str(ref.get("title") or "")
                rdesc = str(ref.get("description") or "")
                rcomments = list(ref.get("comments") or [])
                summaries.append({
                    "id": rid,
                    "title": rtitle,
                    "status": ref.get("status") or "",
                    "owner": ref.get("owner") or "",
                    "comment_count": len(rcomments),
                })
                ref_blocks.append(
                    "\n\n".join(filter(None, [
                        f"REFERENCE HSD: {rid}",
                        f"TITLE: {rtitle}" if rtitle else "",
                        f"DESCRIPTION:\n{rdesc}" if rdesc else "",
                        ("COMMENTS:\n" + "\n".join(rcomments)) if rcomments else "",
                    ]))
                )
                for c in (ref.get("comments_structured") or []):
                    cc = dict(c)
                    cc["author"] = f"{cc.get('author', '')}@HSD{rid}".strip("@")
                    merged_comments.append(cc)
            target["reference_hsds"] = summaries
            target["full_text"] = (
                (target.get("full_text", "") or "")
                + "\n\n== REFERENCE HSD THREADS (auto clone enrichment) ==\n"
                + "\n\n".join(ref_blocks)
            ).strip()
            comment_findings = analyze_comments(merged_comments) if merged_comments else comment_findings
            if comment_findings:
                comment_findings = dict(comment_findings)
                comment_findings["reference_hsds_used"] = [str(r.get("id") or "") for r in reference_hsds]

    blob = f"{symptoms} " + (target.get("full_text") or target.get("description") or ""
                             if target else "")
    if log_findings:
        blob += " " + " ".join(s["label"] for s in log_findings["signatures"])
    if not platform:
        platform = _detect_platform(blob)
    similar: List[Dict[str, Any]] = []
    if auto_history and recall["confidence"] != "High":
        similar = await client.search_similar(symptoms)

    if auto_history and follow_transferred and target and not target.get("error"):
        try:
            transferred = await sync_transferred(client, target)
        except Exception:
            transferred = None

    # Step 4 - REPORT
    if llm.enabled:
        report_md, kb_entry = await _llm_report(
            hsd_id, symptoms, platform, recall, target, similar, client.enabled,
            log_findings, comment_findings, transferred
        )
    else:
        report_md, kb_entry = _offline_report(
            hsd_id, symptoms, platform, recall, target, similar, client.enabled,
            log_findings, attachments, fetched, attach_files, comment_findings,
            transferred, fetch_attempted=fetch_attachments
        )

    # Step 3 - WRITE-BACK
    kb_action = kb.upsert(kb_entry) if kb_entry else {"action": "skipped"}

    return {
        "mode": "llm" if llm.enabled else "offline",
        "hsdes_enabled": client.enabled,
        "family": platform,          # kept key name for UI compatibility
        "kb_recall": recall,
        "target": target,
        "similar": similar,
        "attachments": attachments,
        "attachments_fetched": fetched,
        "attachment_files": attach_files,
        "log_findings": log_findings,
        "comment_findings": comment_findings,
        "reference_hsds_used": [str(r.get("id") or "") for r in reference_hsds],
        "history_mode": auto_history,
        "transferred_sync": transferred,
        "mcp_sources": mcp_sources,
        "axon_records": axon_records,
        "kb_action": kb_action,
        "report_markdown": report_md,
    }


async def _llm_report(hsd_id, symptoms, platform, recall, target, similar,
                      hsdes_enabled, log_findings=None,
                      comment_findings=None, transferred=None) -> Tuple[str, Dict[str, Any]]:
    context = {
        "input": {"hsd_id": hsd_id, "symptoms": symptoms, "platform": platform},
        "kb_recall": recall,
        "target_hsd": target,
        "similar_hsds": similar,
        "attached_log_findings": log_findings,
        "comment_investigation": comment_findings,
        "transferred_ticket_sync": transferred,
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "CONTEXT:\n" + json.dumps(context, indent=2)},
    ]
    raw = await llm.chat(messages)
    parsed = _extract_json(raw)
    if parsed and "report_markdown" in parsed:
        return parsed["report_markdown"], parsed.get("kb_entry") or _fallback_entry(
            hsd_id, symptoms, platform, target, hsdes_enabled, comment_findings
        )
    return raw, _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled,
                                comment_findings)


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


def _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled,
                    comment_findings=None) -> Dict[str, Any]:
    from time import gmtime, strftime
    target = target or {}
    ticket_text = target.get("full_text") or target.get("description") or ""
    error_string = (symptoms + ("\n" + ticket_text if ticket_text else "")).strip()
    domains = [d for d, _ in _detect_domains(error_string)]
    findings = _extract_findings(target, comment_findings)
    return {
        "signature": {
            "family": platform or target.get("family") or "",
            "platform": platform or target.get("family") or "",
            "stepping": target.get("stepping", ""),
            "domain": ", ".join(domains[:3]),
            "component": target.get("component", ""),
            "error_string": error_string[:2000],
            "key_terms": normalize_terms(f"{symptoms} {target.get('title', '')}"),
        },
        "similar_hsds": [],
        "root_cause": {"text": findings["root_cause"], "confidence": findings["confidence"]},
        "debug_steps": [],
        "resolution": {"text": findings["resolution"],
                       "source_hsd": hsd_id if target.get("title") else ""},
        "provenance": {
            "source": "HSDES" if hsdes_enabled else "KB",
            "timestamp": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
            "confidence_tag": "Medium" if target.get("full_text") else "Low",
        },
    }


_VALID_FIXED_REASONS = {"fix_available", "implemented", "validated", "verified",
                        "fix_integrated", "fix_in_validation"}


def _validate_root_cause(cf: Optional[Dict[str, Any]],
                         target: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Grade HOW trustworthy the extracted root cause is — instead of trusting the
    words 'root cause'. Checks provenance (HSDES field vs pasted comment vs AI
    analysis), workflow corroboration, a recorded fix, and author authority, then
    returns a verdict (VALIDATED / PLAUSIBLE / UNVALIDATED HYPOTHESIS) + how to
    validate it."""
    cf = cf or {}
    rc = cf.get("root_cause") or ""
    if not rc:
        return None
    rec = (target or {}).get("raw", {}) or {}

    def gf(*names: str) -> str:
        for n in names:
            for k, v in rec.items():
                if v and (k == n or k.endswith("." + n)):
                    return str(v)
        return ""

    source = cf.get("root_cause_source") or "comment_statement"
    status = ((target or {}).get("status") or "").lower()
    reason = gf("reason").lower()
    owner = ((target or {}).get("owner") or "").lower()
    rc_author = (cf.get("root_cause_author") or "").lower()
    field_rc = gf("root_cause", "fix_description")
    fix_id = gf("fix_id", "fix_build")

    provenance_key = "hsdes_field" if field_rc else source
    _PROV = {
        "hsdes_field": "HSDES structured root_cause / fix_description field (engineer-filled)",
        "labeled_section": "a labeled 'ROOT CAUSE' section pasted into a comment",
        "ai_analysis": "a pasted AI/tool analysis in a comment (a hypothesis, not confirmed)",
        "resolution": "a closure / resolution statement in the comment thread",
        "comment_statement": "an engineer's statement in the comment thread",
    }

    checks: List[tuple] = []
    score = 0
    if field_rc:
        checks.append(("Root cause is filled in the HSDES structured field", True))
        score += 2
    else:
        checks.append(("HSDES structured root_cause field is EMPTY — the claim lives "
                       "only in a comment", False))
    if status in ("closed", "complete", "verified", "resolved") or reason in _VALID_FIXED_REASONS:
        checks.append((f"Ticket workflow corroborates it (status/reason: "
                       f"{status or reason})", True))
        score += 2
    else:
        checks.append((f"Ticket is still '{status or 'open'}' — the workflow has not "
                       "confirmed a root cause", False))
    if fix_id:
        checks.append((f"A fix ingredient / revision is recorded ({fix_id})", True))
        score += 1
    else:
        checks.append(("No fix ingredient / revision recorded yet", False))
    if rc_author and owner and (rc_author in owner or owner in rc_author):
        checks.append((f"Stated by the ticket owner ({cf.get('root_cause_author')})", True))
        score += 1
    elif rc_author:
        checks.append((f"Stated by {cf.get('root_cause_author')} — not the ticket owner", False))
    if provenance_key == "ai_analysis":
        checks.append(("Source is an AI/tool analysis — treat as an unvalidated hypothesis",
                       False))
        score -= 1
    if cf.get("workaround"):
        checks.append(("A candidate fix / workaround is proposed (not yet proven)", True))

    if field_rc and score >= 3:
        verdict = "VALIDATED"
    elif provenance_key == "ai_analysis" or score <= 1:
        verdict = "UNVALIDATED HYPOTHESIS"
    else:
        verdict = "PLAUSIBLE — needs confirmation"

    todo: List[str] = []
    if provenance_key == "ai_analysis":
        todo.append("Treat the pasted AI analysis as a hypothesis — have the owning "
                    "engineer confirm or reject it.")
    if not field_rc:
        todo.append("Ask the owner to record the confirmed cause in the HSDES "
                    "`root_cause` field once proven.")
    todo.append("Reproduce the failure and confirm the claimed mechanism on hardware "
                "(check the exact registers / values / structures named in the cause).")
    if cf.get("workaround"):
        todo.append("Apply the proposed fix and re-run the benchmark/test to prove the "
                    "measured delta actually closes.")

    return {"verdict": verdict, "provenance": _PROV.get(provenance_key, provenance_key),
            "provenance_key": provenance_key, "checks": checks, "score": score, "todo": todo}


def _render_investigation_timeline(L: List[str], cf: Dict[str, Any]) -> None:
    """Concise summary of the comment thread (NOT a full reproduction): a compact
    per-comment timeline, the few decisive pieces of evidence, the converged root
    cause and the disposition."""
    narrative = (cf or {}).get("narrative") or []
    if not narrative:
        return
    _KIND_ICON = {"root_cause": "🎯", "workaround": "🛠️", "finding": "🔎",
                  "action": "🔧", "next_step": "➡️", "note": "•"}
    L.append("## Investigation Summary (from ticket comments)")
    L.append("")
    # Compact timeline — one line per comment.
    for ev in narrative:
        dg = ev.get("digest") or {}
        icon = _KIND_ICON.get(ev.get("kind"), "•")
        who = _short(ev.get("author", ""), 18)
        tag = f" ({dg['tag']})" if dg.get("tag") else ""
        L.append(f"{ev['seq']}. {icon} **{who}{tag}:** {_short(ev.get('text', ''), 200)}")
    L.append("")

    # Only the decisive evidence, aggregated + de-duplicated across the thread.
    regs: List[str] = []
    cmds: List[str] = []
    n_exp = 0
    for ev in narrative:
        dg = ev.get("digest") or {}
        for r in dg.get("registers", []):
            if r not in regs:
                regs.append(r)
        for c in dg.get("commands", []):
            if c not in cmds:
                cmds.append(c)
        n_exp += len(dg.get("experiments", []))
    if regs or cmds or n_exp:
        L.append("**Key evidence:**")
        if regs:
            L.append("- Register / state: " + " · ".join(f"`{_short(r, 60)}`" for r in regs[:5]))
        if cmds:
            L.append("- Repro: " + " · ".join(f"`{_short(c, 70)}`" for c in cmds[:2]))
        if n_exp:
            L.append(f"- {n_exp} pass/fail experiment(s) recorded (full matrix in appendix).")
        L.append("")

    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        L.append(f"**🎯 Converged root cause (per {who}):** {_short(cf['root_cause'], 400)}")
        L.append("")
    disp = f"**📌 Disposition:** {cf.get('status_hint', 'unknown')}"
    if cf.get("handoff_team"):
        disp += f" — next owner: **{_short(cf['handoff_team'], 40)}**"
    L.append(disp)
    L.append("")


# Ticket statuses that mean the sighting is already dispositioned (not an active crash).
_RESOLVED_STATUSES = {
    "rejected", "closed", "duplicate", "implemented", "complete", "completed",
    "verified", "fixed", "resolved", "wont-fix", "won't fix", "not_a_bug", "invalid",
}
# Title/subject cues that a ticket is functional / reporting / config — not a hardware crash.
_FUNCTIONAL_HINTS = re.compile(
    r"not displaying|display|info table|dimm info|enumerat|non[- ]?por|population|"
    r"down[- ]?clock|downclocking|frequenc|\b\d{3,4}\s*mts\b|reporting|cosmetic|"
    r"boots successfully|knob|mapped out|does not show|not shown|incorrectly shown",
    re.I)


def _mca_is_incidental(target: Optional[Dict[str, Any]],
                       log_findings: Optional[Dict[str, Any]],
                       cf: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Decide whether a decoded MCA is incidental background telemetry rather than
    the ticket's real subject. True when the system booted to OS AND (the ticket is
    already dispositioned OR its subject is a functional/config/display topic), and
    no hardware root cause converged in the comment thread."""
    decoded = (log_findings or {}).get("decoded") or {}
    if not decoded.get("mca"):
        return (False, "")
    if not (decoded.get("boot_flow") or {}).get("reached_os"):
        return (False, "")
    if (cf or {}).get("root_cause"):
        return (False, "")  # comments already converged — handled on that path
    status = str((target or {}).get("status") or "").strip().lower()
    title = str((target or {}).get("title") or "")
    reasons: List[str] = []
    if status in _RESOLVED_STATUSES:
        reasons.append(f"ticket status '{status}'")
    if _FUNCTIONAL_HINTS.search(title):
        reasons.append("subject is a functional/config/display topic")
    if not reasons:
        return (False, "")
    return (True, " + ".join(reasons))


def _demoted_primary_line(target: Optional[Dict[str, Any]], cf: Optional[Dict[str, Any]]) -> str:
    """Lead line when the MCA is demoted: disposition + reported subject + last
    recorded conclusion from the comment thread (if any)."""
    status = str((target or {}).get("status") or "").strip().lower()
    title = _short(str((target or {}).get("title") or ""), 220)
    parts: List[str] = []
    if status:
        parts.append(f"Ticket dispositioned as **{status}**.")
    parts.append(f"Reported subject: {title}.")
    last_step = ((cf or {}).get("next_steps") or [None])[-1]
    if last_step:
        parts.append(f"Last thread note: {_short(last_step, 200)}.")
    parts.append("The decoded machine-check is **incidental background telemetry** "
                 "(system booted to OS) — not the reported failure.")
    return " ".join(parts)


def _render_debug_summary(L: List[str], hsd_id: str, target: Dict[str, Any],
                          log_findings: Optional[Dict[str, Any]],
                          cf: Dict[str, Any], rc_validation: Optional[Dict[str, Any]],
                          symptoms: str) -> None:
    """HSLE-Debug-Agent-style structured summary: RESULT + boot/stage progress +
    Symptom / Data Analysis / Metrics / Evidence / Hypothesis / Conclusion /
    Next Actions — driven by the decoded log evidence."""
    lf = log_findings or {}
    decoded = lf.get("decoded") or {}
    boot = decoded.get("boot_flow")
    sigs = lf.get("signatures", []) or []
    if not (decoded.get("mca") or decoded.get("bios") or decoded.get("post") or sigs or boot):
        return  # nothing decoded — the plain Findings Summary already covers it

    def tv(k, d="?"):
        return target.get(k) if target.get(k) else d

    # When the comment thread has already converged on a root cause, the broad
    # log-scan signatures (WHEA/MCA/PCIe from a verbose serial log) are incidental
    # background telemetry — lead with the real cause, not the noise.
    has_comment_rc = bool(cf.get("root_cause"))
    mca_demoted, demote_why = _mca_is_incidental(target, log_findings, cf)
    # Both cases mean the decoded MCA is background telemetry, not the headline.
    mca_incidental = has_comment_rc or mca_demoted

    # ---- RESULT line ----
    fail_where = ""
    if boot and boot.get("failing_stage"):
        fail_where = f"stopped before {boot['failing_stage']['label']}"
    elif boot and boot.get("last_reached"):
        fail_where = f"last reached {boot['last_reached']['label']}"
    top_fatal = next((s for s in sigs if s["severity"] == "fatal"), sigs[0] if sigs else None)
    sig_txt = (f"{top_fatal['label']} (x{top_fatal['count']})" if top_fatal else "")
    if has_comment_rc:
        result = " · ".join(filter(None, ["**FAIL**", fail_where,
                                          "root cause converged in comment thread"])) or "**REVIEW**"
    elif mca_demoted:
        _disp = str(tv('status', '')).strip().lower()
        result = " · ".join(filter(None, [
            "**REVIEW**", fail_where or "booted to OS",
            f"dispositioned ({_disp})" if _disp else "functional/config subject",
            "decoded MCA is incidental"]))
    else:
        result = " · ".join(filter(None, ["**FAIL**", fail_where, sig_txt])) or "**REVIEW**"

    L.append("## 🔧 Debug Summary")
    L.append(f"**RESULT:** {result}")
    L.append("")

    # ---- Boot / Stage Progress (Golden Flow) ----
    if boot and boot.get("stages"):
        L.append("### Boot / Stage Progress")
        L.append("| Stage | Status | Evidence |")
        L.append("|-------|--------|----------|")
        last_key = (boot.get("last_reached") or {}).get("key")
        fail_key = (boot.get("failing_stage") or {}).get("key")
        for s in boot["stages"]:
            if s["reached"]:
                mark = "✅ reached"
                if s["key"] == last_key:
                    mark = "✅ last reached"
            elif s["key"] == fail_key:
                mark = "❌ **did not start**"
            else:
                mark = "— not reached"
            ev_cell = _short(s.get("evidence", ""), 40).replace("|", "\\|") or "—"
            L.append(f"| {s['label']} | {mark} | {ev_cell} |")
        if boot.get("failure_markers"):
            L.append("")
            L.append(f"**Failure markers in log:** {', '.join(boot['failure_markers'])}")
        L.append("")

    # ---- Symptom ----
    L.append("### Symptom")
    L.append(f"- {_short(tv('title',''), 200)}")
    if symptoms:
        L.append(f"- Reported: {_short(symptoms, 160)}")
    L.append("")

    # ---- Data Analysis & Metrics ----
    L.append("### Data Analysis & Metrics")
    L.append(f"- **Log volume:** {lf.get('lines_scanned', 0):,} lines scanned")
    if sigs:
        _noise = (" — ⚠️ incidental background telemetry, NOT the reported failure"
                  if mca_incidental else "")
        L.append("- **Log keyword mentions** (raw count of matching log lines across the whole "
                 "log — inflated by verbose PythonSV/serial register dumps; **not** distinct "
                 "hardware events): " + " · ".join(
            f"{s['label']} (x{s['count']})" for s in sigs[:5]) + _noise)
    if decoded.get("mca"):
        mc = decoded["mca"]
        L.append(f"- **MCA:** {mc['count']} status value(s), "
                 f"{'UNCORRECTED' if mc['uncorrected'] else 'corrected'} — "
                 f"{mc.get('headline') or 'see appendix'}")
    if decoded.get("bios") and decoded["bios"].get("count"):
        bd = decoded["bios"]
        L.append(f"- **BIOS log codes:** {bd['count']} ({'FATAL' if bd['fatal'] else 'warning'})")
    if decoded.get("post"):
        last = decoded["post"]["codes"][-1]
        L.append(f"- **Last POST checkpoint:** `{last.get('code','')}` "
                 f"({last.get('description') or last.get('macro','')})")
    L.append("")

    # ---- Evidence ----
    ev: List[str] = []
    _ierr_ev = (decoded.get("ierr_table") or []) if decoded else []
    for row in _ierr_ev[:4]:
        ev.append(f"PythonSV UBOX: Socket{row['socket']} **{row['type']}** {row['priority']} "
                  f"← `{row['source_unit']}`"
                  + (f" @ `{row['address']}`" if row.get("address") else ""))
    for d in (lf.get("mca_decode") or [])[:1]:
        ev.append(f"MCA `{d['status']}` → {d.get('mcacod_text','?')} "
                  f"(flags {', '.join(d['flags']) or 'none'})")
    for e in (lf.get("evidence") or [])[:2]:
        for ln in e.get("lines", [])[:1]:
            ev.append(f"{e['category']}: `{_short(ln, 90)}`")
    if decoded and decoded.get("mca") and decoded["mca"].get("action"):
        ev.append(f"Recommended action (MCA DB): {_short(decoded['mca']['action'], 160)}")
    _axon_sigs_ev = (target.get("axon_svtools_signatures") or []) if target else []
    if _axon_sigs_ev:
        ev.append(f"Axon SVTools: {' · '.join(_axon_sigs_ev[:3])}")
    if ev:
        L.append("### Evidence")
        for e in ev:
            L.append(f"- {e}")
        L.append("")

    # ---- Hypothesis / Root Cause ----
    L.append("### Hypothesis / Root Cause")
    # Priority: a converged engineer statement in the comment thread is the
    # authoritative cause; precise PythonSV IERR / Axon SVTools corroborate it;
    # broad decoded MCA is only a fallback when nothing else converged.
    ierr_rows = (decoded.get("ierr_table") or []) if decoded else []
    axon_sigs = (target.get("axon_svtools_signatures") or []) if target else []
    if cf.get("root_cause"):
        tag = rc_validation["verdict"] if rc_validation else "reported"
        L.append(f"- (**converged from comment thread**, {tag}) {_short(cf['root_cause'], 320)}")
    elif mca_demoted:
        L.append(f"- (**reported subject / disposition** — {demote_why}) "
                 f"{_demoted_primary_line(target, cf)}")
    if ierr_rows:
        first_ierr = ierr_rows[0]
        L.append(f"- (**IERR from PythonSV UBOX table**) "
                 f"Socket {first_ierr['socket']} — {first_ierr['type']} {first_ierr['priority']} "
                 f"from **{first_ierr['source_unit']}**"
                 + (f" @ `{first_ierr['address']}`" if first_ierr.get("address") else ""))
    if axon_sigs:
        L.append("- (**Axon SVTools failure signatures from the linked recording:**)")
        for s in axon_sigs[:5]:
            L.append(f"  - `{s}`")
    if not cf.get("root_cause") and not ierr_rows and not axon_sigs:
        if mca_demoted:
            pass  # already led with the disposition/subject line above
        elif decoded and decoded.get("hypotheses"):
            top = decoded["hypotheses"][0]
            L.append(f"- (evidence-based, {top['severity']}) {_short(top['text'], 260)}")
        else:
            L.append("- Not yet determined — collect stronger runtime evidence (see Next Actions).")
    L.append("")

    # ---- Conclusion ----
    L.append("### Conclusion")
    concl = []
    if boot and boot.get("failing_stage"):
        concl.append(f"Boot did not progress past **{boot['last_reached']['label']}** "
                     f"(next expected: {boot['failing_stage']['label']}).")
    elif boot and boot.get("reached_os"):
        concl.append("System **booted to OS** — this is a **runtime / post-boot** failure, "
                     "not a boot hang.")
    if decoded.get("mca") and decoded["mca"]["uncorrected"]:
        if has_comment_rc:
            concl.append(f"An uncorrected machine-check was also decoded "
                         f"({decoded['mca'].get('headline','')}), but it is **incidental "
                         "background telemetry** — the converged root cause above (from the "
                         "comment thread) is the actual failure.")
        elif mca_demoted:
            concl.append(f"An uncorrected machine-check was decoded "
                         f"({decoded['mca'].get('headline','')}), but it is **incidental "
                         "background telemetry** — this ticket is a "
                         f"{'dispositioned' if str(tv('status','')).strip().lower() in _RESOLVED_STATUSES else 'functional/config'} "
                         "item (see reported subject above), not a machine-check crash.")
        else:
            concl.append(f"An **uncorrected machine-check** was decoded "
                         f"({decoded['mca'].get('headline','')}), consistent with the reported failure.")
    if not concl:
        concl.append("Failure isolated to the dominant decoded signature; confirm on hardware.")
    for c in concl:
        L.append(f"- {c}")
    L.append("")

    # ---- Next Actions ----
    L.append("### Next Actions")
    na: List[str] = []
    if decoded.get("mca") and decoded["mca"].get("action"):
        na.append(_short(decoded["mca"]["action"], 180))
    if boot and boot.get("failing_stage"):
        na.append(f"Inspect the BIOS/firmware path entering "
                  f"{boot['failing_stage']['label']} (right after the last checkpoint).")
    if decoded.get("bios") and decoded["bios"]["fatal"]:
        na.append("Decode the FATAL BIOS/RC error(s) in Appendix A3 and map to the failing IP.")
    na.append("Confirm the decoded root cause on hardware; capture MCA bank + RIP.")
    for i, s in enumerate(dict.fromkeys([x for x in na if x and x.strip()]), 1):
        L.append(f"{i}. {s}")
    L.append("")
    L.append("---")
    L.append("")


def _render_transferred(L: List[str], transferred: Optional[Dict[str, Any]]) -> None:
    """Render the transferred-ticket sync block (sub-team findings + a prepared,
    ready-to-post update comment) into the report line buffer ``L``."""
    if not transferred or not transferred.get("summaries"):
        return
    L.append("## 🔁 Transferred-Ticket Sync")
    L.append("")
    L.append("This sighting references a sub-team ticket. Latest findings pulled "
             "from the transferred ticket(s) below — review, then post the "
             "prepared comment back on this sighting.")
    L.append("")
    L.append("| Transferred HSD | Status | Fix? | Domain | Ingredient / Revision |")
    L.append("|-----------------|--------|------|--------|-----------------------|")
    for s in transferred["summaries"]:
        if s.get("error"):
            L.append(f"| {s.get('id','?')} | _fetch error_ | — | — | — |")
            continue
        fix = "✅" if s.get("fixed") else "—"
        status = _short(f"{s.get('status','?')} ({s.get('reason','?')})", 40)
        dom = _short(s.get("domain") or "—", 24)
        ing = _short(s.get("ingredient") or "—", 30)
        L.append(f"| {s.get('id','?')} | {status} | {fix} | {dom} | {ing} |")
    L.append("")
    for s in transferred["summaries"]:
        if s.get("error"):
            continue
        if s.get("root_cause"):
            L.append(f"- **{s['id']} root cause:** {_short(s['root_cause'], 300)}")
        if s.get("new_axon_uuids"):
            L.append(f"- **{s['id']} new Axon recording(s):** "
                     + ", ".join(s["new_axon_uuids"][:4]))
    L.append("")
    for s in transferred["summaries"]:
        cm = s.get("comment_markdown")
        if not cm:
            continue
        L.append(f"<details><summary>📋 Prepared update comment for sighting "
                 f"(from {s['id']}) — copy &amp; post on HSDES</summary>")
        L.append("")
        L.append("```markdown")
        L.append(cm)
        L.append("```")
        L.append("")
        L.append("</details>")
        L.append("")


def _extract_versions(target: Dict[str, Any]) -> Dict[str, str]:
    """Best-effort pull of BIOS / uCode / IFWI / BMC versions from the ticket text.
    Only accepts version-like tokens (must contain a digit and not be a bare column
    header word), so a headerless spec table doesn't yield label words as values."""
    text = (target or {}).get("full_text", "") or (target or {}).get("description", "") or ""
    _bad = {"microcode", "ucode", "stepping", "biosversion", "bmcversion", "bmc",
            "kernel", "version", "qdf", "memory", "config", "cpld", "pipeline",
            "ttf", "node", "bios", "ifwi", "details", "affected", "system"}
    pats = {
        "BIOS": r"(?i)bios[\s_]*version\s*[:=]?\s*([A-Za-z0-9][A-Za-z0-9._\-]{5,})",
        "uCode": r"(?i)(?:microcode|ucode)\s*[:=]?\s*(0x[0-9A-Fa-f]+|[0-9][0-9A-Za-z._\-]{2,})",
        "IFWI": r"(?i)ifwi(?:\s*version)?\s*[:=]?\s*([0-9A-Za-z][0-9A-Za-z._\-]{3,})",
        "BMC": r"(?i)bmc\s*version\s*[:=]?\s*([0-9A-Za-z][0-9A-Za-z._\-]{3,})",
    }
    out: Dict[str, str] = {}
    for label, pat in pats.items():
        for m in re.finditer(pat, text):
            val = m.group(1).strip()
            if val.lower() in _bad or not re.search(r"\d", val):
                continue  # skip label-word / non-version captures
            out[label] = val
            break
    return out


def _audit_root_cause_evidence(target: Dict[str, Any],
                               log_findings: Optional[Dict[str, Any]],
                               recall: Dict[str, Any],
                               similar: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Audit the 10 evidence items that separate a generic triage line from an
    engineer-grade root cause. Each item carries the concrete commands to collect
    it. Item: {label, present, detail, collect, commands}."""
    lf = log_findings or {}
    decoded = lf.get("decoded") or {}
    ev = decoded.get("evidence") or {}
    mca = decoded.get("mca") or {}
    versions = _extract_versions(target)
    axon_sigs = (target or {}).get("axon_svtools_signatures") or []
    sim = similar or []

    # Resolve the implicated MCA bank so MC_ADDR/MC_MISC MSR offsets are exact.
    bank_n: Optional[int] = None
    for b in (ev.get("mca_banks") or []):
        try:
            bank_n = int(b)
            break
        except (TypeError, ValueError):
            continue
    if bank_n is None:
        _b = str((ev.get("mc_status") or {}).get("bank") or "")
        if _b.isdigit():
            bank_n = int(_b)

    def item(label, present, detail="", collect="", commands=None):
        return {"label": label, "present": bool(present),
                "detail": detail if present else "", "collect": collect,
                "commands": [] if present else (commands or [])}

    audit: List[Dict[str, Any]] = []

    # 1. MCA bank number
    banks = ev.get("mca_banks") or []
    audit.append(item("MCA Bank Number", banks,
                      ("bank(s) " + ", ".join(banks)) if banks else "",
                      "enumerate the machine-check banks and identify the raising IP block",
                      ["rdmsr -a 0x179  # IA32_MCG_CAP → bank count (OS)",
                       "for N in $(seq 0 31); do echo bank $N; rdmsr -a $((0x401+4*N)); done",
                       "sv.sockets.uncore.mca.dump()  # PythonSV — all banks"]))

    # 2. MC_STATUS / MCACOD / MSCOD (+ flags)
    mcs = ev.get("mc_status") or {}
    have_status = bool(mca) or bool(mcs.get("mscod") or mcs.get("mcacod"))
    flags = ev.get("status_flags") or {}
    flag_txt = (" · flags " + " ".join(k for k, v in flags.items() if v)) if flags else ""
    detail2 = ""
    if have_status:
        detail2 = (" ".join(filter(None, [
            f"bank {mcs.get('bank')}" if mcs.get("bank") else "",
            f"MCACOD {mcs.get('mcacod')}" if mcs.get("mcacod") else "",
            f"MSCOD {mcs.get('mscod')}" if mcs.get("mscod") else "",
            f"= {mcs.get('decode')}" if mcs.get("decode") else (
                f"= {mca.get('headline')}" if mca.get("headline") else ""),
        ])).strip() + flag_txt)
    _sbank = f"$((0x401+4*{bank_n}))" if bank_n is not None else "0x401+4*N"
    audit.append(item("MC_STATUS / MCACOD / MSCOD", have_status, detail2,
                      "capture the full 64-bit MCi_STATUS (VAL/UC/PCC/ADDRV/MISCV + MCACOD/MSCOD)",
                      [f"rdmsr -a {_sbank}  # MC{bank_n if bank_n is not None else 'N'}_STATUS (OS)",
                       "sv.socket0.uncore.mca.dump()  # PythonSV — decode MCACOD/MSCOD + flags"]))

    # 3. MC_ADDR
    _addr = f"0x{0x402 + 4*bank_n:X}" if bank_n is not None else "0x402+4*N"
    audit.append(item("MC_ADDR (transaction address)", ev.get("mc_addr"),
                      ev.get("mc_addr", ""),
                      "read MCi_ADDR when ADDRV=1 to locate the offending address/transaction",
                      [f"rdmsr -a {_addr}  # MC{bank_n if bank_n is not None else 'N'}_ADDR (OS)",
                       "sv.socket0.uncore.mca.dump()  # PythonSV — MCi_ADDR field"]))

    # 4. MC_MISC
    _misc = f"0x{0x403 + 4*bank_n:X}" if bank_n is not None else "0x403+4*N"
    audit.append(item("MC_MISC (transaction detail)", ev.get("mc_misc"),
                      ev.get("mc_misc", ""),
                      "read MCi_MISC when MISCV=1 for request type / source / channel hints",
                      [f"rdmsr -a {_misc}  # MC{bank_n if bank_n is not None else 'N'}_MISC (OS)",
                       "sv.socket0.uncore.mca.dump()  # PythonSV — MCi_MISC field"]))

    # 5. RC-Fatal source agent
    audit.append(item("RC-Fatal / EWL Source Agent", ev.get("rc_fatal_agent"),
                      ev.get("rc_fatal_agent", ""),
                      "capture the RC-Fatal 'Agent =' / originating IP (e.g. IIO Stack 0, UPI Agent 0)",
                      ["grep -iE 'RC_FATAL|FATAL ERROR|Agent *=|MajorCode|MinorCode' <bios_serial.log>",
                       "python -m app.decoders.decode_ewl --log <bios_serial.log>"]))

    # 6. BIOS module / phase at failure
    audit.append(item("BIOS Module / Phase at Failure", ev.get("bios_module"),
                      ev.get("bios_module", ""),
                      "map the failing POST checkpoint to the BIOS phase + module (DXE / CpuSv / Host Interface)",
                      ["capture the POST/checkpoint code at the hang (BMC postcode buffer / port 80h)",
                       "grep -iE 'POST|checkpoint|DXE|PEI|BDS' <bios_serial.log> | tail -40"]))

    # 7. Versions
    audit.append(item("BIOS / uCode / IFWI / BMC Versions", versions,
                      ", ".join(f"{k}={v}" for k, v in versions.items()) if versions else "",
                      "record BIOS / uCode / IFWI / BMC versions to enable regression (first-fail) detection",
                      ["rdmsr 0x8B  # IA32_BIOS_SIGN_ID → uCode rev (OS)",
                       "dmidecode -t bios  # BIOS version",
                       "ipmitool mc info  # BMC + firmware/IFWI rev",
                       "cat /proc/cpuinfo | grep -m1 microcode"]))

    # 8. Socket information
    sockets = ev.get("sockets") or []
    audit.append(item("Socket Information", sockets,
                      ("socket(s) " + ", ".join(sockets)) if sockets else "",
                      "note which socket(s) fail — a socket-localized pattern points at CPU/board vs firmware",
                      ["sv.sockets  # enumerate sockets",
                       "sv.socket0.uncore.mca.dump(); sv.socket1.uncore.mca.dump()  # per-socket"]))

    # 9. Historical signature match
    hist = bool(axon_sigs) or recall.get("confidence") in ("High", "Medium") or bool(sim)
    hist_detail = ""
    if axon_sigs:
        hist_detail = f"Axon SVTools: {axon_sigs[0]}"
    elif recall.get("confidence") in ("High", "Medium"):
        hist_detail = f"KB match ({recall.get('confidence')} confidence)"
    elif sim:
        hist_detail = f"{len(sim)} similar HSD(s)"

    audit.append(item("Historical Signature Match", hist, hist_detail,
                      "search prior HSDs on MCACOD+MSCOD+bank+POST+RC-agent for a known-issue match",
                      ["query HSDES on MCACOD+MSCOD+bank+POST+RC-agent",
                       "query Axon for the same SVTools signature"]))

    # 10. Pass vs Fail configuration comparison (not derivable from a single failing log)
    audit.append(item("Pass vs Fail Configuration Comparison", False, "",
                      "A/B the ucode/BIOS/IFWI/OS + knobs between a passing and the failing run",
                      ["XmlCli: dump BIOS knobs on a passing and the failing run, then diff",
                       "record ucode/BIOS/IFWI/OS build IDs for both runs and compare"]))

    return audit


def _render_missing_evidence(L: List[str], audit: List[Dict[str, Any]]) -> None:
    """Report the concrete evidence decoded from the logs, then recommend the
    specific data still worth collecting to firm up the root cause. Presented as
    report prose + bullets (not a pass/fail checklist)."""
    if not audit:
        return
    have = [a for a in audit if a["present"]]
    missing = [a for a in audit if not a["present"]]

    L.append("## Root-Cause Evidence")
    L.append(f"Decoded **{len(have)} of {len(audit)}** of the key hardware/firmware facts "
             "needed to pin an engineer-grade root cause.")
    L.append("")

    if have:
        L.append("### Evidence on hand (decoded from the attached logs / Axon)")
        for a in have:
            detail = a["detail"] or "captured"
            L.append(f"- **{a['label']}:** {detail}")
        L.append("")

    if missing:
        L.append("### Recommended data to collect to confirm the root cause")
        L.append("The following would move this from a strong hypothesis toward a "
                 "confirmed root cause — capture and attach each item using the commands shown:")
        L.append("")
        for i, a in enumerate(missing, 1):
            L.append(f"{i}. **{a['label']}** — {a['collect']}.")
            for cmd in a.get("commands", []):
                L.append(f"    - `{cmd}`")
        L.append("")


def _offline_report(hsd_id, symptoms, platform, recall, target, similar,
                    hsdes_enabled, log_findings=None, attachments=None,
                    attachments_fetched=0, attach_files=None,
                    comment_findings=None, transferred=None,
                    fetch_attempted=False) -> Tuple[str, Dict[str, Any]]:
    target = target or {}
    attachments = attachments or []
    attach_files = attach_files or []
    cf = comment_findings or {}
    plat = platform or "unknown platform"
    blob = f"{symptoms} " + (target.get("full_text") or target.get("description") or "")
    if log_findings:
        blob += " " + " ".join(s["label"] for s in log_findings["signatures"])
    domains = _detect_domains(blob)[:3]  # focus on the dominant domain(s)

    def tval(k, default="_not available_"):
        return target[k] if target.get(k) else default

    findings = _extract_findings(target, comment_findings)
    rc_validation = _validate_root_cause(cf, target)
    # Evidence-completeness audit — the 10 hardware/firmware facts that move a
    # generic triage line toward an engineer-grade root cause.
    evidence_audit = _audit_root_cause_evidence(target, log_findings, recall, similar)

    def _known_verdict() -> str:
        if cf.get("root_cause"):
            return "Root cause identified in ticket comments"
        if recall["confidence"] in ("High", "Medium"):
            return "Likely known issue"
        if findings.get("confidence") == "confirmed":
            return "Likely known (confirmed in ticket history)"
        return "Likely new sighting"

    def _exec_confidence() -> int:
        score = 20
        if target and not target.get("error"):
            score += 20
        score += {"High": 30, "Medium": 20, "Low": 10, "None": 0}.get(
            recall.get("confidence", "None"), 0)
        if cf.get("root_cause"):
            score += 20
        if cf.get("workaround"):
            score += 10
        elif findings.get("resolution"):
            score += 5
        if log_findings and log_findings.get("signatures"):
            score += 10
        # Evidence completeness lifts confidence a few points per key fact present,
        # so a fully-instrumented failing log reads higher than a generic one.
        score += 2 * sum(1 for a in evidence_audit if a["present"])
        return min(97, score)


    top_sig = None
    if log_findings and log_findings.get("signatures"):
        top_sig = log_findings["signatures"][0]

    # Suspected area: prefer the attachment-derived mechanism, else ticket field.
    suspected_area = (log_findings or {}).get("suspected_area", "") if log_findings else ""
    if not suspected_area:
        rec = target.get("raw", {}) or {}
        for k, v in rec.items():
            if k.endswith("suspect_area") and v and str(v).lower() != "unknown":
                suspected_area = str(v)
                break

    # Failure point: prefer the comment-derived root cause (human conclusion),
    # then the log timeline's first fatal event, then nothing.
    if cf.get("root_cause"):
        failure_point = _short(cf["root_cause"], 200)
    else:
        failure_point = "Not found from current evidence"
        for ev in (log_findings or {}).get("timeline", []):
            if ev.get("failure_point"):
                detail = _short(ev.get("text", ""), 140)
                failure_point = (f"{ev.get('label', 'failure')} — {detail}"
                                 if detail else ev.get("label", "failure"))
                break

    # Next action: continue from the LAST recorded next-step, else evidence-led.
    if cf.get("next_steps"):
        next_action = f"Continue: {_short(cf['next_steps'][-1], 160)}"
    elif cf.get("root_cause"):
        next_action = "Confirm the comment-identified root cause on hardware, then verify the workaround."
    elif top_sig:
        next_action = "Start with attached-log failure signature and MCA/trace decode."
    else:
        next_action = "Start with dominant domain checks and collect stronger runtime evidence."

    L: List[str] = []
    from time import strftime
    ttitle = _short(tval("title", ""), 130)
    n_comments = len((target.get("comments") or [])) if target else 0

    # ---------- NICK-style RCA header + metadata ----------
    L.append(f"# Root Cause Analysis — HSD {hsd_id}")
    L.append("")
    if ttitle and ttitle != "_not available_":
        L.append(f"**{ttitle}**")
        L.append("")
    L.append("| Field | Value |")
    L.append("|-------|-------|")
    L.append(f"| **Date** | {strftime('%Y-%m-%d')} |")
    _family = tval('family', '')
    _component = tval('component', '')
    _domains_txt = ', '.join(d for d, _ in domains) or 'general'
    _comp_cell = f"{_component} · {_domains_txt}" if _component else _domains_txt
    L.append(f"| **Platform / Family** | {plat}{' / ' + _family if _family else ''} |")
    L.append(f"| **Component / Domain** | {_comp_cell} |")
    L.append(f"| **Status / Priority** | {tval('status','—')} / {tval('priority','—')} |")
    L.append(f"| **Owner** | {tval('owner','—')} |")
    L.append(f"| **Analyser mode** | Automated (offline log + ticket analysis) |")
    L.append("")

    # Robustness guard: the ticket lists attachments but none were scanned this run
    # (transient HSDES download failure) — flag it so a thin report isn't mistaken
    # for a clean one.
    _lines_scanned = (log_findings or {}).get("lines_scanned", 0) if log_findings else 0
    if fetch_attempted and attachments and (attachments_fetched == 0 or _lines_scanned == 0):
        L.append(f"> ⚠️ **Attachment fetch incomplete** — this ticket lists "
                 f"{len(attachments)} attachment(s) but none were downloaded/scanned this run "
                 "(transient HSDES fetch failure). The evidence below is based only on the "
                 "ticket text + comments and is therefore incomplete. **Re-run the analysis** "
                 "to pull the attached logs before trusting the confidence score.")
        L.append("")

    # ---------- Artifacts under analysis ----------
    L.append("## Artifacts Under Analysis")
    L.append(f"- **Ticket:** HSD {hsd_id} — {ttitle}")
    L.append(f"- **Comment thread:** {n_comments} comment(s) parsed")
    if attachments:
        note = (f"{attachments_fetched} downloaded &amp; scanned"
                if attachments_fetched else "not fetched — enable auto-fetch")
        L.append(f"- **Attachments:** {len(attachments)} on ticket ({note})")
        for f in (attach_files or [])[:8]:
            L.append(f"  - `{_short(f, 70)}`")
    if log_findings:
        L.append(f"- **Log volume analysed:** {log_findings.get('lines_scanned', 0)} line(s)")
    _mcp_src = target.get("mcp_sources") or []
    if _mcp_src:
        L.append(f"- **External sources queried:** {', '.join(_mcp_src)} (via MCP)")
    L.append("")

    # HSLE-Debug-Agent-style structured summary (Result / Stage Progress /
    # Symptom / Data / Evidence / Hypothesis / Conclusion / Next Actions).
    _render_debug_summary(L, hsd_id, target, log_findings, cf, rc_validation, symptoms)

    # Human-triage investigation timeline straight from the comment thread —
    # visible in the main body (not buried in the appendix) with full detail.
    _render_investigation_timeline(L, cf)

    # ---------- Findings summary (quick 4-part overview) ----------
    sigs = (log_findings or {}).get("signatures", []) if log_findings else []
    decoded = (log_findings or {}).get("decoded") if log_findings else None
    # Real Axon recordings actually linked in the ticket (no synthetic search URLs).
    axon_links = sorted(extract_axon_uuids(target.get("full_text", "") or ""))

    L.append(f"## Findings Summary  ·  confidence {_exec_confidence()}%")
    L.append("")


    # 1. Failure signature (attached logs & analysis)
    L.append("**1. Failure signature — from attached logs & analysis**")
    if sigs:
        L.append("- **Log keyword mentions** (raw matching lines, not distinct events): "
                 + " · ".join(f"{s['label']} (x{s['count']})" for s in sigs[:4]))
        if cf.get("root_cause"):
            L.append("- ⚠️ These broad log signatures are **incidental background telemetry** "
                     "from the verbose serial log — the actual failure is the converged root "
                     "cause in the Investigation Summary above, not these signatures.")
        for d in (log_findings.get("mca_decode") or [])[:1]:
            L.append(f"- **MCA decode:** `{d['status']}` → {d.get('mcacod_text','?')} "
                     f"(flags {', '.join(d['flags']) or 'none'})")
        if log_findings.get("last_checkpoint"):
            L.append(f"- **Last good checkpoint:** `{log_findings['last_checkpoint']}`")
        if suspected_area:
            L.append(f"- **Suspected area:** {suspected_area}")
    elif attachments:
        L.append(f"- {len(attachments)} attachment(s) on ticket — not fetched "
                 "(enable auto-fetch to scan logs).")
    else:
        L.append("- No logs attached to this ticket; analysis based on the "
                 "ticket description + comment thread.")
    # Deterministic decode of SOL / PythonSV / POST logs (Intel decoder DBs).
    if decoded:
        if decoded.get("mca"):
            mc = decoded["mca"]
            L.append(f"- **MCA decode ({'uncorrected' if mc['uncorrected'] else 'corrected'}, "
                     f"x{mc['count']}):** {mc.get('headline') or 'see appendix'}")
        if decoded.get("bios") and decoded["bios"].get("count"):
            bd = decoded["bios"]
            L.append(f"- **BIOS log decode ({'FATAL' if bd['fatal'] else 'warning'}, "
                     f"x{bd['count']}):** {bd.get('headline') or 'see appendix'}")
        elif decoded.get("bios") and decoded["bios"].get("benign_count"):
            bd = decoded["bios"]
            L.append(f"- **BIOS log decode:** no error codes; "
                     f"{bd['benign_count']} known expected/informational message(s) only.")
        if decoded.get("post"):
            last = decoded["post"]["codes"][-1]
            L.append(f"- **Last POST checkpoint:** `{last.get('code','')}` "
                     f"({last.get('description') or last.get('macro','')})")
    L.append("")

    # 2. Proposed root cause
    L.append("**2. Proposed root cause**")
    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        tag = (rc_validation["verdict"] if rc_validation else "reported")
        L.append(f"- (**{tag}**, per **{who}**) {_short(cf['root_cause'], 300)}")
        if rc_validation:
            L.append(f"- Source: {rc_validation['provenance']}")
        if suspected_area:
            L.append(f"- Mechanism/area: {suspected_area}")
    elif suspected_area:
        L.append(f"- (from logs) {suspected_area}")
    elif sigs:
        L.append(f"- (hypothesis) {sigs[0]['label']} on {plat} — see evidence below.")
    else:
        L.append("- Not yet determined from available data — see next steps.")
    if cf.get("workaround"):
        L.append(f"- **Workaround / fix:** {_short(cf['workaround'], 200)}")
    L.append("")

    # Linked Axon recordings — ONLY when the ticket actually contains Axon URLs.
    if axon_links:
        _arecs = {r["uuid"]: r for r in (target.get("axon_records") or [])}
        L.append("**Linked Axon recording(s):**")
        for u in axon_links[:6]:
            rec = _arecs.get(u)
            if rec and rec.get("available"):
                meta = " · ".join(filter(None, [
                    f"platform {rec['platform']}" if rec.get("platform") else "",
                    f"stepping {rec['stepping']}" if rec.get("stepping") else "",
                    f"plugin {rec['plugin']}" if rec.get("plugin") else "",
                    f"{len(rec.get('content_files') or [])} content file(s)"
                    if rec.get("content_files") else ""]))
                L.append(f"- {canonical_axon_url(u)} — **fetched** ({meta or 'record downloaded'})")
            elif rec:
                sigs_str = rec.get("svtools_signatures") or ""
                sigs_list = [s.strip() for s in sigs_str.split(";") if s.strip()]
                if sigs_list:
                    L.append(f"- {canonical_axon_url(u)} — **SVTools failure signatures** (via Geni):")
                    for sig in sigs_list[:6]:
                        L.append(f"  - `{sig}`")
                else:
                    L.append(f"- {canonical_axon_url(u)} — _not fetched. "
                             "Set `AXON_GENI_TOKEN` in `.env` (run acquire-tokens → axon) "
                             "to auto-fetch SVTools failure signatures._")
            else:
                L.append(f"- {canonical_axon_url(u)}")
        L.append("")

    # 3. Next steps
    L.append("**3. Proposed next steps**")
    ns: List[str] = []
    if cf.get("root_cause"):
        ns.append("Confirm the identified root cause on hardware "
                  + (f"(check {', '.join((cf.get('breadcrumbs') or {}).get('register', [])[:2])})"
                     if (cf.get('breadcrumbs') or {}).get('register') else ""))
    if cf.get("next_steps"):
        ns.append(_short(cf["next_steps"][-1], 150))
    if sigs:
        ns.append(f"Corroborate the top log signature ({sigs[0]['label']}) and decode the MCA bank.")
    if axon_links:
        ns.append("Review the linked Axon recording(s) above.")
    if cf.get("workaround"):
        ns.append("Validate the workaround and track the permanent fix.")
    if not cf.get("root_cause") and not sigs:
        ns.append("Collect serial/BIOS/OS logs + revisions (ucode/BIOS/IFWI/OS) and re-run.")
    for i, s in enumerate(dict.fromkeys([x for x in ns if x and x.strip()]), 1):
        L.append(f"{i}. {s}")
    L.append("")

    # ================= NICK-style RCA body =================
    # ---- Analysis Methodology ----
    L.append("## Analysis Methodology")
    meth: List[str] = []
    meth.append(f"Read HSD {hsd_id} in full (title, description, {n_comments} comment(s)) and "
                "reconstructed the investigation narrative from the comment thread.")
    if log_findings:
        src = "attached ticket resources" if attachments_fetched else "the provided log"
        meth.append(f"Scanned {log_findings.get('lines_scanned', 0)} log line(s) from {src} for "
                    "known failure signatures, MCA status words, and an ordered event timeline.")
    meth.append(f"Recalled the self-learning KB (best score {recall.get('best_score', 0)}, "
                f"{recall['confidence']} confidence) and queried HSDES for similar tickets.")
    if axon_links:
        meth.append(f"Reviewed the {len(axon_links)} Axon recording(s) linked in the ticket.")
    if transferred and transferred.get("summaries"):
        meth.append("Followed the transferred sub-team ticket(s) and pulled their latest "
                    "root-cause / fix status back into this report.")
    if target.get("mcp_sources"):
        meth.append("Queried the " + " and ".join(target["mcp_sources"])
                    + " agent(s) over MCP and folded their findings into the ticket context.")
    for m in meth:
        L.append(f"- {m}")
    L.append("")

    # ---- Root Cause ----
    L.append("## Root Cause")
    dom_label = ", ".join(d for d, _ in domains) or "unclassified"
    _mca_demoted, _demote_why = _mca_is_incidental(target, log_findings, cf)
    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        tag = (rc_validation["verdict"] if rc_validation else "reported")
        L.append(f"**Primary ({tag}, per {who}):** {_short(cf['root_cause'], 400)}")
        if suspected_area:
            L.append("")
            L.append(f"- **Mechanism / suspected area:** {suspected_area}")
    elif _mca_demoted:
        L.append(f"**Primary (reported subject / disposition — {_demote_why}):** "
                 f"{_demoted_primary_line(target, cf)}")
        if decoded and decoded.get("hypotheses"):
            L.append("")
            L.append("Decoded log telemetry (incidental — for reference only):")
            for h in decoded["hypotheses"][:3]:
                L.append(f"- ({h['severity']}) {h['text']}")
    elif decoded and decoded.get("hypotheses"):
        top = decoded["hypotheses"][0]
        L.append(f"**Primary (evidence-based, from decoded logs — {top['severity']}):** "
                 f"{top['text']}")
        if len(decoded["hypotheses"]) > 1:
            L.append("")
            L.append("Further decoded findings:")
            for h in decoded["hypotheses"][1:4]:
                L.append(f"- ({h['severity']}) {h['text']}")
    elif suspected_area:
        L.append(f"**Primary (derived from logs):** {suspected_area}")
    elif sigs:
        L.append(f"**Primary (hypothesis):** {sigs[0]['label']} on {plat} — {dom_label} path. "
                 "See supporting evidence in the appendix.")
    else:
        L.append("**Primary:** Not yet determined from available evidence — see the recommended "
                 "fix / next steps to collect stronger runtime data.")
    ev_lines: List[str] = []
    if decoded and decoded.get("mca"):
        mc = decoded["mca"]
        ev_lines.append(f"decoded MCA ({'uncorrected' if mc['uncorrected'] else 'corrected'}): "
                        f"{mc.get('headline') or 'see appendix'}")
    if decoded and decoded.get("bios"):
        ev_lines.append(f"decoded BIOS log: {decoded['bios'].get('headline') or 'see appendix'}")
    for d in (log_findings or {}).get("mca_decode", [])[:1]:
        ev_lines.append(f"MCA `{d['status']}` → {d.get('mcacod_text', '?')} "
                        f"(flags {', '.join(d['flags']) or 'none'})")
    if (log_findings or {}).get("last_checkpoint"):
        ev_lines.append(f"last good checkpoint `{log_findings['last_checkpoint']}`")
    for m in recall["matches"][:1]:
        r = _short(m.get("root_cause"), 120)
        if r and r != "—":
            ev_lines.append(f"KB precedent: {r}")
    if ev_lines:
        L.append("")
        L.append("**Supporting evidence:**")
        for e in ev_lines:
            L.append(f"- {e}")
    L.append("")
    L.append("**Alternative hypotheses:**")
    L.append(f"1. {dom_label} issue on {plat} consistent with the reported signature "
             f"({'KB match found' if recall['matches'] else 'no prior KB match'}).")
    L.append("2. Config / firmware / OS-build-specific behaviour — A/B the relevant revision "
             "(ucode / BIOS / IFWI / OS) between passing and failing runs.")
    L.append("")

    # ---- Root Cause Validation (provenance + trust verdict) ----
    if rc_validation:
        _V_ICON = {"VALIDATED": "✅", "PLAUSIBLE — needs confirmation": "🟡",
                   "UNVALIDATED HYPOTHESIS": "⚠️"}
        icon = _V_ICON.get(rc_validation["verdict"], "•")
        L.append("## Root Cause Validation")
        L.append(f"**Verdict:** {icon} **{rc_validation['verdict']}**")
        L.append(f"**Where it came from:** {rc_validation['provenance']}.")
        L.append("")
        L.append("| Check | Result |")
        L.append("|-------|--------|")
        for label, ok in rc_validation["checks"]:
            L.append(f"| {label} | {'✅ yes' if ok else '❌ no'} |")
        L.append("")
        L.append("**To validate this root cause:**")
        for i, t in enumerate(rc_validation["todo"], 1):
            L.append(f"{i}. {t}")
        L.append("")

    # ---- Secondary Observations ----
    sec: List[str] = []
    for s in sigs[1:4]:
        sec.append(f"Additional log signature: {s['label']} ({s['severity']}, x{s['count']}, "
                   f"{s['domain']}).")
    for label, _c in domains[1:3]:
        sec.append(f"Secondary domain in play: {label}.")
    if cf.get("tried"):
        sec.append("Already-tried paths (do not repeat): "
                   + "; ".join(_short(t, 60) for t in cf["tried"][:4]) + ".")
    if sec:
        L.append("## Secondary Observations")
        for i, s in enumerate(sec, 1):
            L.append(f"{i}. {s}")
        L.append("")

    # ---- Missing Evidence for Root Cause Determination ----
    _render_missing_evidence(L, evidence_audit)

    # ---- Recommended Fix ----
    L.append("## Recommended Fix")
    fix_steps: List[str] = []
    _has_transferred_fix = bool(transferred and any(
        s.get("fixed") for s in (transferred or {}).get("summaries", [])))
    if transferred and transferred.get("summaries"):
        for s in transferred["summaries"]:
            if s.get("fixed"):
                fix_steps.append(f"Adopt the sub-team fix from HSD {s['id']}: update the "
                                 f"**{s.get('domain') or 'responsible'}** ingredient to "
                                 f"`{s.get('ingredient')}` in the platform BKC.")
    if cf.get("workaround"):
        fix_steps.append(f"Apply / validate the recorded workaround: {_short(cf['workaround'], 180)}.")
    if cf.get("root_cause"):
        regs = (cf.get("breadcrumbs") or {}).get("register", [])[:3]
        fix_steps.append("Confirm the identified root cause on hardware"
                         + (f" (read {', '.join(regs)})" if regs else "") + ".")
    if sigs:
        fix_steps.append(f"Corroborate the top log signature ({sigs[0]['label']}) and decode the "
                         "flagged MCA bank / trace.")
    if not cf.get("root_cause") and not sigs:
        fix_steps.append("Collect serial/BIOS/OS logs + revisions (ucode/BIOS/IFWI/OS) and re-run "
                         "to capture stronger evidence.")
    if axon_links:
        fix_steps.append("Review the Axon recording(s) linked in the ticket for the failing sequence.")
    fix_steps.append("File / update the sighting with the findings.")
    for i, s in enumerate(dict.fromkeys([x for x in fix_steps if x and x.strip()]), 1):
        L.append(f"{i}. {s}")
    L.append("")
    if cf.get("root_cause") or _has_transferred_fix:
        L.append("**Expected result:** applying the fix above resolves the reported failure; "
                 "re-validate the failing scenario to confirm closure.")
    else:
        L.append("**Expected result:** the collected evidence isolates the failing domain and "
                 "confirms (or refutes) the leading hypothesis, unblocking a targeted fix.")
    L.append("")

    # Transferred-ticket sync (sub-team findings pulled back to this sighting).
    _render_transferred(L, transferred)

    L.append("---")
    L.append("")
    L.append("<details><summary>Appendix — full evidence (narrative, logs, KB, similar HSDs, knowledge)</summary>")
    L.append("")
    L.append("> **OFFLINE mode** — deterministic report from KB + ticket data. "
             "Configure `LLM_BASE_URL` / `LLM_API_KEY` for full LLM reasoning.")
    L.append("")

    L.append("## A. Target HSD summary")
    if target and not target.get("error"):
        L.append(f"- **ID:** {hsd_id}")
        L.append(f"- **Title:** {tval('title')}")
        L.append(f"- **Platform / Family:** {plat} / {tval('family')}")
        L.append(f"- **Component:** {tval('component')}")
        L.append(f"- **Status:** {tval('status')}  |  **Priority:** {tval('priority')}")
        L.append(f"- **Owner:** {tval('owner')}")
        desc = target.get("description") or ""
        if desc:
            L.append(f"- **Description:** {desc if len(desc) <= 600 else desc[:600] + '…'}")
        if target.get("comments") is not None:
            L.append(f"- **Comments read:** {len(target.get('comments') or [])}")
        if attachments:
            fetched_note = (f" ({attachments_fetched} fetched & scanned)"
                            if attachments_fetched else " (not fetched — pass fetch_attachments)")
            L.append(f"- **Attachments on ticket:** {len(attachments)}{fetched_note}")
    else:
        reason = (target.get("error") if target
                  else "no reader token/credential supplied for this request")
        L.append(f"- **ID:** {hsd_id}")
        L.append(f"- Ticket data unavailable ({reason}).")
    L.append(f"- **Detected domain(s):** {', '.join(d for d, _ in domains) or 'general'}")
    L.append(f"- **Reported signature (input):** {symptoms}")
    L.append("")

    # Investigation narrative reconstructed from the comment thread — this is the
    # crystal-clear "what happened, in order" that a human analyst reads first.
    if cf and cf.get("narrative"):
        _KIND_ICON = {
            "ROOT CAUSE": "🎯", "WORKAROUND / FIX": "🛠️", "OBSERVED": "🔎",
            "TRIED": "🔧", "NEXT STEP": "➡️", "NOTE": "•",
        }
        from .comment_analyzer import _LABELS
        L.append(f"## A1. Investigation narrative (from {cf.get('count', 0)} comments)")
        L.append("")
        L.append("| # | Who | Kind | What they reported |")
        L.append("|---|-----|------|--------------------|")
        for ev in cf["narrative"]:
            label = _LABELS.get(ev["kind"], "NOTE")
            icon = _KIND_ICON.get(label, "•")
            who = _short(ev["author"], 18)
            what = _short(ev["text"], 150).replace("|", "\\|")
            L.append(f"| {ev['seq']} | {who} | {icon} {label} | {what} |")
        L.append("")

        if cf.get("root_cause"):
            who = cf.get("root_cause_author") or "ticket"
            L.append(f"- **🎯 Converged root cause ({who}):** {_short(cf['root_cause'], 320)}")
        if cf.get("workaround"):
            L.append(f"- **🛠️ Workaround / fix:** {_short(cf['workaround'], 240)}")
        if cf.get("tried"):
            L.append(f"- **Already tried (do not repeat):**")
            for t in cf["tried"][:6]:
                L.append(f"  - {_short(t, 150)}")
        if cf.get("next_steps"):
            L.append(f"- **Recorded next steps:**")
            for n in cf["next_steps"][:5]:
                L.append(f"  - {_short(n, 150)}")
        # Technical breadcrumbs pulled from the thread
        crumbs = cf.get("breadcrumbs") or {}
        if crumbs:
            _CRUMB_LABEL = {"register": "Registers", "code_site": "Code sites",
                            "socket_port": "Socket/Port", "bios_build": "BIOS builds",
                            "upi_signal": "UPI/UPLR"}
            L.append(f"- **Technical breadcrumbs:**")
            for k, items in crumbs.items():
                L.append(f"  - *{_CRUMB_LABEL.get(k, k)}:* "
                         f"{', '.join('`' + _short(i, 40) + '`' for i in items[:8])}")
        L.append(f"- **Investigation status:** {cf.get('status_hint', 'unknown')}")
        L.append("")

    # Attached-log analysis (only when logs were provided).
    if log_findings:
        L.append("## A2. Attached log analysis")
        if attachments:
            L.append(f"- **Attachments on ticket:** {len(attachments)} — "
                     f"**{attachments_fetched} downloaded & scanned**")
            if attach_files:
                L.append(f"- **Files extracted:** {', '.join(_short(f, 60) for f in attach_files[:8])}")
        L.append(f"- **Lines scanned:** {log_findings['lines_scanned']}")
        if log_findings.get("last_checkpoint"):
            L.append(f"- **Last good checkpoint:** `{log_findings['last_checkpoint']}`")
        # Suspected area + smoking-gun evidence pulled straight from the attachment.
        if log_findings.get("suspected_area"):
            L.append(f"- **🎯 Suspected area (derived from attachment):** "
                     f"{log_findings['suspected_area']}")
        evid = log_findings.get("evidence") or []
        if evid:
            L.append("")
            L.append("**Root-cause evidence extracted from the attachment "
                     "(smoking-gun lines):**")
            L.append("")
            L.append("| Category | Hits | Representative log line |")
            L.append("|----------|------|-------------------------|")
            for e in evid:
                for i, ln in enumerate(e["lines"]):
                    cat = e["category"] if i == 0 else ""
                    cnt = str(e["count"]) if i == 0 else ""
                    line = _short(ln, 120).replace("|", "\\|")
                    L.append(f"| {cat} | {cnt} | `{line}` |")
            L.append("")
        # Sequence of events (timeline)
        timeline = log_findings.get("timeline") or []
        if timeline:
            L.append("")
            L.append("**Sequence of events (from logs, in order):**")
            L.append("")
            L.append("| # | Timestamp | Event | Detail |")
            L.append("|---|-----------|-------|--------|")
            for i, ev in enumerate(timeline, 1):
                mark = " ⟵ **failure point**" if ev.get("failure_point") else ""
                cnt = f" (x{ev['count']})" if ev.get("count", 1) > 1 else ""
                detail = _short(ev["text"], 90).replace("|", "\\|")
                L.append(f"| {i} | {ev['ts'] or '—'} | {ev['label']}{cnt}{mark} | `{detail}` |")
        if log_findings["signatures"]:
            L.append("")
            L.append("**Failure signatures detected:**")
            L.append("")
            L.append("| Signature | Severity | Count | Domain | Example |")
            L.append("|-----------|----------|-------|--------|---------|")
            for s in log_findings["signatures"][:8]:
                ex = _short((s.get("examples") or [""])[0], 80).replace("|", "\\|")
                L.append(f"| {s['label']} | {s['severity']} | {s['count']} | "
                         f"{s['domain']} | `{ex}` |")
        else:
            L.append("- No known failure signatures matched in the log.")
        # MCA decode (MCi_STATUS -> flags, MCACOD, MSCOD)
        for d in (log_findings.get("mca_decode") or []):
            L.append(f"- **MCA decode:** status `{d['status']}` "
                     f"flags [{', '.join(d['flags']) or 'none'}] "
                     f"MCACOD `{d['mcacod']}` = {d.get('mcacod_text','?')}; "
                     f"MSCOD `{d['mscod']}` (model-specific) — {d['severity']}")
        L.append("")
    elif attachments:
        # Logs exist on the ticket but weren't fetched — make that explicit.
        L.append("## A2. Attached log analysis")
        L.append(f"- **{len(attachments)} attachment(s) on the ticket were NOT downloaded.** "
                 "Enable **Auto-fetch attachments** (UI) or `--fetch-attachments` (CLI) to "
                 "extract and analyze them.")
        L.append("")

    # Decoded log evidence — deterministic Intel decoder DBs (EWL/RC-Fatal/MCHECK/MCA/POST).
    if decoded:
        L.append("## A3. Decoded log evidence (Intel decoder databases)")
        L.append(f"*Log types detected: {', '.join(decoded.get('kinds') or ['generic'])}. "
                 "Decoded with the bundled EWL / RC-Fatal / MCHECK / MCA / POST databases.*")
        L.append("")
        if decoded.get("mca"):
            L.append("### MCA (Machine Check) decode")
            L.append(decoded["mca"]["summary_md"])
            L.append("")
        if decoded.get("bios"):
            L.append("### BIOS / SOL serial-log decode")
            L.append(decoded["bios"]["summary_md"])
            L.append("")
        if decoded.get("post"):
            L.append("### BIOS POST / checkpoint codes")
            L.append("| Code | Macro | Meaning |")
            L.append("|------|-------|---------|")
            for c in decoded["post"]["codes"]:
                L.append(f"| `{c.get('code','')}` | {c.get('macro','')} | "
                         f"{_short(c.get('description',''), 80)} |")
            L.append("")

    L.append("## B. KB recall result")
    L.append(f"- **Confidence:** {recall['confidence']} (best score {recall['best_score']})")
    if recall["matches"]:
        for m in recall["matches"]:
            L.append(f"  - `{m.get('sig_key','')}` — root cause: "
                     f"{_short(m.get('root_cause')) or '_none recorded_'} "
                     f"(score {m.get('match_score')})")
    else:
        L.append("- No matching learned cases yet — this will seed the KB.")
    L.append("")

    L.append("## C. Similar HSDs")
    L.append("| ID | Source | Similarity reason | Root cause | Status |")
    L.append("|----|--------|-------------------|------------|--------|")
    for m in recall["matches"]:
        L.append(f"| {m.get('source_hsd') or '—'} | KB | terms: "
                 f"{', '.join(m.get('matched_terms', []))} | {_short(m.get('root_cause')) or '—'} "
                 f"| {m.get('confidence_tag','—')} |")
    for s in similar:
        L.append(f"| {s.get('id','')} | HSDES | keyword match | — | {s.get('status','')} |")
    if not recall["matches"] and not similar:
        L.append("| — | — | no matches | — | — |")
    L.append("")

    # How the most similar prior issues were resolved (root cause / fix).
    L.append("### How similar issues were resolved")
    any_res = False
    for m in recall["matches"]:
        res = _short(m.get("resolution") or m.get("root_cause"), 180)
        if res and res != "—":
            src = m.get("source_hsd") or m.get("sig_key", "")
            L.append(f"- **{src}:** {res}")
            any_res = True
    if not any_res:
        L.append("- _No recorded root cause / resolution among the similar cases yet._")
    L.append("")

    L.append("## D. Ranked root-cause hypotheses")
    dom_label = ", ".join(d for d, _ in domains) or "unclassified"
    rank = 1
    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        tag = "confirmed-in-ticket" if cf.get("workaround") else "leading, from comments"
        L.append(f"{rank}. *({tag})* {_short(cf['root_cause'], 320)} "
                 f"— stated by **{who}** in the comment thread.")
        rank += 1
    L.append(f"{rank}. *(hypothesis)* {dom_label} issue on {plat} consistent with the reported "
             f"signature. Evidence: ticket text; {'KB match' if recall['matches'] else 'no prior KB match'}.")
    rank += 1
    L.append(f"{rank}. *(hypothesis)* Config / firmware / OS-build specific behavior — A/B the "
             "relevant revision (ucode/BIOS/IFWI/OS) before deeper isolation.")
    L.append("")

    L.append("## E. Detailed next debug steps")
    step = 1
    # If the ticket comments already recorded a converged root cause + next step,
    # continue from there instead of restarting the investigation.
    if cf.get("root_cause"):
        L.append(f"{step}. **Confirm the comment-identified root cause on hardware.** "
                 f"{_short(cf['root_cause'], 200)}")
        crumbs = cf.get("breadcrumbs") or {}
        if crumbs.get("register"):
            L.append(f"   - Read the cited register(s): "
                     f"{', '.join('`' + r + '`' for r in crumbs['register'][:4])}.")
        if crumbs.get("socket_port"):
            L.append(f"   - Focus on: {', '.join(crumbs['socket_port'][:4])}.")
        if crumbs.get("code_site"):
            L.append(f"   - Inspect code path near: "
                     f"{', '.join('`' + c + '`' for c in crumbs['code_site'][:3])}.")
        step += 1
        if cf.get("next_steps"):
            L.append(f"{step}. **Continue the recorded plan:** "
                     f"{_short(cf['next_steps'][-1], 180)}")
            step += 1
        if cf.get("workaround"):
            L.append(f"{step}. **Validate the workaround** and track the real fix: "
                     f"{_short(cf['workaround'], 180)}")
            step += 1
    # Log-driven step when attached logs revealed something concrete.
    if log_findings and log_findings.get("signatures"):
        top = log_findings["signatures"][0]
        L.append(f"{step}. **From attached logs — {top['label']}** ({top['severity']}, "
                 f"x{top['count']}). Corroborate against the root cause above.")
        mca = (log_findings.get("mca_decode") or [])
        if mca:
            d = mca[0]
            L.append(f"   - Decode the flagged MCA bank: read `MCi_STATUS`/`MCi_ADDR`; "
                     f"status `{d['status']}` = {d.get('mcacod_text','?')} "
                     f"(flags {', '.join(d['flags']) or 'none'}).")
            L.append("   - `sv.socket<N>.uncore.mca_bank<B>.status.read()` "
                     "# confirm bank B from the log line")
        if log_findings.get("last_checkpoint"):
            L.append(f"   - Last checkpoint before failure: `{log_findings['last_checkpoint']}` "
                     "— inspect the code path right after it.")
        step += 1
    # Domain checks only when we DON'T already have a converged root cause.
    if not cf.get("root_cause"):
        if domains:
            for label, cmds in domains:
                L.append(f"{step}. **{label}** — check the domain-specific state first.")
                for c in cmds:
                    L.append(f"   - {c}")
                step += 1
        else:
            L.append(f"{step}. **Identify the failing domain** from the ticket signature, then "
                     "read that subsystem's status/log.")
            step += 1
        L.append(f"{step}. **Isolate by revision** — A/B ucode / BIOS / IFWI / BMC / OS build "
                 "between passing and failing runs.")
        step += 1
    if cf.get("tried"):
        L.append(f"{step}. **Skip already-tried paths** (recorded in comments): "
                 + "; ".join(_short(t, 60) for t in cf["tried"][:4]) + ".")
    L.append("")

    L.append("## F. Data to request/collect")
    L.append("- Full logs (serial/BIOS/OS/RPT), failing config/test, cluster/system id")
    L.append("- Revisions: silicon stepping, ucode, BIOS/IFWI, BMC/CPLD, OS build")
    L.append("- Domain specifics (MCA bank+RIP, DIMM/channel, PCIe lane, Sx target, etc.)")
    L.append("")

    L.append("## G. Learning summary")
    if cf.get("root_cause"):
        conf = "High" if cf.get("workaround") else "Medium"
    else:
        conf = "Medium" if target.get("full_text") else "Low"
    tag = "root-cause captured from comments" if cf.get("root_cause") else "signature captured"
    L.append(f"- KB entry created/updated for this signature, tagged **{conf}** ({tag}).")
    L.append("")

    L.append("## H. Known-issue verdict")
    if cf.get("root_cause") and cf.get("workaround"):
        L.append("- **Root-caused in ticket** — root cause + workaround recorded in comments "
                 "(section A1). Verify the fix lands before closing.")
    elif cf.get("root_cause"):
        L.append("- **Root cause identified** in ticket comments (section A1) — not yet "
                 "verified/fixed. Confirm on hardware.")
    elif recall["confidence"] in ("High", "Medium"):
        L.append("- **Likely known** — see KB matches in section C. Verify before closing.")
    else:
        L.append("- **Likely new sighting** — no confident KB match found.")
    L.append("")

    # I. Reference knowledge — auto-linked debug wiki pages + BIOS code areas.
    kb_blob = " ".join(filter(None, [
        symptoms,
        (log_findings or {}).get("suspected_area", "") if log_findings else "",
        " ".join(s["label"] for s in (log_findings or {}).get("signatures", [])),
        cf.get("root_cause", ""),
        " ".join(" ".join(v) for v in (cf.get("breadcrumbs") or {}).values()),
        target.get("full_text", "")[:2000],
    ]))
    knowledge = match_knowledge(kb_blob, domains=[d for d, _ in domains])
    if knowledge:
        L.append("## I. Reference knowledge & auto-suggested next steps")
        L.append("*(from the built-in Debug Knowledge Pack — real Intel debug wikis + "
                 "BIOS/firmware code areas, matched to this failure)*")
        L.append("")
        for k in knowledge:
            L.append(f"### {k['title']}")
            if k.get("summary"):
                L.append(f"{k['summary']}")
            if k.get("wiki_links"):
                L.append("- **Debug wiki pages:**")
                for w in k["wiki_links"]:
                    L.append(f"  - {w}")
            if k.get("code_paths"):
                L.append("- **BIOS / firmware code areas:**")
                for c in k["code_paths"]:
                    L.append(f"  - {c}")
            if k.get("debug_steps"):
                L.append("- **Suggested next steps:**")
                for i, s in enumerate(k["debug_steps"], 1):
                    L.append(f"  {i}. {s}")
            L.append("")

        # Optional: live BIOS-source snippets for the exact code sites in the logs.
        code_sites = ((cf.get("breadcrumbs") or {}).get("code_site") or [])
        bios = lookup_bios_code(code_sites) if code_sites else []
        if bios:
            L.append("### BIOS source at the exact code sites (from local checkout)")
            for b in bios:
                if b.get("found"):
                    L.append(f"- **{b['site']}** ({b.get('path','')}):")
                    L.append("```c")
                    L.append(b["snippet"])
                    L.append("```")
                else:
                    L.append(f"- **{b['site']}** — file not found in BIOS_REPO_PATH.")
            L.append("")
        elif code_sites and not config.BIOS_REPO_PATH:
            L.append(f"> ℹ️ Code sites seen in logs ({', '.join(code_sites[:4])}) — set "
                     "`BIOS_REPO_PATH` to a local BIOS checkout to auto-pull the source here.")
            L.append("")

    # J. Axon recordings — ONLY real recordings actually linked in the ticket.
    if axon_links:
        _arecs = {r["uuid"]: r for r in (target.get("axon_records") or [])}
        L.append("## J. Axon recordings linked in the ticket")
        for u in axon_links:
            rec = _arecs.get(u)
            L.append(f"- {canonical_axon_url(u)}")
            if rec and rec.get("available"):
                for k in ("platform", "stepping", "plugin", "config"):
                    if rec.get(k):
                        L.append(f"  - **{k.capitalize()}:** {_short(rec[k], 100)}")
                if rec.get("content_files"):
                    L.append(f"  - **Content files (decoded above):** "
                             f"{', '.join(rec['content_files'][:8])}")
            elif rec:
                L.append(f"  - _not fetched: {rec.get('note','')}_")
        L.append("")

    L.append("</details>")

    return "\n".join(L), _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled,
                                         comment_findings)
