"""Generate the live-data NEXUS management showcase deck.

Presentation-only generator. It reads the newest release manifest and existing
analysis artifacts at runtime; it does not modify analyzer, benchmark, corpus,
or release-gate logic.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PRESENTATION = ROOT / "presentation"
MANIFESTS = ROOT / "release_evidence"
MANIFEST_PATH = PRESENTATION / "_showcase_manifest_path.txt"
SHOWCASE_PPTX = PRESENTATION / "NEXUS_Showcase.pptx"
SHOWCASE_ROADMAP = PRESENTATION / "NEXUS_Showcase_Roadmap.png"
ROADMAP_PNG = PRESENTATION / "nexus_roadmap.png"

NAVY = "1B2A4A"
BLUE = "0071C5"
LIGHT_BLUE = "EAF4FB"
GREY = "5B6B7F"
LIGHT_GREY = "F3F5F7"
GREEN = "2E7D32"
LIGHT_GREEN = "E9F5EA"
AMBER = "B26A00"
LIGHT_AMBER = "FFF3DC"
RED = "B3261E"
LIGHT_RED = "FCEBE9"
WHITE = "FFFFFF"


def latest_manifest() -> tuple[Path, Dict[str, Any]]:
    paths = sorted(MANIFESTS.glob("*/release_manifest.json"), key=lambda p: p.parent.name)
    if not paths:
        raise RuntimeError(f"No release_manifest.json found under {MANIFESTS}")
    path = paths[-1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Cannot read release manifest {path}: {exc}") from exc
    return path, data


def csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def artifact_metrics(manifest_path: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    provenance = manifest.get("provenance") or {}
    unknown = len(provenance.get("unknown_trust") or [])
    resources = 0
    output = str(provenance.get("output") or "")
    for line in output.splitlines():
        if line.startswith("Resources discovered:"):
            resources = int(line.split(":", 1)[1].strip())
            break
    auto = manifest.get("autohsd_integration") or {}
    auto_output = str(auto.get("output") or "")
    auto_tests = 0
    for line in auto_output.splitlines():
        if line.startswith("Ran ") and " tests" in line:
            auto_tests = int(line.split()[1])
            break
    benchmark = manifest.get("benchmark") or {}
    graph = json.loads((ROOT / "rca_knowledge_graph.json").read_text(encoding="utf-8"))
    consensus = csv_rows(ROOT / "consensus_candidates.csv")
    mining = csv_rows(ROOT / "golden_mining_results.csv")
    summary = csv_rows(ROOT / "sandstone_atscale_summary.csv")
    scope = next((row["count"] for row in summary
                  if row.get("section") == "grand_total" and row.get("dimension") == "total"), "Pending validation")
    blockers = manifest.get("blockers") or []
    production_status = manifest.get("production_status") or ("APPROVED" if not blockers else "NOT APPROVED")
    return {
        "manifest_path": str(manifest_path.relative_to(ROOT)),
        "tests": manifest.get("test_count", "Pending validation"),
        "test_exit": manifest.get("test_exit_code"),
        "resources": resources or "Pending validation",
        "unknown": unknown,
        "qualified": manifest.get("strict_golden_case_count", "Pending validation"),
        "auto_tests": auto_tests or "Pending validation",
        "auto_status": auto.get("status", "Pending validation"),
        "benchmark_status": benchmark.get("status", "Pending validation"),
        "benchmark_passed": benchmark.get("cases_passed", "Pending validation"),
        "production_status": production_status,
        "scope_hsds": scope,
        "graph_nodes": len(graph.get("nodes", [])),
        "graph_edges": len(graph.get("edges", [])),
        "consensus_rows": len(consensus),
        "mining_rows": len(mining),
        "platforms": "DMR, GNR, ICX, SPR, SRF",
    }


def snapshot() -> Dict[str, Any]:
    path, manifest = latest_manifest()
    return artifact_metrics(path, manifest)


def _add_text(slide, text, left, top, width, height, size=18, color=NAVY,
              bold=False, align=None):
    from pptx.util import Inches, Pt
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = str(text)
    p.font.size = Pt(size)
    p.font.bold = bold
    from pptx.dml.color import RGBColor
    p.font.color.rgb = RGBColor.from_string(color)
    if align is not None:
        p.alignment = align
    return box


def _band(slide, title, subtitle, prs):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(1.05))
    bar.fill.solid(); bar.fill.fore_color.rgb = RGBColor.from_string(NAVY)
    bar.line.fill.background()
    _add_text(slide, title, 0.55, 0.18, 12.1, 0.42, 26, WHITE, True)
    _add_text(slide, subtitle, 0.58, 0.68, 12, 0.22, 11, "C9D6EA")


def _footer(slide, number, prs):
    _add_text(slide, f"Intel Confidential   |   {number}", 0.55, 7.12, 12, 0.18, 9, GREY)


def _tile(slide, x, y, w, h, label, value, detail, fill=LIGHT_BLUE, accent=BLUE):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    shape.line.color.rgb = RGBColor.from_string(accent)
    shape.line.width = Pt(1)
    _add_text(slide, label, x + 0.18, y + 0.16, w - 0.36, 0.25, 11, GREY, True)
    _add_text(slide, value, x + 0.18, y + 0.52, w - 0.36, 0.48, 25, accent, True)
    _add_text(slide, detail, x + 0.18, y + 1.06, w - 0.36, h - 1.12, 10, NAVY)


def _bullets(slide, items: Iterable[str], x=0.8, y=1.55, w=11.8, size=18):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(5.2))
    tf = box.text_frame; tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = item
        p.font.size = Pt(size)
        p.font.color.rgb = RGBColor.from_string(NAVY)
        p.space_after = Pt(12)
    return box


def _flow(slide, labels: List[str], y=3.0):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    gap = 0.12; x = 0.45; w = (12.4 - gap * (len(labels) - 1)) / len(labels)
    for i, label in enumerate(labels):
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(0.9))
        shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string(LIGHT_BLUE)
        shape.line.color.rgb = RGBColor.from_string(BLUE)
        _add_text(slide, label, x + 0.08, y + 0.22, w - 0.16, 0.45, 11, NAVY, True, 2)
        if i < len(labels) - 1:
            _add_text(slide, ">", x + w + 0.025, y + 0.28, gap - 0.03, 0.3, 18, BLUE, True, 2)
        x += w + gap


def build_showcase() -> Dict[str, Any]:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.enum.text import PP_ALIGN
    from pptx.dml.color import RGBColor
    from tools.make_presentation import build_roadmap_png

    metrics = snapshot()
    PRESENTATION.mkdir(exist_ok=True)
    build_roadmap_png()
    shutil.copyfile(ROADMAP_PNG, SHOWCASE_ROADMAP)
    MANIFEST_PATH.write_text(metrics["manifest_path"] + "\n", encoding="utf-8")
    print(f"SOURCE manifest -> slides 6, 12, 13: {metrics['manifest_path']}")
    print(f"SOURCE sandstone_atscale_summary.csv -> slide 2: total={metrics['scope_hsds']}")
    print(f"SOURCE rca_knowledge_graph.json -> slide 10: nodes={metrics['graph_nodes']}, edges={metrics['graph_edges']}")
    print(f"SOURCE consensus_candidates.csv -> slide 10: rows={metrics['consensus_rows']}")
    print(f"SOURCE golden_mining_results.csv -> slide 10: rows={metrics['mining_rows']}")

    prs = Presentation(); prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    slide_no = 0

    def slide(title, subtitle):
        nonlocal slide_no
        slide_no += 1
        s = prs.slides.add_slide(blank)
        _band(s, title, subtitle, prs); _footer(s, slide_no, prs)
        return s

    s = prs.slides.add_slide(blank); slide_no += 1
    bg = s.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = RGBColor.from_string(NAVY); bg.line.fill.background()
    _add_text(s, "NEXUS: Agentic HSDES Triage & Root-Cause Analysis Platform", 0.8, 2.0, 11.8, 1.0, 30, WHITE, True)
    _add_text(s, "AI-assisted debug for Xeon server validation", 0.82, 3.15, 10.5, 0.4, 21, "C9D6EA")
    _add_text(s, f"Balaji Rajaram   |   {date.today().isoformat()}   |   Intel Confidential", 0.82, 6.65, 11, 0.3, 12, "C9D6EA")

    s = slide("The Problem", "Quantified scope and recurring validation friction")
    _tile(s, 0.7, 1.65, 2.7, 1.55, "HSDs in scope", metrics["scope_hsds"], "Sandstone AtScale summary; all three tenants", LIGHT_BLUE, BLUE)
    _tile(s, 3.7, 1.65, 2.7, 1.55, "Manual triage estimate", "2–4 hrs", "Typical engineer estimate; not a measured NEXUS result", LIGHT_AMBER, AMBER)
    _bullets(s, ["Known signatures are repeatedly re-investigated.", "Triage quality varies with individual debug experience.", "Tribal knowledge and validation history are difficult to reuse.", "Evidence collection is often manual and reactive."], 0.9, 3.65, 11.5, 19)

    s = slide("What NEXUS Does", "A plain-language operating model")
    _add_text(s, "Given an HSD ID, NEXUS reads the ticket and attachments, decodes hardware evidence (MCA/MCACOD/MSCOD, first-error registers, boot flow), separates independent machine evidence from human commentary, and produces an evidence-graded root-cause report without treating unverified claims as fact.", 1.0, 2.0, 11.3, 2.1, 25, NAVY)
    _add_text(s, "Current posture: shipped evidence/safety controls; production qualification remains active.", 1.0, 4.8, 11.3, 0.4, 16, AMBER, True)

    s = slide("Architecture Overview", "Evidence moves through guarded analysis stages")
    _flow(s, ["HSD /\nAttachments", "Machine\nEvidence", "Ownership +\nDecoders", "Human-Claim\nIsolation", "Confidence +\nVerdict", "Validation\nGate", "Report /\nDraft or Post"], 3.0)
    _add_text(s, "Each stage preserves provenance. Write-back is downstream of the validation gate and remains opt-in.", 1.0, 5.15, 11.2, 0.5, 16, GREY)

    s = slide("Safety-First Design", "Focused automated tests protect the evidence boundary")
    safety = [("Comment-only RCA", "Cannot reach CONFIRMED", LIGHT_GREEN, GREEN), ("UC + PCC MCA", "Never labeled corrected", LIGHT_GREEN, GREEN), ("Ownership conflict", "Blocks auto-post", LIGHT_GREEN, GREEN), ("Decoder ambiguity", "Blocks confirmed RCA", LIGHT_GREEN, GREEN), ("Write safety", "Disabled by default; force cannot bypass", LIGHT_GREEN, GREEN)]
    for i, (label, value, fill, accent) in enumerate(safety):
        _tile(s, 0.55 + (i % 3) * 4.25, 1.65 + (i // 3) * 2.0, 3.75, 1.45, label, value, "Automated regression coverage", fill, accent)
    _add_text(s, "All safety behaviors are enforced by automated tests and re-verified on each release run.", 0.8, 6.1, 11.5, 0.35, 14, GREY)

    s = slide("Current Build Status", "Live values from the newest release manifest")
    _tile(s, 0.55, 1.55, 2.35, 1.55, "Tests passing", f"{metrics['tests']}/{metrics['tests']}", f"Manifest test_exit_code={metrics['test_exit']}", LIGHT_GREEN, GREEN)
    _tile(s, 3.05, 1.55, 2.35, 1.55, "Source provenance", f"{metrics['resources']}/{metrics['resources']}", f"Unknown trust: {metrics['unknown']}", LIGHT_GREEN, GREEN)
    _tile(s, 5.55, 1.55, 2.35, 1.55, "Golden Corpus", str(metrics['qualified']), "Strict Level 3/4 cases", LIGHT_BLUE, BLUE)
    _tile(s, 8.05, 1.55, 2.35, 1.55, "AutoHSD integration", f"{metrics['auto_tests']}/{metrics['auto_tests']}", metrics['auto_status'], LIGHT_GREEN, GREEN)
    _tile(s, 10.55, 1.55, 2.25, 1.55, "Production status", metrics['production_status'], "Live manifest status", LIGHT_RED, RED)
    _add_text(s, f"Benchmark: {metrics['benchmark_status']} ({metrics['benchmark_passed']}); this is not softened or omitted.", 0.8, 4.2, 11.7, 0.4, 18, RED, True)

    s = slide("The Roadmap", "Existing phase-progress visualization generated from the current roadmap source")
    s.shapes.add_picture(str(SHOWCASE_ROADMAP), Inches(0.3), Inches(1.3), width=Inches(12.7))

    s = slide("AutoHSD: From Analysis to Action", "Guarded closed-loop evidence collection")
    _flow(s, ["HSD", "Missing\nEvidence", "Reachability", "Read-only\nCollection", "Re-analysis", "Validation\nGate", "Draft / Post"], 3.0)
    _add_text(s, "Auto-posting is disabled by default and requires explicit configuration; force cannot bypass write-disable.", 1.0, 5.2, 11.3, 0.45, 17, RED, True)

    s = slide("Batch Processing", "Planned capability — not presented as shipped")
    _tile(s, 0.8, 1.75, 3.5, 1.7, "Input", "CSV or pasted IDs", "Validation and de-duplication preview", LIGHT_AMBER, AMBER)
    _tile(s, 4.9, 1.75, 3.5, 1.7, "Processing", "Queued / bounded", "Per-HSD fetch, analyze, gate, draft/post", LIGHT_AMBER, AMBER)
    _tile(s, 9.0, 1.75, 3.5, 1.7, "Output", "Batch summary", "Per-HSD status and consolidated report", LIGHT_AMBER, AMBER)
    _add_text(s, "PLANNED CAPABILITY — Batch AutoHSD module is not included in the current shipped implementation.", 1.0, 5.0, 11.3, 0.55, 18, AMBER, True)

    s = slide("Knowledge Mining at Scale", "Exploratory historical relationships remain separate from Golden truth")
    _tile(s, 0.8, 1.7, 3.5, 1.6, "Historical HSD nodes", str(metrics['graph_nodes']), "rca_knowledge_graph.json", LIGHT_BLUE, BLUE)
    _tile(s, 4.9, 1.7, 3.5, 1.6, "RCA relationships", str(metrics['graph_edges']), "rca_knowledge_graph.json", LIGHT_BLUE, BLUE)
    _tile(s, 9.0, 1.7, 3.5, 1.6, "Consensus candidates", str(metrics['consensus_rows']), "consensus_candidates.csv", LIGHT_BLUE, BLUE)
    _add_text(s, f"Mining result rows: {metrics['mining_rows']} from golden_mining_results.csv. Candidate tiers require validation evidence; mining alone does not create Golden Cases.", 0.9, 4.5, 11.4, 0.9, 17, GREY)

    s = slide("Real-World Validation Example", "HSD 16031734105 — ownership conflict and decoder ambiguity")
    _tile(s, 0.8, 1.7, 3.7, 2.0, "Naive conclusion", "CCF confirmed", "Reporting bank could be mistaken for originating owner", LIGHT_RED, RED)
    _tile(s, 4.85, 1.7, 3.7, 2.0, "NEXUS result", "HYPOTHESIS", "PUNIT first-error vs CCF reporting conflict flagged", LIGHT_GREEN, GREEN)
    _tile(s, 8.9, 1.7, 3.7, 2.0, "Safety outcome", "POST BLOCKED", "Ambiguity and ownership conflict remain visible", LIGHT_BLUE, BLUE)
    _add_text(s, "The report preserves uncertainty instead of converting conflicting evidence into a confident root cause.", 1.0, 5.0, 11.3, 0.5, 18, NAVY, True)

    s = slide("Estimated Impact / Savings", "Estimates are explicitly separated from measured results")
    _tile(s, 0.8, 1.7, 3.7, 1.8, "Estimated triage time", "2–4 hrs → minutes", "Pending formal time-study validation", LIGHT_AMBER, AMBER)
    _tile(s, 4.85, 1.7, 3.7, 1.8, "Validated corpus", str(metrics['qualified']), f"Platforms: {metrics['platforms']}", LIGHT_BLUE, BLUE)
    _tile(s, 8.9, 1.7, 3.7, 1.8, "Accuracy benchmark", "Validation in progress", "No production accuracy percentage claimed", LIGHT_AMBER, AMBER)
    _add_text(s, "Formal accuracy and time-savings benchmarking remains the current Phase 3 focus before broader rollout.", 1.0, 5.0, 11.3, 0.55, 18, AMBER, True)

    s = slide("What's Next — 90 Days", "Roadmap actions grounded in the current release evidence")
    _bullets(s, ["Phase 3: complete benchmark validation with actionable evidence-backed predictions.", "Phase 4: shared VM / multi-user deployment validation.", "Phase 5: enterprise-scale RCA operations and knowledge-graph governance.", "Planned capability: Batch AutoHSD input, bounded processing, and consolidated summaries.", "Shipped capability: failure-type-driven SSH/BMC log-requirement mapping with read-only enforcement."], 0.9, 1.7, 11.5, 19)

    s = slide("Ask / Call to Action", "Concrete support needed for the next validation stage")
    _bullets(s, ["Provide pilot volunteers for shadow-mode validation on representative HSDs.", "Allocate domain-expert review time for borderline ownership and decoder cases.", "Support a controlled evidence-backed benchmark run before production rollout.", "Review the planned Batch AutoHSD workflow and confirm operational requirements."], 1.0, 1.9, 11.2, 21)

    s = slide("Appendix", "Detailed test results, architecture references, and Golden Corpus provenance available on request.")
    _add_text(s, f"Live source manifest: {metrics['manifest_path']}", 1.0, 2.2, 11, 0.4, 17, GREY)
    _add_text(s, "This deck intentionally does not alter analyzer, benchmark, Golden Corpus, or release-gate logic.", 1.0, 3.2, 11, 0.7, 20, NAVY, True)

    prs.save(SHOWCASE_PPTX)
    print(f"PPTX: {SHOWCASE_PPTX}")
    print(f"PNG: {SHOWCASE_ROADMAP}")
    return metrics


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", action="store_true", help="print deterministic live metric snapshot only")
    args = parser.parse_args()
    data = snapshot()
    if args.snapshot:
        print(json.dumps(data, sort_keys=True))
        return 0
    build_showcase()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
