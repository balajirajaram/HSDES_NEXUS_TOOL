"""
mcp_enrichment.py — Pre-enrichment pipeline for BugScout blind analysis.

Runs three MCP phases before dispatching evidence to BugScout:
  Phase 1: Platform Identity    (codesign-ask-specs-and-wikis)
  Phase 2: Register Annotation  (codesign-ask-remote-code-repo)
  Phase 3: HSD Pattern Match    (codesign-ask-hsd-agent, signals only, root cause redacted)

Usage:
    enricher = MCPEnrichmentPipeline(
        cpuid_family=19, cpuid_model=1, cpuid_stepping=0,
        key_signals=["IERR after idle", "SEL voltage lower critical"],
        exclude_hsd_ids=["15018590736"],
        mca_banks_observed=[31],
        # mode defaults to "phase-b" (MCP-enriched); pass mode="none" for raw blind run
    )
    context_block = enricher.run()
    enriched_payload = context_block + "\n\n" + raw_evidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# HSD FIELD WHITELIST — redacts root-cause language before injecting
# ─────────────────────────────────────────────────────────────────────────────

# Fields allowed to pass through to BugScout in Phase 3
HSD_ALLOWED_FIELDS = {"id", "title", "symptom", "description", "component", "domain", "tenant"}

# Fields that must NEVER be passed to BugScout
HSD_BLOCKED_FIELDS = {
    "root_cause", "resolution", "analysis", "fix_version", "fix_stepping",
    "root_cause_summary", "workaround", "comments",
}

# Patterns in free text that suggest root-cause leakage
_ROOT_CAUSE_PATTERNS = [
    re.compile(r"root cause (is|was|identified)", re.I),
    re.compile(r"caused by", re.I),
    re.compile(r"fix (is|was|applied)", re.I),
    re.compile(r"fixed in (stepping|microcode|b0|b1|c0)", re.I),
    re.compile(r"(rasip|fivr|pstate|cstate).*(race|bug|erratum)", re.I),
]


def sanitize_hsd_result(result: dict) -> Optional[dict]:
    """Return a sanitized copy of an HSD result dict with only whitelisted fields.
    Returns None if the result is in the exclude list."""
    out = {}
    for k, v in result.items():
        if k not in HSD_ALLOWED_FIELDS:
            continue
        if isinstance(v, str):
            # Drop any field value that leaks root cause
            if any(p.search(v) for p in _ROOT_CAUSE_PATTERNS):
                v = "[redacted — contains root cause language]"
        out[k] = v
    return out if out else None


# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT BLOCK BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_platform_context_block(platform_name: str, subsystems: list[str],
                                  power_note: str, errata_domains: list[str]) -> str:
    subs = " | ".join(subsystems)
    errata = ", ".join(errata_domains)
    return (
        "=== PLATFORM CONTEXT (pre-enrichment, read-only architecture facts) ===\n"
        f"Platform: {platform_name}\n"
        f"Subsystems: {subs}\n"
        f"Power delivery: {power_note}\n"
        f"Errata domains ({platform_name.split()[-1]}): {errata}\n"
        "=== END PLATFORM CONTEXT ==="
    )


def build_register_annotation_block(bank_map: dict[int, str],
                                     msr_hints: list[str]) -> str:
    lines = ["=== REGISTER ANNOTATION (pre-enrichment) ===", "MCA Bank Map:"]
    for bank, subsystem in sorted(bank_map.items()):
        lines.append(f"  Bank {bank:>3}: {subsystem}")
    lines.append("Key diagnostic MSRs:")
    for hint in msr_hints:
        lines.append(f"  {hint}")
    lines.append("=== END REGISTER ANNOTATION ===")
    return "\n".join(lines)


def build_pattern_reference_block(matches: list[dict],
                                   excluded_ids: list[str],
                                   key_signals: list[str]) -> str:
    sig_str = ", ".join(f'"{s}"' for s in key_signals)
    lines = [
        "=== HISTORICAL PATTERN REFERENCE (observable symptoms only — root cause redacted) ===",
        f"Similar sightings for signals: {sig_str}",
        "",
    ]
    if not matches:
        lines.append("No similar sightings found (or all excluded).")
    for i, m in enumerate(matches, 1):
        hsd_id = m.get("id", "UNKNOWN")
        title = m.get("title", "(no title)")
        symptom = m.get("symptom") or m.get("description", "(no symptom)")
        domain = m.get("domain", m.get("component", ""))
        lines.append(f"{i}. HSD {hsd_id} — {title}")
        lines.append(f"   Symptom: {symptom}")
        if domain:
            lines.append(f"   Domain: {domain}")
        lines.append("")
    if excluded_ids:
        excl_str = ", ".join(excluded_ids)
        lines.append(f"[Excluded: {excl_str} — repro HSD(s), treated as ground truth labels, not pattern inputs]")
    lines.append("=== END HISTORICAL PATTERN REFERENCE ===")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MCPEnrichmentPipeline:
    """
    Orchestrates the three enrichment phases.

    In production use, each phase calls the corresponding MCP tool via the
    BugScout agent's tool-calling interface. This module provides the
    data-transformation and sanitization layer; the agent drives the MCP calls
    and passes results back to the pipeline methods below.
    """
    cpuid_family: int
    cpuid_model: int
    cpuid_stepping: int
    key_signals: list[str]
    exclude_hsd_ids: list[str] = field(default_factory=list)
    mca_banks_observed: list[int] = field(default_factory=list)
    mode: str = "phase-b"   # "phase-b" (default) | "phase-a" | "none" (raw blind)

    # Results populated by each phase
    _phase1_block: str = ""
    _phase2_block: str = ""
    _phase3_block: str = ""

    # ── Phase 1 ──────────────────────────────────────────────────────────────

    def phase1_query(self) -> str:
        """Returns the CoDesign spec query string for Phase 1."""
        return (
            f"DMR Diamond Rapids Family {self.cpuid_family} Model {self.cpuid_model} "
            f"Stepping {self.cpuid_stepping} platform architecture overview: "
            "subsystems, power delivery topology (FIVR vs external platform VR), "
            "which faults are visible in IPMI SEL vs MCA bank registers only, "
            "MCA domains, RAS architecture, known errata domains for this stepping"
        )

    def phase1_apply(self, platform_name: str, subsystems: list[str],
                     power_note: str, errata_domains: list[str]) -> None:
        """Call with MCP results to build Phase 1 context block."""
        self._phase1_block = build_platform_context_block(
            platform_name, subsystems, power_note, errata_domains
        )

    # ── Phase 2 ──────────────────────────────────────────────────────────────

    def phase2_query(self, platform_name: str) -> str:
        """Returns the remote code repo query string for Phase 2."""
        banks = ", ".join(str(b) for b in self.mca_banks_observed) if self.mca_banks_observed else "all"
        return (
            f"{platform_name} MCA bank to subsystem mapping: "
            f"which MCA bank number(s) correspond to banks {banks}? "
            "What MSR addresses read their MCA_STATUS and MCA_ADDR registers? "
            "Include RASIP error handler domain bank number and MSR address if present."
        )

    def phase2_apply(self, bank_map: dict[int, str], msr_hints: list[str]) -> None:
        """Call with MCP results to build Phase 2 context block."""
        self._phase2_block = build_register_annotation_block(bank_map, msr_hints)

    # ── Phase 3 ──────────────────────────────────────────────────────────────

    def phase3_query(self) -> str:
        """Returns the HSD MCP query string for Phase 3."""
        signals_str = "; ".join(self.key_signals)
        exclude_str = ", ".join(self.exclude_hsd_ids) if self.exclude_hsd_ids else "none"
        return (
            f"Find DMR sightings with observable symptoms matching: {signals_str}. "
            "Return only: id, title, observable symptom/description, component, domain. "
            "Do NOT return root_cause, resolution, analysis, fix_version, or fix_stepping. "
            f"Exclude these HSD IDs and any tickets linked/duplicate to them: {exclude_str}. "
            "Tenant: sighting_central.sighting, server_platf_ae.bug. Limit: 5 results."
        )

    def phase3_apply(self, raw_results: list[dict]) -> None:
        """Sanitize raw HSD MCP results and build Phase 3 context block."""
        safe_results = []
        for r in raw_results:
            # Drop excluded IDs (including linked tickets)
            hsd_id = str(r.get("id", ""))
            if hsd_id in self.exclude_hsd_ids:
                continue
            # Drop if linked_article or duplicate_of points to an excluded ID
            linked = str(r.get("linked_article", "") or r.get("duplicate_of", ""))
            if any(excl in linked for excl in self.exclude_hsd_ids):
                continue
            sanitized = sanitize_hsd_result(r)
            if sanitized:
                safe_results.append(sanitized)
        self._phase3_block = build_pattern_reference_block(
            safe_results, self.exclude_hsd_ids, self.key_signals
        )

    # ── Final Assembly ────────────────────────────────────────────────────────

    def assemble(self) -> str:
        """Assemble all active context blocks into a single prepend string."""
        if self.mode == "none":
            return ""
        parts = []
        phase_tag = f"[{self.mode.upper()} ENRICHMENT — CPUID {self.cpuid_family}/{self.cpuid_model}/{self.cpuid_stepping}]"
        parts.append(phase_tag)
        if self._phase1_block:
            parts.append(self._phase1_block)
        if self._phase2_block:
            parts.append(self._phase2_block)
        if self.mode == "phase-b" and self._phase3_block:
            parts.append(self._phase3_block)
        return "\n\n".join(parts)
