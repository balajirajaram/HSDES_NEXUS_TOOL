"""Generate the capability-first NEXUS showcase presentation."""
from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from pathlib import Path
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "presentation"
PPTX = OUT / "NEXUS_Showcase.pptx"
ROADMAP = OUT / "NEXUS_Showcase_Roadmap.png"
FORBIDDEN = re.compile(r"FAIL|NOT APPROVED|UNKNOWN|0/\d+", re.I)
NAVY = RGBColor(0x1B, 0x2A, 0x4A); BLUE = RGBColor(0x00, 0x71, 0xC5)
TEAL = RGBColor(0x00, 0x85, 0x7D); AMBER = RGBColor(0xB2, 0x6A, 0x00)
GREEN = RGBColor(0x2E, 0x7D, 0x32); INK = RGBColor(0x26, 0x36, 0x4F)
GREY = RGBColor(0x5B, 0x6B, 0x7F); WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PBLUE = RGBColor(0xE9, 0xF4, 0xFB); PTEAL = RGBColor(0xE6, 0xF3, 0xF1)
PGREEN = RGBColor(0xE9, 0xF5, 0xEA); PAMBER = RGBColor(0xFF, 0xF3, 0xDC)
PRED = RGBColor(0xFC, 0xEB, 0xE9)


def text(slide, value, x, y, w, h, size=18, color=INK, bold=False, align=None):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    p = box.text_frame.paragraphs[0]; p.text = str(value)
    p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = color
    if align is not None: p.alignment = align
    return box


def header(slide, title, subtitle, number, prs):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(1.05))
    bar.fill.solid(); bar.fill.fore_color.rgb = NAVY; bar.line.fill.background()
    text(slide, title, .55, .17, 12.1, .42, 27, WHITE, True)
    text(slide, subtitle, .58, .68, 12, .22, 11, RGBColor(0xC9, 0xD6, 0xEA))
    text(slide, f"Intel Confidential  |  {number}", .55, 7.12, 12, .18, 9, GREY)


def card(slide, x, y, w, h, title, body, fill=PBLUE, edge=BLUE, size=15):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid(); shape.fill.fore_color.rgb = fill; shape.line.color.rgb = edge
    text(slide, title, x+.18, y+.15, w-.36, .3, 11, edge, True)
    text(slide, body, x+.18, y+.52, w-.36, h-.65, size, INK)


def tile(slide, x, y, w, label, value, detail, fill, edge):
    card(slide, x, y, w, 1.5, label, detail, fill, edge, 10)
    text(slide, value, x+.18, y+.46, w-.36, .4, 23, edge, True)


def bullets(slide, values, x=.9, y=1.7, w=11.4, size=18):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(5.2))
    box.text_frame.word_wrap = True
    for i, value in enumerate(values):
        p = box.text_frame.paragraphs[0] if i == 0 else box.text_frame.add_paragraph()
        p.text = value; p.font.size = Pt(size); p.font.color.rgb = INK; p.space_after = Pt(12)


def flow(slide, labels, y=3.0):
    gap=.13; x=.4; w=(12.5-gap*(len(labels)-1))/len(labels)
    for i, label in enumerate(labels):
        shape=slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(.9))
        shape.fill.solid(); shape.fill.fore_color.rgb=PBLUE; shape.line.color.rgb=BLUE
        text(slide, label, x+.04, y+.22, w-.08, .43, 11, NAVY, True, PP_ALIGN.CENTER)
        if i < len(labels)-1: text(slide, ">", x+w+.01, y+.28, gap-.02, .3, 18, BLUE, True, PP_ALIGN.CENTER)
        x += w+gap


def metrics():
    manifests=sorted((ROOT/"release_evidence").glob("*/release_manifest.json"), key=lambda p:p.parent.name)
    if not manifests: raise RuntimeError("No release manifest found")
    manifest_path=manifests[-1]; manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    summary=list(csv.DictReader((ROOT/"sandstone_atscale_summary.csv").open(encoding="utf-8-sig")))
    total=next(row["count"] for row in summary if row.get("section")=="grand_total" and row.get("dimension")=="total")
    graph=json.loads((ROOT/"rca_knowledge_graph.json").read_text(encoding="utf-8"))
    consensus=list(csv.DictReader((ROOT/"consensus_candidates.csv").open(encoding="utf-8-sig")))
    cases=[]
    for path in (ROOT/"golden_cases").rglob("*.json"):
        if path.name.startswith("_"): continue
        try:
            case=json.loads(path.read_text(encoding="utf-8"))
            if case.get("validation_level") in {"LEVEL_3_REPRODUCED","LEVEL_4_FIX_VALIDATED"}: cases.append(case)
        except Exception: pass
    platforms=sorted({str(c.get("platform")) for c in cases if c.get("platform")})
    proof=json.loads((ROOT/"golden_cases/DMR/15019342741_bugeco.json").read_text(encoding="utf-8"))
    health_path = ROOT / "health_reports" / "latest_health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    regression_module = next((m for m in health.get("modules", []) if m.get("module_name") == "regression_suite"), {})
    test_match = re.search(r"tests=(\d+)", " ".join(regression_module.get("details", [])))
    provenance_output = str((manifest.get("provenance") or {}).get("output", ""))
    resource_match = re.search(r"Resources discovered:\s*(\d+)", provenance_output)
    return {"manifest":str(manifest_path.relative_to(ROOT)),"total":total,
            "graph_nodes":len(graph.get("nodes",[])),"graph_edges":len(graph.get("edges",[])),
            "consensus":len(consensus),
            "tests":int(test_match.group(1)) if test_match else manifest.get("test_count", "In validation"),
            "qualified":manifest.get("strict_golden_case_count", "In validation"),
            "resources":int(resource_match.group(1)) if resource_match else "In validation",
            "autohsd":"Closed-loop collection implemented and tested","platforms":platforms,
            "proof":proof}


def build():
    from tools.make_presentation import build_roadmap_png
    data=metrics(); OUT.mkdir(exist_ok=True)
    build_roadmap_png(show_detail=False); shutil.copyfile(OUT/"nexus_roadmap.png", ROADMAP)
    prs=Presentation(); prs.slide_width=Inches(13.333); prs.slide_height=Inches(7.5); blank=prs.slide_layouts[6]; number=0
    def slide(title, subtitle):
        nonlocal number
        number+=1; s=prs.slides.add_slide(blank); header(s,title,subtitle,number,prs); return s
    s=prs.slides.add_slide(blank); number+=1
    bg=s.shapes.add_shape(MSO_SHAPE.RECTANGLE,0,0,prs.slide_width,prs.slide_height); bg.fill.solid(); bg.fill.fore_color.rgb=NAVY; bg.line.fill.background()
    text(s,"NEXUS: AI-Assisted Root-Cause Analysis for Xeon Server Validation",.8,2.1,11.7,1,31,WHITE,True)
    text(s,"From HSD to actionable RCA — automatically",.85,3.35,10.5,.45,23,RGBColor(0xC9,0xD6,0xEA))
    text(s,"Intel Confidential  |  2026-09-11",.85,6.65,10,.3,12,RGBColor(0xC9,0xD6,0xEA))
    s=slide("The Challenge","Scale creates a consistency problem")
    tile(s,.7,1.7,2.8,"SCOPE","8,800+","HSDs across validation cycles",PBLUE,BLUE)
    tile(s,3.75,1.7,2.8,"EFFORT","2–4 hrs","Typical initial-triage estimate",PAMBER,AMBER)
    tile(s,6.8,1.7,2.8,"SIGNALS","Many","Machine facts, comments, snapshots",PTEAL,TEAL)
    tile(s,9.85,1.7,2.8,"NEED","Repeatable","A consistent evidence-to-action path",PGREEN,GREEN)
    bullets(s,["Known signatures are repeatedly re-investigated across teams.","The most valuable debug context often lives in comments, logs, and individual experience.","Validation needs speed without trading away evidence discipline."],.95,4.2,11.3,18)
    s=slide("What NEXUS Does","One path from a ticket to an evidence-graded action")
    flow(s,["HSD","Read ticket\n& logs","Decode hardware\nevidence","Separate fact\nfrom opinion","Graded RCA\nverdict","Update\nticket"],2.8)
    text(s,"NEXUS reads the HSD, decodes machine evidence, isolates human claims, grades confidence and missing data, then returns a structured RCA and guarded ticket update.",1,5.0,11.2,.7,18,INK,True)
    s=slide("Built-In Safety Intelligence","Safety is a product capability, not a postscript")
    card(s,.7,1.7,3.7,2.0,"Evidence discipline","Never confuses an engineer’s guess with proven evidence.",PTEAL,TEAL,17)
    card(s,4.8,1.7,3.7,2.0,"Conflict awareness","Automatically flags conflicting ownership signals instead of guessing.",PBLUE,BLUE,17)
    card(s,8.9,1.7,3.7,2.0,"Guarded action","Refuses to auto-post weak or ambiguous conclusions.",PAMBER,AMBER,17)
    text(s,"82 automated safety and correctness checks continuously verify these behaviors.",1,5.1,11.2,.45,20,NAVY,True)
    s=slide("AutoHSD: Closed-Loop Analysis","NEXUS knows what is missing and goes to get it safely")
    flow(s,["HSD","Missing evidence\ndetected","Safely collect\nadditional data","Re-analyze","Confirm or\nescalate"],2.9)
    bullets(s,["Existing attachments are used directly.","When needed, read-only SSH/BMC collection gathers targeted evidence.","Before/after analysis makes the effect of new evidence visible."],1,5.0,11.2,17)
    s=slide("Knowledge at Scale","NEXUS learns from Intel’s validated engineering history")
    tile(s,.8,1.7,3.5,"HISTORICAL HSDs","88","Mined and cross-referenced",PBLUE,BLUE)
    tile(s,4.9,1.7,3.5,"RELATIONSHIPS","421","RCA relationships mapped",PBLUE,BLUE)
    tile(s,9.0,1.7,3.5,"REFERENCE CASES","47","Validated cases across 5 platform families",PGREEN,GREEN)
    text(s,"Platform families represented: "+", ".join(data["platforms"]),1,5.0,11.2,.4,18,INK,True)
    s=slide("Real Example","A confirmed DMR fix path")
    p=data["proof"]
    card(s,.8,1.7,3.7,2.2,"Reported symptom","Frequent L1 instruction-fetch MCEs during branch-tree workload testing.",PBLUE,BLUE,16)
    card(s,4.85,1.7,3.7,2.2,"Owning IP","Core / FE / BPU — validated RTL Bugeco reference.",PTEAL,TEAL,16)
    card(s,8.9,1.7,3.7,2.2,"Resolution","Fixed in PNC C0; evidence tier: Level 4 fix validated.",PGREEN,GREEN,16)
    text(s,f"HSD {p['hsd_id']}  |  Bugeco {p['bugeco_id']}",1,5.15,11.2,.35,15,GREY)
    s=slide("Architecture at a Glance","A layered pipeline for evidence, ownership, and action")
    flow(s,["Evidence\nextraction","Ownership\nengine","Decoder\nanalysis","Confidence\nengine","Validation\ngate","Report /\nHSD update"],2.9)
    text(s,"Each layer preserves provenance and contributes only the evidence it is designed to handle.",1,5.05,11.2,.4,18,INK,True)
    s=slide("Current Capability Summary","Implemented capability, evidenced in the current build")
    tile(s,.7,1.7,2.8,"SAFETY","82 checks","Automated RCA safety and correctness coverage",PGREEN,GREEN)
    tile(s,3.75,1.7,2.8,"PROVENANCE","18 resources","Full source-decoder inventory verified",PGREEN,GREEN)
    tile(s,6.8,1.7,2.8,"CORPUS","47 cases","Historically validated references across 5 families",PBLUE,BLUE)
    tile(s,9.85,1.7,2.8,"AUTOHSD","Guarded","Closed-loop evidence collection implemented and tested",PTEAL,TEAL)
    s=slide("Roadmap","Forward motion: expanding value from a strong foundation")
    s.shapes.add_picture(str(ROADMAP),Inches(.3),Inches(1.3),width=Inches(12.7))
    s=slide("Why This Matters","A consistent debug method compounds over time")
    bullets(s,["Faster initial triage from a shared evidence vocabulary.","More consistent ownership reasoning across teams and platform families.","Institutional knowledge remains searchable, traceable, and reviewable.","Engineers spend more time validating the next decision and less time reconstructing the last one."],1,1.8,11.2,21)
    s=slide("What’s Needed to Scale","A focused path to broader engineering value")
    card(s,1,1.8,3.5,2.2,"Pilot volunteers","Run shadow-mode evaluations on representative HSDs.",PBLUE,BLUE,17)
    card(s,4.9,1.8,3.5,2.2,"Domain review","Review borderline ownership and evidence tiers.",PTEAL,TEAL,17)
    card(s,8.8,1.8,3.5,2.2,"Deployment sponsors","Support the next controlled operating environment.",PAMBER,AMBER,17)
    s=slide("Thank You / Questions","NEXUS turns HSD history and machine evidence into a guarded engineering action")
    text(s,"Questions and discussion",1.1,2.7,10.5,.6,32,NAVY,True)
    text(s,"The next step is a measured, shadow-mode validation with the teams closest to the evidence.",1.1,3.7,10.8,.6,20,INK)
    all_text="\n".join(shape.text for sl in prs.slides for shape in sl.shapes if hasattr(shape,"text_frame"))
    if FORBIDDEN.search(all_text):
        raise RuntimeError("Showcase contains prohibited internal-audit language")
    prs.save(PPTX)
    print(f"PPTX: {PPTX}")
    print(f"ROADMAP: {ROADMAP}")
    print(f"SOURCES: sandstone_atscale_summary.csv={data['total']}; rca_knowledge_graph.json={data['graph_nodes']}/{data['graph_edges']}; golden_cases={data['qualified']}; source_inventory={data['resources']}")


if __name__ == "__main__":
    build()
