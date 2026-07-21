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
matched cases from a learned Knowledge Base (KB), and similar HSDs. Produce a Markdown
report with EXACTLY these sections:

A. Target HSD summary (title, platform/family, component, status, owner, priority,
   and the failure signature distilled from description + comments)
B. KB recall result (confidence + matched learned cases)
C. Similar HSDs table (ID | Source: KB/HSDES | Similarity reason | Root cause | Status)
D. Ranked root-cause hypotheses, each tied to specific supporting evidence from the ticket
E. Detailed next debug steps - numbered; for each give what to check & why, the EXACT
   command(s) appropriate to the DOMAIN (e.g. PythonSV `sv.socket0.<unit>.<reg>.read()` and
   MCA decode for silicon; `powercfg /a`, Kernel-Power event queries, `pmc.Sx_check()` for
   power/Sx; `lspci`/LTSSM for PCIe/CXL; BIOS/serial log greps for boot/hang), and a
   decision branch (if X -> conclusion, else -> next step)
F. Data to request/collect (logs, RPT/rpt.gz, ucode/BIOS/IFWI/BMC revs, OS build, config)
G. Learning summary (what KB entry was created/updated + confidence tag)
H. Known-issue verdict (known + cite HSD / workaround, or new sighting)

Rules: Only cite HSD IDs present in the provided data. If unsure of an exact register/command
path, say so and give the closest known one plus how to confirm it. Clearly separate
"confirmed from data" vs "hypothesis".

Return a SINGLE JSON object (no prose outside it) with keys:
  "report_markdown": string  (the full A-H report)
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
                  fetch_attachments: bool = False) -> Dict[str, Any]:
    client = HSDESClient(hsdes_token, username, password)
    # Text we reason over = typed symptoms (target text is added after fetch).
    platform = _detect_platform(f"{symptoms} {hsd_id}")

    # Step 0 - RECALL (domain-agnostic: no family filter; exclude self-match)
    recall = kb.search(symptoms, exclude_id=hsd_id)

    # Step 2 - INVESTIGATE
    target = await client.get_article(hsd_id)
    attachments = client.attachment_ids(target) if target else []

    # Read the comment thread like a human analyst — this is where debug converges.
    comment_findings = analyze_comments(
        (target or {}).get("comments_structured", [])) if target else None

    # Logs: any pasted log + (optionally) the logs already attached to the ticket.
    combined_log = log_text or ""
    fetched = 0
    attach_files: List[str] = []
    if fetch_attachments and attachments:
        atext = await client.fetch_attachment_text(target)
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
    log_findings = analyze_log(combined_log) if combined_log.strip() else None

    blob = f"{symptoms} " + (target.get("full_text") or target.get("description") or ""
                             if target else "")
    if log_findings:
        blob += " " + " ".join(s["label"] for s in log_findings["signatures"])
    if not platform:
        platform = _detect_platform(blob)
    similar: List[Dict[str, Any]] = []
    if recall["confidence"] != "High":
        similar = await client.search_similar(symptoms)

    # Step 4 - REPORT
    if llm.enabled:
        report_md, kb_entry = await _llm_report(
            hsd_id, symptoms, platform, recall, target, similar, client.enabled,
            log_findings, comment_findings
        )
    else:
        report_md, kb_entry = _offline_report(
            hsd_id, symptoms, platform, recall, target, similar, client.enabled,
            log_findings, attachments, fetched, attach_files, comment_findings
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
        "kb_action": kb_action,
        "report_markdown": report_md,
    }


async def _llm_report(hsd_id, symptoms, platform, recall, target, similar,
                      hsdes_enabled, log_findings=None,
                      comment_findings=None) -> Tuple[str, Dict[str, Any]]:
    context = {
        "input": {"hsd_id": hsd_id, "symptoms": symptoms, "platform": platform},
        "kb_recall": recall,
        "target_hsd": target,
        "similar_hsds": similar,
        "attached_log_findings": log_findings,
        "comment_investigation": comment_findings,
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


def _offline_report(hsd_id, symptoms, platform, recall, target, similar,
                    hsdes_enabled, log_findings=None, attachments=None,
                    attachments_fetched=0, attach_files=None,
                    comment_findings=None) -> Tuple[str, Dict[str, Any]]:
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
    L.append(f"# Auto HSD Analyser report — {hsd_id}")
    L.append("")
    L.append("> **OFFLINE mode** — no LLM configured. Deterministic report from KB + "
             "ticket data. Configure `LLM_BASE_URL` / `LLM_API_KEY` for full reasoning.")
    L.append("")

    # Model A: compact executive card (for fast triage decisions).
    L.append("## Model A. Executive triage card")
    L.append(f"- **Verdict:** {_known_verdict()}")
    L.append(f"- **Overall confidence:** {_exec_confidence()} / 100")
    L.append(f"- **Primary domain cluster:** {(domains[0][0] if domains else 'General / unclassified')}")
    L.append(f"- **Failure point (best signal):** {failure_point}")
    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        L.append(f"- **Root cause ({who}):** {_short(cf['root_cause'], 240)}")
    if suspected_area:
        L.append(f"- **Suspected area (from attachment):** {suspected_area}")
    if cf.get("workaround"):
        L.append(f"- **Workaround / fix:** {_short(cf['workaround'], 200)}")
    # Key failure signatures read from the attached logs (top few by severity).
    sigs = (log_findings or {}).get("signatures", []) if log_findings else []
    if sigs:
        key = " · ".join(f"{s['label']} ({s['severity']}, x{s['count']})"
                         for s in sigs[:4])
        L.append(f"- **Key failure signatures (from attached logs):** {key}")
    elif top_sig:
        L.append(f"- **Top failure signature:** {top_sig['label']} ({top_sig['severity']}, x{top_sig['count']})")
    L.append(f"- **Immediate next action:** {next_action}")
    if cf.get("status_hint"):
        L.append(f"- **Investigation status:** {cf['status_hint']}")
    L.append("")

    L.append("### Model A evidence ledger")
    L.append(f"- **Target ticket narrative available:** {'yes' if target and not target.get('error') else 'no'}")
    L.append(f"- **Comments analysed:** {cf.get('count', 0)}")
    L.append(f"- **KB matches:** {len(recall.get('matches', []))} ({recall.get('confidence', 'None')})")
    L.append(f"- **Similar HSDs from source:** {len(similar)}")
    L.append(f"- **Log signatures detected:** {len((log_findings or {}).get('signatures', []))}")
    L.append("")

    L.append("### Domain cluster snapshot")
    L.append("| Cluster | Relative confidence | Why selected |")
    L.append("|---------|---------------------|--------------|")
    if domains:
        for i, (label, _) in enumerate(domains):
            rel = ("High" if i == 0 else ("Medium" if i == 1 else "Low"))
            why = "keyword + signature dominance" if i == 0 else "secondary indicators"
            L.append(f"| {label} | {rel} | {why} |")
    else:
        L.append("| General / unclassified | Low | no strong domain tokens in current data |")
    L.append("")

    # Model B: detailed investigation report with sections A-H.
    L.append("## Model B. Full investigation")
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

    return "\n".join(L), _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled,
                                         comment_findings)
