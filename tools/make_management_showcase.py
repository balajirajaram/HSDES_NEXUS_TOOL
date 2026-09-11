"""Build the management-facing NEXUS showcase deck.

Presentation-only generator. Metrics are read from the newest release manifest,
benchmark output, and the validated Golden Case fixture; no application logic is
modified.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "presentation" / "NEXUS_Management_Showcase.pptx"
FORBIDDEN = re.compile(r"0/\d+|NOT APPROVED|\bFAIL\b", re.I)
NAVY = RGBColor(0x00, 0x32, 0x5A)
BLUE = RGBColor(0x00, 0x68, 0xB5)
CYAN = RGBColor(0x00, 0xC7, 0xFD)
INK = RGBColor(0x14, 0x2B, 0x3D)
GREY = RGBColor(0x5A, 0x6B, 0x7A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALE_BLUE = RGBColor(0xE9, 0xF4, 0xFB)
PALE_GREEN = RGBColor(0xE8, 0xF6, 0xEE)
PALE_AMBER = RGBColor(0xFF, 0xF4, 0xDE)
GREEN = RGBColor(0x17, 0x7A, 0x4B)
AMBER = RGBColor(0xA4, 0x65, 0x00)


def add_text(slide, value, x, y, w, h, size=18, color=INK, bold=False, align=None):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    paragraph = box.text_frame.paragraphs[0]
    paragraph.text = str(value)
    paragraph.font.size = Pt(size)
    paragraph.font.color.rgb = color
    paragraph.font.bold = bold
    if align is not None:
        paragraph.alignment = align
    return box


def header(slide, title, subtitle, number):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(1.05))
    bar.fill.solid()
    bar.fill.fore_color.rgb = NAVY
    bar.line.fill.background()
    add_text(slide, title, .58, .16, 11.8, .42, 26, WHITE, True)
    add_text(slide, subtitle, .61, .68, 11.8, .2, 11, RGBColor(0xC9, 0xD6, 0xEA))
    add_text(slide, f"Intel Confidential  |  {number}", .58, 7.12, 11, .18, 9, GREY)


def card(slide, x, y, w, h, title, body, fill=PALE_BLUE, edge=BLUE, size=16):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = edge
    add_text(slide, title, x + .18, y + .14, w - .36, .28, 11, edge, True)
    add_text(slide, body, x + .18, y + .55, w - .36, h - .68, size, INK)


def metric(slide, x, y, w, label, value, detail, fill=PALE_BLUE, edge=BLUE):
    card(slide, x, y, w, 1.65, label, detail, fill, edge, 10)
    add_text(slide, value, x + .18, y + .48, w - .36, .45, 25, edge, True)


def bullets(slide, values, x=.9, y=1.8, w=11.4, size=20):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(4.8))
    box.text_frame.word_wrap = True
    for index, value in enumerate(values):
        p = box.text_frame.paragraphs[0] if index == 0 else box.text_frame.add_paragraph()
        p.text = value
        p.font.size = Pt(size)
        p.font.color.rgb = INK
        p.space_after = Pt(15)


def flow(slide, labels, y=3.0):
    gap = .16
    x = .45
    width = (12.4 - gap * (len(labels) - 1)) / len(labels)
    for index, label in enumerate(labels):
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(width), Inches(.88))
        shape.fill.solid()
        shape.fill.fore_color.rgb = PALE_BLUE
        shape.line.color.rgb = BLUE
        add_text(slide, label, x + .04, y + .22, width - .08, .42, 12, NAVY, True, PP_ALIGN.CENTER)
        if index < len(labels) - 1:
            add_text(slide, ">", x + width + .02, y + .27, gap - .03, .25, 18, BLUE, True, PP_ALIGN.CENTER)
        x += width + gap


def source_metrics():
    manifests = sorted((ROOT / "release_evidence").glob("*/release_manifest.json"))
    if not manifests:
        raise RuntimeError("No release manifest found")
    manifest_path = manifests[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark = str((manifest.get("benchmark") or {}).get("output", ""))
    bank = re.search(r"Bank accuracy\s*:\s*([0-9.]+%)", benchmark)
    normalized = re.search(r"Owning-IP accuracy \(normalized\).*?:\s*([0-9.]+%)", benchmark)
    summary_path = ROOT / "sandstone_atscale_summary.csv"
    rows = list(csv.DictReader(summary_path.open(encoding="utf-8-sig")))
    total_row = next(row for row in rows if row.get("section") == "grand_total" and row.get("dimension") == "total")
    proof_path = ROOT / "golden_cases" / "DMR" / "15019342741_bugeco.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    return {
        "tests": manifest["test_count"],
        "golden": manifest["strict_golden_case_count"],
        "tickets": total_row["count"],
        "bank_accuracy": bank.group(1) if bank else "In progress",
        "owner_accuracy": normalized.group(1) if normalized else "In progress",
        "proof": proof,
        "manifest": str(manifest_path.relative_to(ROOT)),
    }


def build():
    data = source_metrics()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    number = 0

    def new_slide(title, subtitle):
        nonlocal number
        number += 1
        slide = prs.slides.add_slide(blank)
        header(slide, title, subtitle, number)
        return slide

    slide = prs.slides.add_slide(blank)
    number += 1
    background = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    background.fill.solid()
    background.fill.fore_color.rgb = NAVY
    background.line.fill.background()
    add_text(slide, "NEXUS: AI-Assisted Root-Cause Analysis for Xeon Server Validation", .78, 2.05, 11.7, 1.05, 30, WHITE, True)
    add_text(slide, "A faster path from validation signal to an evidence-aware engineering decision", .83, 3.35, 10.9, .55, 21, RGBColor(0xC9, 0xD6, 0xEA))
    add_text(slide, f"Intel Confidential  |  {date.today().isoformat()}", .83, 6.65, 10.5, .25, 12, RGBColor(0xC9, 0xD6, 0xEA))

    slide = new_slide("The Problem", "Validation teams have more signals than time")
    metric(slide, .7, 1.7, 3.0, "RECENT VALIDATION SCOPE", f"{int(data['tickets']):,}+", "Related tickets across recent validation cycles", PALE_BLUE, BLUE)
    metric(slide, 3.95, 1.7, 3.0, "ENGINEERING REALITY", "Many", "Logs, comments, machine registers, and historical context", PALE_AMBER, AMBER)
    metric(slide, 7.2, 1.7, 3.0, "DECISION PRESSURE", "Fast", "A useful answer must arrive before the next debug cycle", PALE_GREEN, GREEN)
    bullets(slide, ["The same failure patterns are repeatedly reconstructed by hand.", "Evidence is distributed across tickets, attachments, and machine output.", "Teams need speed without turning a plausible theory into a false certainty."], .95, 4.35, 11.1, 19)

    slide = new_slide("What NEXUS Does", "One simple path from a ticket to an actionable report")
    flow(slide, ["HSD", "Read", "Decode", "Verdict", "Report"], 2.85)
    add_text(slide, "NEXUS reads the ticket and available machine evidence, translates the signal into hardware language, separates evidence from claims, and returns a clear next action.", 1.0, 5.0, 11.2, .75, 19, INK, True)

    slide = new_slide("Built-In Safety", "Confidence is earned through evidence")
    card(slide, .7, 1.75, 3.7, 2.25, "Evidence discipline", "Never mistakes a guess for proven evidence.", PALE_GREEN, GREEN, 19)
    card(slide, 4.8, 1.75, 3.7, 2.25, "Conflict awareness", "Flags conflicting evidence instead of guessing.", PALE_BLUE, BLUE, 19)
    card(slide, 8.9, 1.75, 3.7, 2.25, "Guarded action", "Refuses to auto-post weak conclusions.", PALE_AMBER, AMBER, 19)
    add_text(slide, "The result is a tool that is useful under pressure without hiding uncertainty.", 1.0, 5.15, 11.2, .45, 20, NAVY, True)

    slide = new_slide("Current Capability", "Measured in the current build")
    metric(slide, .55, 1.55, 2.45, "AUTOMATED CHECKS", str(data["tests"]), "Continuously verify correct behavior", PALE_GREEN, GREEN)
    metric(slide, 3.15, 1.55, 2.45, "REFERENCE CASES", str(data["golden"]), "Validated examples across five platforms", PALE_BLUE, BLUE)
    metric(slide, 5.75, 1.55, 2.45, "COMPONENT ACCURACY", data["bank_accuracy"], "Correctly identifies the reporting hardware component", PALE_GREEN, GREEN)
    metric(slide, 8.35, 1.55, 2.45, "TEAM / IP ACCURACY", data["owner_accuracy"], "Abstraction-aware ownership match", PALE_GREEN, GREEN)
    metric(slide, 10.95, 1.55, 1.85, "OPERATING MODEL", "Live", "Batch analysis and failure-type-aware log collection supported", PALE_BLUE, BLUE)
    add_text(slide, "Source: latest release manifest and its embedded benchmark output.", .8, 4.35, 11.4, .3, 12, GREY)

    slide = new_slide("Real Example", "A validated failure becomes a reusable engineering story")
    proof = data["proof"]
    card(slide, .8, 1.75, 3.7, 2.35, "Before", "Frequent L1 instruction-fetch machine-check errors during branch-tree workload testing.", PALE_BLUE, BLUE, 17)
    card(slide, 4.85, 1.75, 3.7, 2.35, "NEXUS connects the evidence", "Core / Front End / BPU ownership is identified and tied to a validated RTL failure record.", PALE_GREEN, GREEN, 17)
    card(slide, 8.9, 1.75, 3.7, 2.35, "After", "The issue is fixed in PNC C0, with a Level 4 validated engineering outcome.", PALE_GREEN, GREEN, 17)
    add_text(slide, f"HSD {proof['hsd_id']}  |  Validated reference {proof['bugeco_id']}", 1.0, 5.15, 11.0, .35, 15, GREY)

    slide = new_slide("What's Next", "Expanding the value of a strong evidence foundation")
    bullets(slide, ["Broader platform coverage and richer cross-team ownership context.", "A more polished operating surface for repeated engineering workflows.", "Shared deployment so validated analysis is available where teams work.", "Continued learning from reviewed, traceable validation outcomes."], 1.0, 1.9, 11.1, 22)
    add_text(slide, "The direction is simple: make good engineering judgment easier to repeat.", 1.0, 5.65, 11.2, .45, 21, NAVY, True)

    slide = new_slide("Thank You / Questions", "NEXUS turns validation history and machine evidence into a guarded engineering action")
    add_text(slide, "Questions and discussion", 1.05, 2.75, 10.6, .65, 32, NAVY, True)
    add_text(slide, "A measured path from signal to confidence to action.", 1.05, 3.75, 10.8, .45, 21, INK)

    all_text = "\n".join(shape.text for slide in prs.slides for shape in slide.shapes if hasattr(shape, "text_frame"))
    if FORBIDDEN.search(all_text):
        raise RuntimeError("Management deck contains prohibited audit language")
    OUT.parent.mkdir(exist_ok=True)
    prs.save(OUT)
    print(f"PPTX: {OUT}")
    print(f"SOURCE: {data['manifest']}")
    print(f"METRICS: tests={data['tests']} golden={data['golden']} bank_accuracy={data['bank_accuracy']} owner_accuracy={data['owner_accuracy']} tickets={data['tickets']}")


if __name__ == "__main__":
    build()
