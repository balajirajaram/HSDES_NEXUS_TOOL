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


def _extract_findings(target: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Deterministically pull root-cause / resolution text from ticket fields and
    comment keywords — no LLM required."""
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

    root_cause = " ".join(rc_lines) or gf("fix_description", "executive_summary")
    resolution = " ".join(fix_lines) or gf("closed_reason", "status_reason")
    status = (target.get("status") or "").lower()
    confirmed = status in ("closed", "complete", "verified") and bool(root_cause or resolution)
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

    # Logs: any pasted log + (optionally) the logs already attached to the ticket.
    combined_log = log_text or ""
    fetched = 0
    if fetch_attachments and attachments:
        atext = await client.fetch_attachment_text(target)
        if atext:
            combined_log = (combined_log + "\n" + atext).strip()
            fetched = len(attachments)
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
            log_findings
        )
    else:
        report_md, kb_entry = _offline_report(
            hsd_id, symptoms, platform, recall, target, similar, client.enabled,
            log_findings, attachments, fetched
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
        "log_findings": log_findings,
        "kb_action": kb_action,
        "report_markdown": report_md,
    }


async def _llm_report(hsd_id, symptoms, platform, recall, target, similar,
                      hsdes_enabled, log_findings=None) -> Tuple[str, Dict[str, Any]]:
    context = {
        "input": {"hsd_id": hsd_id, "symptoms": symptoms, "platform": platform},
        "kb_recall": recall,
        "target_hsd": target,
        "similar_hsds": similar,
        "attached_log_findings": log_findings,
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "CONTEXT:\n" + json.dumps(context, indent=2)},
    ]
    raw = await llm.chat(messages)
    parsed = _extract_json(raw)
    if parsed and "report_markdown" in parsed:
        return parsed["report_markdown"], parsed.get("kb_entry") or _fallback_entry(
            hsd_id, symptoms, platform, target, hsdes_enabled
        )
    return raw, _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled)


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


def _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled) -> Dict[str, Any]:
    from time import gmtime, strftime
    target = target or {}
    ticket_text = target.get("full_text") or target.get("description") or ""
    error_string = (symptoms + ("\n" + ticket_text if ticket_text else "")).strip()
    domains = [d for d, _ in _detect_domains(error_string)]
    findings = _extract_findings(target)
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
                    attachments_fetched=0) -> Tuple[str, Dict[str, Any]]:
    target = target or {}
    attachments = attachments or []
    plat = platform or "unknown platform"
    blob = f"{symptoms} " + (target.get("full_text") or target.get("description") or "")
    if log_findings:
        blob += " " + " ".join(s["label"] for s in log_findings["signatures"])
    domains = _detect_domains(blob)[:3]  # focus on the dominant domain(s)

    def tval(k, default="_not available_"):
        return target[k] if target.get(k) else default

    L: List[str] = []
    L.append(f"# Auto HSD Analyser report — {hsd_id}")
    L.append("")
    L.append("> **OFFLINE mode** — no LLM configured. Deterministic report from KB + "
             "ticket data. Configure `LLM_BASE_URL` / `LLM_API_KEY` for full reasoning.")
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

    # Attached-log analysis (only when logs were provided).
    if log_findings:
        L.append("## A2. Attached log analysis")
        L.append(f"- **Lines scanned:** {log_findings['lines_scanned']}")
        if log_findings.get("last_checkpoint"):
            L.append(f"- **Last checkpoint before failure:** `{log_findings['last_checkpoint']}`")
        if log_findings["signatures"]:
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
    L.append(f"1. *(hypothesis)* {dom_label} issue on {plat} consistent with the reported "
             f"signature. Evidence: ticket text; {'KB match' if recall['matches'] else 'no prior KB match'}.")
    L.append("2. *(hypothesis)* Config / firmware / OS-build specific behavior — A/B the "
             "relevant revision (ucode/BIOS/IFWI/OS) before deeper isolation.")
    L.append("")

    L.append("## E. Detailed next debug steps")
    step = 1
    # Log-driven step first when attached logs revealed something concrete.
    if log_findings and log_findings.get("signatures"):
        top = log_findings["signatures"][0]
        L.append(f"{step}. **From attached logs — {top['label']}** ({top['severity']}, "
                 f"x{top['count']}). Start here; it's the strongest evidence.")
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
    L.append(f"{step + 1}. **Collect logs** — grep serial/BIOS/OS logs for the error string; "
             "capture full config and revisions.")
    L.append("")

    L.append("## F. Data to request/collect")
    L.append("- Full logs (serial/BIOS/OS/RPT), failing config/test, cluster/system id")
    L.append("- Revisions: silicon stepping, ucode, BIOS/IFWI, BMC/CPLD, OS build")
    L.append("- Domain specifics (MCA bank+RIP, DIMM/channel, PCIe lane, Sx target, etc.)")
    L.append("")

    L.append("## G. Learning summary")
    conf = "Medium" if target.get("full_text") else "Low"
    L.append(f"- KB entry created/updated for this signature, tagged **{conf} / hypothesis** "
             "(full reasoning requires the LLM; offline captures the signature).")
    L.append("")

    L.append("## H. Known-issue verdict")
    if recall["confidence"] in ("High", "Medium"):
        L.append("- **Likely known** — see KB matches in section C. Verify before closing.")
    else:
        L.append("- **Likely new sighting** — no confident KB match found.")

    return "\n".join(L), _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled)
