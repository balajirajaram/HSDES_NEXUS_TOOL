#!/usr/bin/env python3
"""
parse_and_triage.py
═══════════════════
HSD Triage & Log Recommendation Engine.

Modes:
  --mode prepare    : Parse input CSV → output/run_<timestamp>/triage_prompts.jsonl
  --mode finalize   : Process GHCP responses → output/run_<timestamp>/triage_results.csv
  --mode report     : Render CSV → output/run_<timestamp>/triage_report.html

Each run is isolated in a timestamped subfolder under output/.
The finalize and report modes auto-detect the latest run folder unless --output-dir is specified.

Usage:
  python parse_and_triage.py --input <csv_path> --mode prepare
  python parse_and_triage.py --mode finalize --responses <responses.jsonl> [--output-dir output/run_...]
  python parse_and_triage.py --mode report --input <results.csv> [--output-dir output/run_...]
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Handle large HTML description fields in HSD CSVs
csv.field_size_limit(10 * 1024 * 1024)  # 10 MB

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_BASE = SCRIPT_DIR / "output"
TEMPLATE_PATH = SCRIPT_DIR / "report_template.html"
TAXONOMY_PATH = SCRIPT_DIR / "log_taxonomy.md"


_CLEAN_MAP = str.maketrans({
    "\u00a0": " ",   # non-breaking space → regular space (shows as "Â " in Latin-1 viewers)
    "\u2003": " ",   # em space → regular space
    "\u2002": " ",   # en space → regular space
    "\u200b": "",    # zero-width space → remove
    "\u200e": "",    # left-to-right mark → remove
    "\u200f": "",    # right-to-left mark → remove
    "\ufeff": "",    # BOM / zero-width no-break space embedded mid-text → remove
    "\u00ad": "",    # soft hyphen → remove
})

def clean_text(value: object) -> str:
    """Normalize Unicode oddities that cause mojibake in Latin-1 CSV viewers (e.g. Excel).

    Replaces invisible/variant whitespace with plain space or removes it,
    then collapses runs of multiple spaces into one.
    Does NOT alter em-dashes, curly quotes, arrows, or other visible Unicode.
    """
    if not isinstance(value, str):
        return value  # type: ignore[return-value]
    s = value.translate(_CLEAN_MAP)
    # Collapse multiple spaces (including those we just introduced) into one
    s = re.sub(r"  +", " ", s)
    return s.strip()


def _make_timestamped_output_dir() -> Path:
    """Create and return a new timestamped run folder under output/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_BASE / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _resolve_output_dir(explicit_path: str | None) -> Path:
    """Resolve output dir: use explicit path, or find latest run folder."""
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            logger.error("Specified output dir not found: %s", p)
            sys.exit(1)
        return p
    # Auto-detect latest run folder
    if not OUTPUT_BASE.exists():
        logger.error("No output/ directory found. Run --mode prepare first.")
        sys.exit(1)
    run_dirs = sorted(OUTPUT_BASE.glob("run_*"), key=lambda d: d.name, reverse=True)
    if not run_dirs:
        logger.error("No run_* folders found in %s. Run --mode prepare first.", OUTPUT_BASE)
        sys.exit(1)
    latest = run_dirs[0]
    logger.info("Auto-detected latest run folder: %s", latest.name)
    return latest

# Regex patterns for extracting structured data from HSD descriptions
NGA_UUID_PATTERN = re.compile(
    r"nga\.laas\.intel\.com/#/[^/]+/(?:planning|failureManagement)/(?:testResult|failures)/([0-9a-f\-]{36})",
    re.IGNORECASE,
)
ROCKET_CMD_PATTERN = re.compile(
    r"(rocket\s+[^\n<]{10,300})", re.IGNORECASE
)
SV_PATH_PATTERN = re.compile(
    r"(sv\.socket\d+\.[a-zA-Z0-9_.]+(?:\.[a-zA-Z0-9_]+)*)", re.IGNORECASE
)
REGISTER_VALUE_PATTERN = re.compile(
    r"(0x[0-9a-fA-F]{4,16})\s*:\s*(\w+)", re.IGNORECASE
)

# Accelerator detection from title/component
ACCEL_PATTERNS = {
    "DSA": re.compile(r"\bDSA\b|data.?streaming|dsa_|local-dsa", re.IGNORECASE),
    "IAA": re.compile(r"\bIAA?\b|IAX|analytics.?accel|iaa_|local-iax", re.IGNORECASE),
    "QAT": re.compile(r"\bQAT\b|CPM|quick.?assist|cpm_|cpmqat", re.IGNORECASE),
}

# Failure mode detection
FAILURE_MODES = {
    "hang": re.compile(r"\bhang\b|deadlock|stuck|no.?response|not.?responding", re.IGNORECASE),
    "error": re.compile(r"\berror\b|err_code|SWERROR|ppaercs|fault", re.IGNORECASE),
    "timeout": re.compile(r"\btimeout\b|timed.?out", re.IGNORECASE),
    "mismatch": re.compile(r"\bmismatch\b|FAILVECT|expected.*observed|incorrect.?default", re.IGNORECASE),
    "crash": re.compile(r"\bcrash\b|machine.?check|MCE|panic", re.IGNORECASE),
    "data_corruption": re.compile(r"\bcorrupt\b|data.?integrity|bit.?flip", re.IGNORECASE),
    "initialization_failure": re.compile(r"\binit\b.*fail|not.?supporting|module.*zero|svDeviceInit", re.IGNORECASE),
}

# Log category detection in descriptions
LOG_DETECTORS = {
    "register_dump": re.compile(r"sv\.socket.*\.show\(\)|\.show\b", re.IGNORECASE),
    "perfmon_counters": re.compile(r"cntr(?:cfg|data)|perfmon|showsearch.*cntr", re.IGNORECASE),
    "swerror_dump": re.compile(r"swerror\d|gensts|intcause|cmdstatus", re.IGNORECASE),
    "pcie_aer": re.compile(r"ppaercs|ppaeruc|aer.*error|Advisory.?Non.?Fatal", re.IGNORECASE),
    "dmesg_kernel": re.compile(r"dmesg|\[\s*\d+\.\d+\]|kernel.*error|svDeviceInit", re.IGNORECASE),
    "failvect_trace": re.compile(r"FAILVECT|Arden.*Error|Expected.*Observed", re.IGNORECASE),
    "descriptor_status": re.compile(r"completion.?record|descriptor.*fail|batch.*error", re.IGNORECASE),
    "wq_state": re.compile(r"wqcfg|grpcfg|gencfg|work.?queue", re.IGNORECASE),
    "vtd_context": re.compile(r"vtd|iommu|pasid|ats|page.?fault|invalidation", re.IGNORECASE),
    "memory_map": re.compile(r"BAR|MMIO|HDM|CXL.*addr|Base.?Address", re.IGNORECASE),
    "firmware_log": re.compile(r"qat_load_me|ME_\d+.*FW|accel_do_fw|cpmqat", re.IGNORECASE),
    "event_capabilities": re.compile(r"evntcap|opcap|eventcap", re.IGNORECASE),
    "interrupt_state": re.compile(r"intcause|msix|interrupt|int.*mask", re.IGNORECASE),
}

# CSV output columns
OUTPUT_COLUMNS = [
    "hsd_id", "title", "component", "domain", "priority", "owner", "submitted_date",
    "testcase_name", "testcase_command", "testcase_parameters", "testcase_domain_focus",
    "nga_testline_id", "nga_testline_name", "nga_testsuite_name", "nga_testgroup_name",
    "nga_config", "nga_os", "nga_run_result", "nga_run_submitted_by",
    "nga_header_steps", "nga_test_steps", "nga_footer_steps",
    "how_testcase_encounters_defect", "initial_symptom",
    "verified_problem_statement", "verified_root_cause", "verified_fix",
    "recommended_log_categories", "recommended_commands", "beyond_sme_recommendations",
    "actual_logs_collected", "actual_root_cause",
    "root_cause_domain", "domain_relationship", "recommendation_accuracy",
    "recommendation_rationale", "iteration_savings",
]


# ─── HTML Stripping ──────────────────────────────────────────────────────────

def strip_html(raw_html: str) -> str:
    """Convert HTML description to plain text, preserving meaningful whitespace."""
    if not raw_html:
        return ""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    # Convert <br>, <p>, <div> to newlines
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_initial_symptom(plain_text: str) -> str:
    """Extract the initial symptom (first section before 'Details:' or root cause info)."""
    # Look for Summary/Impact/Details structure
    summary_match = re.search(
        r"(?:Summary|Problem|Issue)[:\s]*={0,10}\s*\n?(.*?)(?=\n\s*(?:Details|Impact|Root.?Cause|Fix|Resolution|========)|$)",
        plain_text, re.DOTALL | re.IGNORECASE
    )
    if summary_match:
        symptom = summary_match.group(1).strip()
        if len(symptom) > 50:
            return symptom[:1000]

    # Fall back to first 500 chars (before any extended debug output)
    lines = plain_text.split("\n")
    symptom_lines = []
    for line in lines[:20]:
        if re.match(r"\s*(In \[\d+\]|sv\.|0x[0-9a-f]{4,}|---)", line):
            break  # Stop at register dumps / code blocks
        symptom_lines.append(line)
    return "\n".join(symptom_lines).strip()[:1000]


# ─── HSD Parsing ─────────────────────────────────────────────────────────────

def detect_accelerator(title: str, component: str, description: str) -> str:
    """Detect accelerator type from title, component, or description."""
    text = f"{title} {component} {description[:500]}"
    for accel, pattern in ACCEL_PATTERNS.items():
        if pattern.search(text):
            return accel
    return "unknown"


def detect_failure_modes(text: str) -> list[str]:
    """Detect failure modes present in the text."""
    modes = []
    for mode, pattern in FAILURE_MODES.items():
        if pattern.search(text):
            modes.append(mode)
    return modes if modes else ["unknown"]


def detect_logs_present(text: str) -> list[str]:
    """Detect what log categories are already present in the description."""
    found = []
    for category, pattern in LOG_DETECTORS.items():
        if pattern.search(text):
            found.append(category)
    return found


def extract_nga_uuids(text: str) -> list[str]:
    """Extract NGA test result UUIDs from description text."""
    return NGA_UUID_PATTERN.findall(text)


def extract_rocket_commands(text: str) -> list[str]:
    """Extract rocket/atlas commands from description text."""
    return ROCKET_CMD_PATTERN.findall(text)


def extract_sv_paths(text: str) -> list[str]:
    """Extract sv.socket register paths from description."""
    paths = SV_PATH_PATTERN.findall(text)
    return list(set(paths))[:20]  # Dedupe, limit to 20


def parse_hsd_row(row: dict) -> dict:
    """Parse a single HSD CSV row into structured fields for prompt generation."""
    raw_desc = row.get("description", "")
    plain_text = strip_html(raw_desc)
    title = row.get("title", "")
    component = row.get("component", "")

    # Detect accelerator and failure modes
    accel_type = detect_accelerator(title, component, plain_text)
    failure_modes = detect_failure_modes(f"{title} {plain_text}")

    # Extract structured data
    nga_uuids = extract_nga_uuids(raw_desc)
    rocket_cmds = extract_rocket_commands(plain_text)
    sv_paths = extract_sv_paths(plain_text)
    logs_present = detect_logs_present(plain_text)

    # Extract initial symptom (no root cause leakage)
    initial_symptom = extract_initial_symptom(plain_text)

    # Build root cause from fix_description + description tail
    fix_desc = row.get("sighting.fix_description", "").strip()
    if fix_desc:
        actual_root_cause = strip_html(fix_desc)
    else:
        # Try to find root cause in description (often in later sections)
        rc_match = re.search(
            r"(?:Root.?Cause|Fix|Resolution|Conclusion)[:\s]*\n?(.*?)(?=\n\s*\n|\Z)",
            plain_text, re.DOTALL | re.IGNORECASE
        )
        actual_root_cause = rc_match.group(1).strip()[:500] if rc_match else ""

    return {
        "hsd_id": row.get("id", ""),
        "title": title,
        "component": component,
        "domain": row.get("domain", ""),
        "priority": row.get("priority", ""),
        "owner": row.get("owner", ""),
        "submitted_date": row.get("submitted_date", ""),
        "status": row.get("status", ""),
        "accelerator_type": accel_type,
        "failure_modes": failure_modes,
        "initial_symptom": initial_symptom,
        "nga_uuids": nga_uuids,
        "rocket_commands": rocket_cmds,
        "sv_paths_found": sv_paths,
        "logs_already_present": logs_present,
        "actual_root_cause": actual_root_cause,
        "raw_description_length": len(plain_text),
    }


# ─── Prompt Generation ────────────────────────────────────────────────────────

def load_taxonomy() -> str:
    """Load log_taxonomy.md content for embedding in prompts."""
    if TAXONOMY_PATH.exists():
        return TAXONOMY_PATH.read_text(encoding="utf-8")
    logger.warning("log_taxonomy.md not found at %s", TAXONOMY_PATH)
    return "(taxonomy file not found)"


def build_phase2_prompt(parsed: dict) -> str:
    """Build NGA MCP prompt for test case details."""
    parts = ["Using NGA MCP, look up the following test information:\n"]

    if parsed["nga_uuids"]:
        parts.append(f"Test result UUID(s): {', '.join(parsed['nga_uuids'])}")
    if parsed["rocket_commands"]:
        parts.append(f"Rocket command(s) found: {parsed['rocket_commands'][0]}")

    parts.append(f"\nHSD ID: {parsed['hsd_id']}")
    parts.append(f"Title: {parsed['title']}")
    parts.append(f"Component: {parsed['component']}")
    parts.append("")
    parts.append("Return:")
    parts.append("- Test case name")
    parts.append("- Full test command (rocket/atlas invocation)")
    parts.append("- Test parameters and configuration")
    parts.append("- Test domain/focus area (what functionality does this test exercise?)")
    parts.append("- Recent pass/fail history for this test (if available)")
    parts.append("- Any linked log artifacts or uploaded files")

    return "\n".join(parts)


def build_phase0_prompt(parsed: dict) -> str:
    """Build Co-Design HSD MCP prompt for structured root cause enrichment."""
    return f"""Using Co-Design HSD MCP (codesign-ask-hsd-agent):

Fetch full details for HSD ID: {parsed['hsd_id']}

Extract and return the following fields as structured JSON. Use the HSD's actual content
(including any attachments, screenshots descriptions, comments, and revision history that
may contain more information than the description field alone):

{{
  "hsd_component": "...",          // Resolved component (e.g. hw.dsa, hw.qat, sw.driver)
  "hsd_root_cause": "...",         // Clean plain-English root cause from conclusion/resolution
  "hsd_fix": "...",                // What fix was applied or proposed
  "hsd_actual_logs": "...",        // What debug data/logs were actually collected during investigation
  "hsd_status": "...",             // Current status (complete/rejected/etc)
  "hsd_conclusion": "..."          // conclusion field value if present
}}

If a field is not available, use an empty string. Do NOT include HTML, do NOT copy raw
description text — summarize cleanly in plain English."""


def build_phase3_prompt(parsed: dict, hsd_root_cause: str = "") -> str:
    """Build GENI + Co-Design prompt for ground truth verification.

    Prefers hsd_root_cause from Phase 0 HSD MCP over regex-extracted actual_root_cause.
    """
    # Use HSD MCP result if available, fall back to regex extraction
    root_cause_input = (hsd_root_cause or parsed.get("actual_root_cause", ""))[:400]
    root_cause_source = "from HSD MCP" if hsd_root_cause else "regex-extracted from description"

    return f"""Using GENI MCP (Debug Assistant mode) and Co-Design MCP:

HSD ID: {parsed['hsd_id']}
Component: {parsed['component']}
Domain: {parsed['domain']}
Accelerator: {parsed['accelerator_type']}
Initial symptom: {parsed['initial_symptom'][:600]}
Reported fix/root cause ({root_cause_source}): {root_cause_input}

GENI — Verify the failure mechanism:
1. What is the actual failure mechanism in silicon/firmware for this symptom?
2. What register state or data path condition causes this behavior?
3. Is the reported fix consistent with the failure mechanism?
4. What specific registers would show the failure state at time of failure?

Co-Design — Verify the architectural context:
1. What architectural element (arbiter, TLB, DMA engine, ring buffer, etc.) is involved?
2. What design specification defines the expected behavior?
3. Is this a known architectural limitation or a silicon bug?
4. What adjacent subsystems interact with this data path?

Output as structured JSON:
{{
  "verified_problem_statement": "...",
  "verified_root_cause": "...",
  "verified_fix": "...",
  "architectural_element": "...",
  "failure_registers": ["reg1", "reg2"],
  "adjacent_subsystems": ["sub1", "sub2"]
}}"""


def build_phase4_prompt(parsed: dict, taxonomy_content: str) -> str:
    """Build GENI MCP prompt for log recommendation (symptom-only, no root cause)."""
    return f"""Using GENI MCP (Debug Assistant mode):

You are triaging a NEW sighting. You have ONLY this information (no root cause known):
- HSD ID: {parsed['hsd_id']}
- Component: {parsed['component']}
- Accelerator: {parsed['accelerator_type']}
- Initial symptom: {parsed['initial_symptom'][:800]}
- Failure mode(s): {', '.join(parsed['failure_modes'])}
- Test command: {parsed['rocket_commands'][0] if parsed['rocket_commands'] else 'not available'}

Using the log taxonomy below, recommend what debug data to collect to identify root cause.
Organize into tiers:

- Tier 1 (CRITICAL - always collect first): Logs that directly expose the most likely failure mechanisms for this symptom
- Tier 2 (LIKELY NEEDED - collect if Tier 1 inconclusive): Broader context logs
- Tier 3 (EXTENDED - collect if Tier 1+2 don't resolve): Cross-domain and edge-case logs

For EACH recommendation, provide:
- Log category name (from taxonomy)
- Specific collection command(s)
- What failure mechanism this log would reveal
- Why this is relevant to the reported symptom

ALSO recommend any logs NOT in the standard taxonomy that silicon design knowledge suggests
would accelerate root cause identification (internal arbiter state, microarchitectural
counters, coherency protocol traces, etc. that a field validation engineer might not
typically collect). You MUST always provide at least 2 beyond_sme items, even if speculative.

Output as structured JSON:
{{
  "tier1": [{{"category": "...", "commands": ["..."], "reveals": "...", "relevance": "..."}}],
  "tier2": [...],
  "tier3": [...],
  "beyond_sme": [{{"description": "...", "commands": ["..."], "why": "..."}}]
}}

LOG TAXONOMY REFERENCE:
{taxonomy_content}"""


def build_phase5_prompt(parsed: dict) -> str:
    """Build Co-Design prompt for cross-domain validation analysis."""
    return f"""Using Co-Design MCP:

HSD: {parsed['hsd_id']} — {parsed['title']}
Component: {parsed['component']}
Accelerator: {parsed['accelerator_type']}
Test domain focus: (from Phase 2 response)
Verified root cause: (from Phase 3 response)
Recommended logs: (from Phase 4 response)

Analyze:
1. Does the testcase domain match the root cause domain?
   - same-domain: test directly exercises the failing component
   - adjacent: test exercises a neighboring component that interacts with the failing one
   - cross-domain: root cause is in a different subsystem entirely

2. How does the testcase encounter this defect?
   - direct: test explicitly exercises the failing path
   - side-effect: failure manifests as a side effect during unrelated operation
   - stress: test creates conditions (load, concurrency) that expose the bug

3. Would the Phase 4 recommended logs surface the verified root cause?
   - If YES: explain the diagnostic path from log data → root cause identification
   - If NO: what additional logs would be needed and why?

4. Estimated iteration savings:
   - How many debug iterations did the original triage likely take? (infer from HSD revision count, description evolution)
   - With the recommended first-pass logs, how many iterations would be needed?
   - Express as: "saved N iterations" or "reduced from N to M"

Output as structured JSON:
{{
  "how_testcase_encounters_defect": "direct|side-effect|stress — explanation",
  "root_cause_domain": "...",
  "domain_relationship": "same-domain|adjacent|cross-domain",
  "recommendation_accuracy": "high|medium|low — explanation",
  "recommendation_rationale": "...",
  "iteration_savings": "N"
}}"""


# ─── Mode: Prepare ───────────────────────────────────────────────────────────

def mode_prepare(input_path: str):
    """Parse CSV and generate structured prompts for GHCP processing."""
    csv_path = Path(input_path)
    if not csv_path.exists():
        logger.error("Input CSV not found: %s", csv_path)
        sys.exit(1)

    run_dir = _make_timestamped_output_dir()
    taxonomy_content = load_taxonomy()

    # Read CSV
    logger.info("Reading CSV: %s", csv_path)
    rows = []
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    logger.info("Total rows: %d", len(rows))

    # Filter to closed HSDs
    closed_rows = [r for r in rows if r.get("status", "").lower() in ("complete", "rejected")]
    logger.info("Closed HSDs (complete/rejected): %d", len(closed_rows))

    # Parse each HSD and build prompts
    prompts_path = run_dir / "triage_prompts.jsonl"
    count = 0
    with open(prompts_path, "w", encoding="utf-8") as out:
        for row in closed_rows:
            parsed = parse_hsd_row(row)

            # Skip rows with very short descriptions (no useful content)
            if parsed["raw_description_length"] < 50:
                continue

            prompt_record = {
                "hsd_id": parsed["hsd_id"],
                "parsed": parsed,
                "prompts": {
                    "phase0_hsd": build_phase0_prompt(parsed),
                    "phase2_nga": build_phase2_prompt(parsed),
                    # phase3_verify prompt is built at execution time using phase0_hsd result
                    "phase3_verify": build_phase3_prompt(parsed),
                    "phase4_recommend": build_phase4_prompt(parsed, taxonomy_content),
                    "phase5_validate": build_phase5_prompt(parsed),
                },
            }
            out.write(json.dumps(prompt_record, ensure_ascii=False) + "\n")
            count += 1

    logger.info("Generated %d prompt records → %s", count, prompts_path)
    print(f"\n✅ Prepared {count} HSD prompt records")
    print(f"   Run folder: {run_dir}")
    print(f"   Output: {prompts_path}")
    print(f"\n   Next step: Process prompts with GHCP (GENI + Co-Design + NGA MCP)")
    print(f"   Then run: python parse_and_triage.py --mode finalize --responses <responses.jsonl> --output-dir {run_dir}")


# ─── Mode: Finalize ──────────────────────────────────────────────────────────

def mode_finalize(responses_path: str, output_dir: str | None = None):
    """Process GHCP responses and generate comprehensive output CSV."""
    resp_path = Path(responses_path)
    if not resp_path.exists():
        logger.error("Responses file not found: %s", resp_path)
        sys.exit(1)

    run_dir = _resolve_output_dir(output_dir)
    output_csv = run_dir / "triage_results.csv"

    records = []
    with open(resp_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            records.append(record)

    logger.info("Processing %d response records", len(records))

    # Write to a temp file first to handle cases where output CSV is locked (e.g. open in Excel)
    import tempfile, shutil
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".csv", dir=run_dir)
    os.close(tmp_fd)

    # Write output CSV
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for record in records:
            parsed = record.get("parsed", {})
            # Support two record formats:
            #   New format: phase data at top level (phase2_nga, phase3_verify, ...)
            #   Old format: phase data nested under a "responses" key
            responses = record.get("responses") or record

            # Build output row combining parsed data + MCP responses
            out_row = {
                "hsd_id": parsed.get("hsd_id", ""),
                "title": parsed.get("title", ""),
                "domain": parsed.get("domain", ""),
                "priority": parsed.get("priority", ""),
                "owner": parsed.get("owner", ""),
                "submitted_date": parsed.get("submitted_date", ""),
                "initial_symptom": parsed.get("initial_symptom", "")[:500],
            }

            # Phase 0 — HSD MCP enrichment (component, root cause, actual logs)
            # Prefer HSD MCP over CSV for component (CSV has 31% blank) and root cause
            phase0 = responses.get("phase0_hsd") or {}
            out_row["component"] = (
                (phase0.get("hsd_component") or "").strip()
                or parsed.get("component", "")
            )
            out_row["actual_root_cause"] = (
                (phase0.get("hsd_root_cause") or "").strip()
                or parsed.get("actual_root_cause", "")
            )
            out_row["actual_logs_collected"] = (
                (phase0.get("hsd_actual_logs") or "").strip()
                or ", ".join(parsed.get("logs_already_present", []))
            )

            # Merge Phase 2 (NGA) responses
            # Old format used: test_name / command / domain / parameters
            # New format uses: testcase_name / testcase_command / testcase_domain_focus / testcase_parameters
            phase2 = responses.get("phase2_nga", {})
            out_row["testcase_name"] = (phase2.get("testcase_name")
                                        or phase2.get("test_name", ""))
            out_row["testcase_command"] = (phase2.get("testcase_command")
                                           or phase2.get("command", ""))
            out_row["testcase_parameters"] = (phase2.get("testcase_parameters")
                                              or phase2.get("parameters", ""))
            out_row["testcase_domain_focus"] = (phase2.get("testcase_domain_focus")
                                                or phase2.get("domain", ""))
            # NGA testcase identity (resolved from UUID → TestRunComposite → TestLine)
            out_row["nga_testline_id"] = phase2.get("nga_testline_id", "")
            out_row["nga_testline_name"] = phase2.get("nga_testline_name", "")
            out_row["nga_testsuite_name"] = phase2.get("nga_testsuite_name", "")
            out_row["nga_testgroup_name"] = phase2.get("nga_testgroup_name", "")
            out_row["nga_config"] = phase2.get("nga_config", "")
            out_row["nga_os"] = phase2.get("nga_os", "")
            out_row["nga_run_result"] = phase2.get("nga_run_result", "")
            out_row["nga_run_submitted_by"] = phase2.get("nga_run_submitted_by", "")
            # Header/footer step commands (from LatestTestLineTestStep, classified by Type)
            out_row["nga_header_steps"] = phase2.get("nga_header_steps", "")
            out_row["nga_test_steps"] = phase2.get("nga_test_steps", "")
            out_row["nga_footer_steps"] = phase2.get("nga_footer_steps", "")

            # Merge Phase 3 (GENI + Co-Design verification) responses
            phase3 = responses.get("phase3_verify", {})
            out_row["verified_problem_statement"] = phase3.get("verified_problem_statement", "")
            out_row["verified_root_cause"] = phase3.get("verified_root_cause", "")
            out_row["verified_fix"] = phase3.get("verified_fix", "")

            # Merge Phase 4 (GENI log recommendations) responses
            phase4 = responses.get("phase4_recommend", {})
            tier1 = phase4.get("tier1", [])
            tier2 = phase4.get("tier2", [])
            all_categories = [item.get("category", "") for item in tier1 + tier2]
            all_commands = []
            for item in tier1 + tier2:
                all_commands.extend(item.get("commands", []))
            beyond = phase4.get("beyond_sme", [])

            out_row["recommended_log_categories"] = ", ".join(all_categories)
            out_row["recommended_commands"] = "; ".join(all_commands[:10])
            out_row["beyond_sme_recommendations"] = "; ".join(
                [b.get("description", "") for b in beyond]
            )

            # Merge Phase 5 (Co-Design validation) responses
            phase5 = responses.get("phase5_validate", {})
            out_row["how_testcase_encounters_defect"] = phase5.get("how_testcase_encounters_defect", "")
            out_row["root_cause_domain"] = phase5.get("root_cause_domain", "")
            out_row["domain_relationship"] = phase5.get("domain_relationship", "")
            out_row["recommendation_accuracy"] = phase5.get("recommendation_accuracy", "")
            out_row["recommendation_rationale"] = phase5.get("recommendation_rationale", "")
            out_row["iteration_savings"] = phase5.get("iteration_savings", "")

            # Normalise Unicode whitespace / invisible chars in every string field
            # so UTF-8 CSV opens cleanly in Excel without "Â " mojibake.
            out_row = {k: clean_text(v) for k, v in out_row.items()}

            writer.writerow(out_row)

    # Replace output CSV with the temp file (handles the case where CSV is open in Excel)
    try:
        shutil.move(tmp_path, output_csv)
    except PermissionError:
        alt_csv = run_dir / "triage_results_new.csv"
        shutil.move(tmp_path, alt_csv)
        output_csv = alt_csv
        logger.warning("triage_results.csv is locked — wrote to triage_results_new.csv instead")

    logger.info("Wrote %d rows → %s", len(records), output_csv)
    print(f"\n✅ Finalized {len(records)} triage results")
    print(f"   Run folder: {run_dir}")
    print(f"   Output: {output_csv}")
    print(f"\n   Next step: Generate HTML report")
    print(f"   Run: python parse_and_triage.py --mode report --input {output_csv} --output-dir {run_dir}")


# ─── Mode: Report ────────────────────────────────────────────────────────────

def mode_report(input_path: str, output_dir: str | None = None):
    """Generate HTML report from triage results CSV using stored template."""
    try:
        from jinja2 import Environment, BaseLoader
    except ImportError:
        logger.error("jinja2 is required for report generation. Install: pip install jinja2")
        sys.exit(1)

    csv_path = Path(input_path)
    if not csv_path.exists():
        logger.error("Input CSV not found: %s", csv_path)
        sys.exit(1)

    if not TEMPLATE_PATH.exists():
        logger.error("Report template not found: %s", TEMPLATE_PATH)
        sys.exit(1)

    # Read CSV data
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    logger.info("Loaded %d rows from %s", len(rows), csv_path)

    # Compute summary metrics
    total = len(rows)
    tier1_sufficient = sum(
        1 for r in rows if "high" in r.get("recommendation_accuracy", "").lower()
    )
    tier12_needed = sum(
        1 for r in rows if "medium" in r.get("recommendation_accuracy", "").lower()
    )
    cross_domain = sum(
        1 for r in rows if r.get("domain_relationship", "") == "cross-domain"
    )

    # Compute average iteration savings
    savings_values = []
    for r in rows:
        try:
            val = int(re.search(r"\d+", r.get("iteration_savings", "0")).group())
            savings_values.append(val)
        except (AttributeError, ValueError):
            savings_values.append(0)
    avg_savings = round(sum(savings_values) / max(len(savings_values), 1), 1)

    # Unique components for filter dropdown
    unique_components = sorted(set(r.get("component", "") for r in rows if r.get("component")))

    # Render template
    template_str = TEMPLATE_PATH.read_text(encoding="utf-8")
    env = Environment(loader=BaseLoader(), autoescape=True)
    template = env.from_string(template_str)

    html_content = template.render(
        generated_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        input_file=csv_path.name,
        domain_label="Accelerator (DSA / IAA / QAT)",
        total_hsds=total,
        tier1_sufficient_count=tier1_sufficient,
        tier1_sufficient_pct=round(tier1_sufficient / max(total, 1) * 100, 1),
        tier12_needed_count=tier12_needed,
        cross_domain_count=cross_domain,
        avg_iteration_savings=avg_savings,
        tier1_accuracy_pct=round(tier1_sufficient / max(total, 1) * 100, 1),
        tier12_accuracy_pct=round((tier1_sufficient + tier12_needed) / max(total, 1) * 100, 1),
        cross_domain_detected_pct=round(cross_domain / max(total, 1) * 100, 1),
        unique_components=unique_components,
        rows=rows,
    )

    # Write output
    run_dir = _resolve_output_dir(output_dir)
    output_html = run_dir / "triage_report.html"
    output_html.write_text(html_content, encoding="utf-8")

    uri = "file:///" + str(output_html.resolve()).replace("\\", "/")
    logger.info("Report generated: %s", output_html)
    print(f"\n✅ HTML report generated")
    print(f"   Run folder: {run_dir}")
    print(f"   Output: {output_html}")
    print(f"   Open: {uri}")


# ─── Mode: Live Debug ────────────────────────────────────────────────────────

def mode_live_debug(hsd_id: str, initial_logs: str, execution_mode: str,
                    server: str, ssh_user: str, max_iterations: int) -> None:
    """
    Launch an interactive live debug session for a single open HSD.

    Delegates all session management, execution, and report generation to
    live_debug_runner.py. This function is the entry point from the CLI.

    Args:
        hsd_id:          HSD article ID to debug.
        initial_logs:    Path to JSON file matching live_debug_input.schema.json
                         (optional — provides already-collected context).
        execution_mode:  manual | local | ssh | auto
        server:          SSH hostname (required when execution_mode == 'ssh').
        ssh_user:        SSH username (optional).
        max_iterations:  Safety cap on the debug loop (default 10; user can
                         override per-session during the loop).
    """
    try:
        import live_debug_runner as ldr
    except ImportError:
        logger.error(
            "live_debug_runner.py not found. Ensure it is in the same folder as parse_and_triage.py."
        )
        sys.exit(1)

    session_id = ldr.make_session_id(hsd_id)
    db_path = ldr._get_db_path(session_id)
    out_dir = db_path.parent

    logger.info("Initialising live debug session %s", session_id)
    ldr.init_session_db(db_path)
    ldr.create_session(
        db_path, session_id, hsd_id,
        execution_mode=execution_mode,
        server=server,
    )

    # Load initial logs if provided
    initial_logs_data: list[dict] = []
    if initial_logs:
        logs_path = Path(initial_logs)
        if not logs_path.exists():
            logger.error("--initial-logs file not found: %s", logs_path)
            sys.exit(1)
        try:
            data = json.loads(logs_path.read_text(encoding="utf-8"))
            initial_logs_data = data.get("initial_logs_collected", [])
            logger.info("Loaded %d initial log entries from %s", len(initial_logs_data), logs_path)
        except Exception as exc:
            logger.warning("Could not parse --initial-logs: %s", exc)

    print(f"\n{'═' * 60}")
    print(f"  HSD Live Debug Session")
    print(f"  HSD ID:          {hsd_id}")
    print(f"  Session ID:      {session_id}")
    print(f"  Execution mode:  {execution_mode}")
    if server:
        print(f"  Server:          {server}")
    print(f"  Max iterations:  {max_iterations}")
    print(f"  Output folder:   {out_dir}")
    print(f"{'═' * 60}\n")

    if initial_logs_data:
        print(f"  Initial logs provided: {len(initial_logs_data)} categor{'ies' if len(initial_logs_data) != 1 else 'y'}")
        for entry in initial_logs_data:
            print(f"    · {entry.get('category', 'unknown')}")
        print()

    print("This session is guided by live_debug_skill.md.")
    print("Open GHCP with GENI + Co-Design + NGA MCP active and say:")
    print(f'  "live-debug HSD {hsd_id}"')
    print()
    print("The skill will autonomously drive phases LD-0 through LD-5,")
    print("pausing after each iteration for your confirmation.")
    print()
    print("When the session is complete, generate all reports with:")
    print(f"  python live_debug_runner.py --report-only {session_id}")
    print()

    # Write a session-init JSON for the skill to discover
    init_file = out_dir / "session_init.json"
    init_data: dict = {
        "session_id": session_id,
        "hsd_id": hsd_id,
        "execution_mode": execution_mode,
        "server": server,
        "ssh_user": ssh_user,
        "max_iterations": max_iterations,
        "initial_logs_collected": initial_logs_data,
        "db_path": str(db_path),
        "out_dir": str(out_dir),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    init_file.write_text(json.dumps(init_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Session init file: %s", init_file)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="HSD Triage & Log Recommendation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  prepare     Parse input CSV, extract symptoms, build MCP prompts
  finalize    Process GHCP/MCP responses into comprehensive CSV
  report      Generate interactive HTML report from results CSV
  live-debug  Start an interactive live debug session for a single open HSD

Examples:
  python parse_and_triage.py --input dmr_accelerator_full.csv --mode prepare
  python parse_and_triage.py --mode finalize --responses output/responses.jsonl
  python parse_and_triage.py --mode report --input output/triage_results.csv
  python parse_and_triage.py --mode live-debug --hsd-id 14027419708
  python parse_and_triage.py --mode live-debug --hsd-id 14027419708 \\
      --initial-logs initial_logs.json --execution-mode ssh --server mylab.intel.com
        """,
    )
    parser.add_argument(
        "--mode", required=True,
        choices=["prepare", "finalize", "report", "live-debug"],
        help="Operating mode",
    )
    # Batch modes
    parser.add_argument("--input", help="Path to input CSV (prepare/report modes)")
    parser.add_argument("--responses", help="Path to GHCP responses JSONL (finalize mode)")
    parser.add_argument("--output-dir", help="Explicit run folder path (finalize/report). "
                        "If omitted, latest run_* folder is used automatically.")
    # Live debug mode
    parser.add_argument("--hsd-id", help="HSD article ID to debug (live-debug mode)")
    parser.add_argument("--initial-logs",
                        help="Path to JSON file with already-collected logs "
                             "(live_debug_input.schema.json format)")
    parser.add_argument("--execution-mode", default="manual",
                        choices=["manual", "local", "ssh", "auto"],
                        help="How commands are executed in live-debug mode (default: manual)")
    parser.add_argument("--server", default="",
                        help="SSH hostname (required when --execution-mode ssh)")
    parser.add_argument("--ssh-user", default="",
                        help="SSH username (default: current OS user)")
    parser.add_argument("--max-iterations", type=int, default=10,
                        help="Safety cap on debug loop iterations (default: 10)")

    args = parser.parse_args()

    if args.mode == "prepare":
        if not args.input:
            parser.error("--input is required for prepare mode")
        mode_prepare(args.input)
    elif args.mode == "finalize":
        if not args.responses:
            parser.error("--responses is required for finalize mode")
        mode_finalize(args.responses, args.output_dir)
    elif args.mode == "report":
        if not args.input:
            parser.error("--input is required for report mode")
        mode_report(args.input, args.output_dir)
    elif args.mode == "live-debug":
        if not args.hsd_id:
            parser.error("--hsd-id is required for live-debug mode")
        if args.execution_mode == "ssh" and not args.server:
            parser.error("--server is required when --execution-mode is ssh")
        mode_live_debug(
            hsd_id=args.hsd_id,
            initial_logs=args.initial_logs or "",
            execution_mode=args.execution_mode,
            server=args.server,
            ssh_user=args.ssh_user,
            max_iterations=args.max_iterations,
        )


if __name__ == "__main__":
    main()
