"""Render markdown RCA reports into standalone HTML pages."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional

import markdown

APP_NAME = "HSDES NEXUS"


def _extract_meta_value(src: str, label: str) -> str:
  pattern = rf"\|\s*\*\*{re.escape(label)}\*\*\s*\|\s*(.*?)\s*\|"
  m = re.search(pattern, src, flags=re.IGNORECASE)
  return m.group(1).strip() if m else ""


def _extract_first_heading(src: str) -> str:
  m = re.search(r"^#\s+(.+?)\s*$", src, flags=re.MULTILINE)
  return m.group(1).strip() if m else ""


def _extract_first_bold_line(src: str) -> str:
  m = re.search(r"^\*\*(.+?)\*\*\s*$", src, flags=re.MULTILINE)
  return m.group(1).strip() if m else ""


def _extract_int(src: str, pattern: str) -> int:
  m = re.search(pattern, src, flags=re.IGNORECASE)
  if not m:
    return 0
  raw = m.group(1).replace(",", "")
  try:
    return int(raw)
  except ValueError:
    return 0


def _extract_confidence(src: str) -> int:
  m = re.search(r"confidence\s*(\d{1,3})%", src, flags=re.IGNORECASE)
  if not m:
    return 0
  val = int(m.group(1))
  return max(0, min(val, 100))


def _confidence_class(conf: int) -> str:
  if conf >= 75:
    return "conf-high"
  if conf >= 40:
    return "conf-med"
  return "conf-low"


def _card_class_for_heading(h: str) -> str:
  hl = h.lower()
  if "root cause" in hl:
    return "card-rootcause"
  if "findings summary" in hl or "debug summary" in hl:
    return "card-summary"
  if "next actions" in hl or "recommended fix" in hl:
    return "card-actions"
  if "appendix" in hl:
    return "card-appendix"
  return "card-default"


def _sectionize_html(body_html: str) -> str:
  # Wrap each H2 section into BugScout-like content cards while preserving tables/code blocks.
  parts = re.split(r"(?is)(<h2[^>]*>.*?</h2>)", body_html)
  if len(parts) < 3:
    return f'<section class="report-card card-default">{body_html}</section>'

  chunks = []
  preface = (parts[0] or "").strip()
  if preface:
    chunks.append(f'<section class="report-card card-default">{preface}</section>')

  i = 1
  while i < len(parts):
    heading_html = parts[i]
    content_html = parts[i + 1] if i + 1 < len(parts) else ""
    plain_heading = re.sub(r"<[^>]+>", "", heading_html or "").strip()
    klass = _card_class_for_heading(plain_heading)
    chunks.append(
      f'<section class="report-card {klass}">'
      f'<div class="section-head">{heading_html}</div>'
      f'<div class="section-body">{content_html}</div>'
      f"</section>"
    )
    i += 2

  return "\n".join(chunks)


def render_report_html(markdown_text: str, title: Optional[str] = None) -> str:
  """Convert markdown report text to a richer BugScout-style standalone HTML document."""
  src = markdown_text or ""
  heading = _extract_first_heading(src)
  subtitle = _extract_first_bold_line(src)
  report_title = (title or heading or "Auto HSD Analysis Report").strip() or "Auto HSD Analysis Report"
  doc_title = html.escape(report_title)

  platform = _extract_meta_value(src, "Platform / Family") or "Unknown"
  component = _extract_meta_value(src, "Component / Domain") or "Unknown"
  status = _extract_meta_value(src, "Status / Priority") or "Unknown"
  owner = _extract_meta_value(src, "Owner") or "Unknown"
  analyzed_on = _extract_meta_value(src, "Date") or "Unknown"

  comments = _extract_int(src, r"Comment thread:\**\s*([0-9,]+)\s*comment")
  attachments = _extract_int(src, r"Attachments:\**\s*([0-9,]+)\s*on ticket")
  lines_scanned = _extract_int(src, r"Log volume analysed:\**\s*([0-9,]+)\s*line")
  confidence = _extract_confidence(src)
  conf_class = _confidence_class(confidence)

  body = markdown.markdown(
    src,
    extensions=[
      "extra",
      "tables",
      "fenced_code",
      "sane_lists",
      "toc",
    ],
    output_format="html5",
  )
  sectioned_body = _sectionize_html(body)

  safe_heading = html.escape(heading or "Root Cause Analysis")
  safe_subtitle = html.escape(subtitle or "Auto-generated detailed analysis report")
  safe_platform = html.escape(platform)
  safe_component = html.escape(component)
  safe_status = html.escape(status)
  safe_owner = html.escape(owner)
  safe_analyzed_on = html.escape(analyzed_on)

  return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{doc_title}</title>
  <style>
    :root {{
      --bg: #f8f9fa;
      --card-bg: #ffffff;
      --border: #dee2e6;
      --text: #212529;
      --text-muted: #6c757d;
      --primary: #0d6efd;
      --success: #198754;
      --warning: #ffc107;
      --danger: #dc3545;
      --info: #0dcaf0;
      --conf-high: #198754;
      --conf-med: #fd7e14;
      --conf-low: #dc3545;
      --code-bg: #1e1e2e;
      --code-text: #cdd6f4;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 24px;
      line-height: 1.5;
    }}

    .wrap {{
      max-width: 1280px;
      margin: 0 auto;
    }}

    .report-header {{
      background: var(--card-bg);
      border-radius: 12px;
      padding: 28px 32px;
      margin-bottom: 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
      border-top: 4px solid var(--primary);
    }}

    .report-header h1 {{ font-size: 1.55em; margin-bottom: 4px; }}
    .report-header .subtitle {{ font-size: 1em; color: var(--text-muted); margin-bottom: 12px; }}
    .report-header .meta {{ color: var(--text-muted); font-size: 0.88em; margin-bottom: 16px; }}

    .header-badges {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 0.78em;
      font-weight: 700;
      white-space: nowrap;
    }}
    .badge-found {{ background: #d4edda; color: #155724; }}
    .badge-status {{ background: #e9ecef; color: #495057; }}
    .pill {{
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 0.85em;
      font-weight: 600;
      background: #e9ecef;
      color: #495057;
      white-space: nowrap;
    }}

    .metrics-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}

    .metric-card {{
      background: var(--card-bg);
      border-radius: 8px;
      padding: 20px;
      text-align: center;
      box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }}

    .metric-card .value {{ font-size: 2em; font-weight: 700; color: var(--primary); }}
    .metric-card .value.conf-high {{ color: var(--conf-high); }}
    .metric-card .value.conf-med {{ color: var(--conf-med); }}
    .metric-card .value.conf-low {{ color: var(--conf-low); }}
    .metric-card .label {{ font-size: 0.82em; color: var(--text-muted); margin-top: 4px; }}

    .report-card {{
      background: var(--card-bg);
      border-radius: 12px;
      padding: 24px 28px;
      margin-bottom: 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
      border-left: 4px solid transparent;
    }}

    .card-summary {{ border-left-color: var(--info); }}
    .card-rootcause {{ border-left-color: var(--success); }}
    .card-actions {{ border-left-color: var(--warning); }}
    .card-appendix {{ border-left-color: #6c757d; }}
    .card-default {{ border-left-color: #ced4da; }}

    .section-head h2 {{
      font-size: 1em;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.6px;
      margin-bottom: 12px;
      padding-bottom: 6px;
      border-bottom: 2px solid var(--border);
    }}

    .section-body h3, .section-body h4 {{ margin: 14px 0 8px; color: #0a2540; }}
    .section-body p, .section-body li {{ font-size: 0.92rem; line-height: 1.6; }}
    .section-body ul, .section-body ol {{ padding-left: 20px; }}

    a {{ color: var(--primary); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    code {{
      background: #1e1e1e;
      color: #9cdcfe;
      border-radius: 3px;
      padding: 2px 6px;
      font-size: 0.85em;
    }}

    pre {{
      background: var(--code-bg);
      color: var(--code-text);
      border-radius: 6px;
      padding: 14px;
      font-size: 0.82em;
      white-space: pre-wrap;
      overflow-x: auto;
      max-height: 340px;
    }}

    pre code {{
      background: transparent;
      border: 0;
      color: inherit;
      padding: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86em;
      margin: 12px 0;
    }}

    th, td {{
      border: 1px solid var(--border);
      padding: 10px 14px;
      text-align: left;
      vertical-align: top;
    }}

    th {{
      background: #343a40;
      color: #fff;
      font-weight: 700;
      white-space: nowrap;
    }}

    blockquote {{
      border-left: 4px solid #f59e0b;
      margin: 10px 0;
      padding: 10px 14px;
      color: #92400e;
      background: #fff8e1;
      border-radius: 0 6px 6px 0;
    }}

    details {{
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      background: #f1f3f5;
    }}

    details > summary {{
      cursor: pointer;
      font-weight: 600;
      color: #343a40;
    }}

    footer {{
      text-align: center;
      color: var(--text-muted);
      font-size: 0.8em;
      margin-top: 24px;
      padding: 16px;
    }}

    @media (max-width: 768px) {{
      .metrics-row {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <header class=\"report-header\">
      <h1>{safe_heading}</h1>
      <div class=\"subtitle\">{safe_subtitle}</div>
      <div class=\"meta\">
        Component: <strong>{safe_component}</strong> &nbsp;|&nbsp;
        Platform: {safe_platform} &nbsp;|&nbsp;
        Status/Priority: <strong>{safe_status}</strong> &nbsp;|&nbsp;
        Owner: <strong>{safe_owner}</strong> &nbsp;|&nbsp;
        Generated: {safe_analyzed_on}
      </div>
      <div class=\"header-badges\">
        <span class=\"badge badge-found\">Detailed RCA</span>
        <span class=\"badge badge-status\">Auto-staged analysis</span>
        <span class=\"pill\">Richer BugScout-style output</span>
      </div>
    </header>

    <section class=\"metrics-row\">
      <article class=\"metric-card\"><div class=\"value\">{attachments}</div><div class=\"label\">Attachments Analyzed</div></article>
      <article class=\"metric-card\"><div class=\"value\">{comments}</div><div class=\"label\">Comments Parsed</div></article>
      <article class=\"metric-card\"><div class=\"value\">{lines_scanned:,}</div><div class=\"label\">Log Lines Scanned</div></article>
      <article class=\"metric-card\"><div class=\"value {conf_class}\">{confidence}%</div><div class=\"label\">Findings Confidence</div></article>
    </section>

    {sectioned_body}
    <footer>Generated by {html.escape(APP_NAME)}</footer>
  </main>
</body>
</html>
"""


# ======================================================================
# Structured, phase-based renderer (Live-Debug style)
# ======================================================================

_STRUCT_CSS = """
  :root {
    --bg:#f8f9fa; --card-bg:#fff; --border:#dee2e6; --text:#212529; --text-muted:#6c757d;
    --primary:#0d6efd; --success:#198754; --warning:#ffc107; --danger:#dc3545; --info:#0dcaf0;
    --conf-high:#198754; --conf-med:#fd7e14; --conf-low:#dc3545;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); padding:24px; line-height:1.5; }
  .wrap { max-width:1180px; margin:0 auto; }
  .report-header { background:var(--card-bg); border-radius:12px; padding:28px 32px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); border-top:4px solid var(--primary); }
  .report-header h1 { font-size:1.55em; margin-bottom:4px; }
  .report-header h1 a { color:inherit; text-decoration:none; }
  .report-header h1 a:hover { color:var(--primary); }
  .report-header .subtitle { font-size:1em; color:var(--text-muted); margin-bottom:12px; }
  .report-header .meta { color:var(--text-muted); font-size:0.88em; margin-bottom:16px; }
  .header-badges { display:flex; gap:8px; flex-wrap:wrap; }
  .pill { padding:6px 16px; border-radius:20px; font-size:0.85em; font-weight:600; background:#e9ecef; color:#495057; white-space:nowrap; }
  .pill-brand { background:#e7f0ff; color:#0d6efd; }
  .badge { display:inline-block; padding:3px 10px; border-radius:12px; font-size:0.78em; font-weight:700; white-space:nowrap; }
  .badge-found { background:#d4edda; color:#155724; }
  .badge-likely { background:#fff3cd; color:#856404; }
  .badge-open { background:#f8d7da; color:#842029; }
  .badge-manual { background:#e9ecef; color:#495057; }
  .metrics-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:24px; }
  .metric-card { background:var(--card-bg); border-radius:8px; padding:20px; text-align:center; box-shadow:0 1px 4px rgba(0,0,0,0.05); }
  .metric-card .value { font-size:2em; font-weight:700; color:var(--primary); }
  .metric-card .value.conf-high { color:var(--conf-high); } .metric-card .value.conf-med { color:var(--conf-med); } .metric-card .value.conf-low { color:var(--conf-low); }
  .metric-card .label { font-size:0.82em; color:var(--text-muted); margin-top:4px; }
  .section-title { font-size:1em; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.6px; margin-bottom:12px; padding-bottom:6px; border-bottom:2px solid var(--border); }
  .card { background:var(--card-bg); border-radius:12px; padding:24px 28px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }
  table.kv, table.hyp-table, table.related-table, table.mca-table { width:100%; border-collapse:collapse; font-size:0.86em; margin:6px 0; }
  table.kv td { padding:8px 12px; border-bottom:1px solid var(--border); vertical-align:top; }
  table.kv td:first-child { width:210px; color:var(--text-muted); font-weight:600; }
  .hyp-table th, .related-table th { background:#343a40; color:#fff; padding:9px 12px; text-align:left; }
  .hyp-table td, .related-table td { padding:9px 12px; border-bottom:1px solid var(--border); vertical-align:top; }
  .sev-fatal { color:var(--danger); font-weight:700; } .sev-high { color:#fd7e14; font-weight:700; } .sev-medium { color:#b8860b; font-weight:700; } .sev-info { color:var(--text-muted); }
  .rc-box { background:#d4edda; border-radius:10px; padding:18px 22px; margin-bottom:24px; border-left:5px solid var(--success); }
  .rc-box.open { background:#fff3cd; border-left-color:var(--warning); }
  .rc-box .rc-badge { display:inline-block; background:#198754; color:#fff; font-size:0.75em; font-weight:700; padding:3px 12px; border-radius:12px; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px; }
  .rc-box.open .rc-badge { background:#b8860b; }
  .rc-box p { font-size:0.95em; line-height:1.6; }
  .iter-panel { border-bottom:1px solid var(--border); padding:16px 0; }
  .iter-panel:last-child { border-bottom:none; }
  .iter-num { display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; border-radius:50%; background:#343a40; color:#fff; font-weight:700; font-size:0.85em; margin-right:10px; }
  .iter-grid { display:grid; grid-template-columns:1fr 2fr; gap:16px; margin-top:12px; }
  .iter-section h4 { font-size:0.78em; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px; }
  .iter-section p { font-size:0.9em; line-height:1.6; }
  .iter-section code, .rc-section code, td code { background:#1e1e1e; color:#9cdcfe; padding:2px 6px; border-radius:3px; font-size:0.85em; }
  .log-box { background:#1e1e2e; color:#cdd6f4; border-radius:6px; padding:12px 14px; font-size:0.75rem; font-family:'Cascadia Code',Consolas,monospace; white-space:pre-wrap; overflow:auto; max-height:280px; margin:10px 0 0; }
  .mca-table th { background:#2d2d3f; color:#89b4fa; padding:6px 10px; text-align:left; font-family:Consolas,monospace; }
  .mca-table td { padding:5px 10px; border-bottom:1px solid #3a3a4f; background:#1e1e2e; color:#cdd6f4; font-family:Consolas,monospace; }
  .field-set { color:#a6e3a1; font-weight:700; } .field-zero { color:#6c7086; }
  .rootcause-card { border-top:4px solid var(--success); }
  .rootcause-grid { display:grid; grid-template-columns:1fr 1fr; gap:22px; margin-top:12px; }
  .rc-section h4 { font-size:0.82em; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; margin:0 0 6px; }
  .rc-section h4.mt { margin-top:14px; }
  .rc-section p, .rc-section li { font-size:0.9em; line-height:1.6; }
  .rc-section ul, .rc-section ol { padding-left:18px; }
  .ev-chain { margin:8px 0; }
  .ev-step { display:flex; gap:12px; margin-bottom:10px; align-items:flex-start; }
  .ev-num { background:#0d6efd; color:#fff; border-radius:50%; width:24px; height:24px; display:flex; align-items:center; justify-content:center; font-size:0.72rem; font-weight:700; flex-shrink:0; margin-top:2px; }
  .ev-body { flex:1; background:#f8f9fa; border:1px solid var(--border); border-radius:6px; padding:8px 12px; font-size:0.85rem; }
  .evidence-have li { margin-bottom:5px; font-size:0.9em; }
  .collect-list > li { margin-bottom:10px; font-size:0.9em; }
  .collect-list code { display:inline-block; margin-top:3px; }
  a { color:var(--primary); }
  footer { text-align:center; color:var(--text-muted); font-size:0.8em; margin-top:8px; padding:16px; }
  @media (max-width:768px) { .iter-grid,.rootcause-grid { grid-template-columns:1fr; } .metrics-row { grid-template-columns:1fr 1fr; } }
"""


def _e(v: Any) -> str:
  return html.escape(str(v if v is not None else ""))


def _confidence_from_result(result: Dict[str, Any]) -> int:
  return _extract_confidence(result.get("report_markdown", "") or "")


def _primary_root_cause(result: Dict[str, Any]) -> tuple[str, str, bool]:
  """Return (badge_label, text, is_open) for the root-cause summary box."""
  cf = result.get("comment_findings") or {}
  decoded = (result.get("log_findings") or {}).get("decoded") or {}
  target = result.get("target") or {}
  if cf.get("root_cause"):
    return ("Root cause — converged in comment thread", str(cf["root_cause"]), False)
  # Demote an incidental MCA when the ticket is dispositioned / functional-config.
  try:
    from .analyzer import _mca_is_incidental, _demoted_primary_line
    demoted, why = _mca_is_incidental(target, result.get("log_findings"), cf)
  except Exception:
    demoted, why = (False, "")
  if demoted:
    status = str(target.get("status") or "").strip().lower()
    badge = f"Dispositioned ({status})" if status else "Functional / config observation"
    return (badge, _demoted_primary_line(target, cf), True)
  mca = decoded.get("mca") or {}
  if mca and mca.get("uncorrected"):
    ev = (decoded.get("evidence") or {}).get("mc_status") or {}
    extra = ""
    if ev.get("decode"):
      extra = (f" MC_STATUS bank {ev.get('bank')} MCACOD {ev.get('mcacod')} "
               f"MSCOD {ev.get('mscod')} = {ev.get('decode')}.")
    axon = (target.get("axon_svtools_signatures") or [])
    axon_txt = f" Corroborated by Axon SVTools signature `{axon[0]}`." if axon else ""
    return ("Uncorrected machine-check (MCA)",
            f"An uncorrected machine-check was decoded: {mca.get('headline') or 'see decode'}.{extra}{axon_txt}",
            True)
  hyps = decoded.get("hypotheses") or []
  if hyps:
    return ("Leading hypothesis", str(hyps[0].get("text", "")), True)
  return ("Investigation in progress",
          "Root cause not yet determined from the current evidence — see the recommended "
          "data to collect below.", True)


def _boot_stage_rows(decoded: Dict[str, Any]) -> str:
  boot = decoded.get("boot_flow") or {}
  stages = boot.get("stages") or []
  if not stages:
    return ""
  last_key = (boot.get("last_reached") or {}).get("key")
  fail_key = (boot.get("failing_stage") or {}).get("key")
  rows = []
  for s in stages:
    if s.get("reached"):
      mark = "✅ last reached" if s.get("key") == last_key else "✅ reached"
    elif s.get("key") == fail_key:
      mark = "❌ did not start"
    else:
      mark = "— not reached"
    ev = _e((s.get("evidence") or "")[:60]) or "—"
    rows.append(f"<tr><td>{_e(s.get('label'))}</td><td>{mark}</td><td><code>{ev}</code></td></tr>")
  markers = boot.get("failure_markers") or []
  cap = (f'<p style="margin-top:10px;font-size:0.85em"><strong>Failure markers:</strong> '
         f'{_e(", ".join(markers))}</p>') if markers else ""
  return (
    '<div class="card"><div class="section-title">Boot / Stage Progress (Golden Flow)</div>'
    '<table class="hyp-table"><thead><tr><th>Stage</th><th>Status</th><th>Evidence</th></tr></thead>'
    f'<tbody>{"".join(rows)}</tbody></table>{cap}</div>'
  )


def _hypotheses_table(decoded: Dict[str, Any]) -> str:
  hyps = decoded.get("hypotheses") or []
  if not hyps:
    return ""
  _assess = {"fatal": "Primary (fatal)", "high": "Contributing",
             "medium": "Secondary", "info": "Informational"}
  rows = []
  for i, h in enumerate(hyps, 1):
    sev = str(h.get("severity", "info"))
    rows.append(
      f'<tr><td>{i}</td><td>{_e(h.get("text"))}</td>'
      f'<td class="sev-{_e(sev)}">{_e(sev.upper())}</td>'
      f'<td>{_e(_assess.get(sev, "—"))}</td></tr>')
  return (
    '<div class="card"><div class="section-title">Ranked Hypotheses (decoded evidence synthesis)</div>'
    '<table class="hyp-table"><thead><tr><th>#</th><th>Hypothesis</th><th>Severity</th>'
    '<th>Assessment</th></tr></thead>'
    f'<tbody>{"".join(rows)}</tbody></table></div>'
  )


def _evidence_panels(result: Dict[str, Any]) -> str:
  lf = result.get("log_findings") or {}
  decoded = lf.get("decoded") or {}
  target = result.get("target") or {}
  panels: List[str] = []

  def panel(n, title, source, finding, extra_html=""):
    return (
      f'<div class="iter-panel"><span class="iter-num">{n}</span><strong>{_e(title)}</strong>'
      '<div class="iter-grid">'
      f'<div class="iter-section"><h4>Source</h4><p>{source}</p></div>'
      f'<div class="iter-section"><h4>Finding</h4><p>{finding}</p></div>'
      f'</div>{extra_html}</div>'
    )

  n = 0
  # 1) IERR / UBOX table
  for row in (decoded.get("ierr_table") or [])[:4]:
    n += 1
    src = row.get("source_unit")
    src_html = f"<code>{_e(src)}</code>" if src and str(src).lower() != "none" else "<em>not captured</em>"
    addr = f" @ <code>{_e(row.get('address'))}</code>" if row.get("address") else ""
    panels.append(panel(
      n, f"PythonSV UBOX — Socket {row.get('socket')} {row.get('type')} {row.get('priority')}",
      "PythonSV UBOX error table (<code>ierr/mcerr</code> first/second capture)",
      f"Socket {_e(row.get('socket'))} <strong>{_e(row.get('type'))}</strong> "
      f"{_e(row.get('priority'))} originated from {src_html}{addr}."))

  # 2) MCA decode + status table
  mca = decoded.get("mca") or {}
  ev = decoded.get("evidence") or {}
  mcs = ev.get("mc_status") or {}
  if mca or mcs.get("decode"):
    n += 1
    flags = ev.get("status_flags") or {}
    frows = "".join(
      f'<tr><td>{_e(k)}</td><td class="{("field-set" if v else "field-zero")}">'
      f'{("SET" if v else "0")}</td></tr>' for k, v in flags.items()) if flags else ""
    ftable = (f'<table class="mca-table"><thead><tr><th>MCi_STATUS flag</th><th>Value</th>'
              f'</tr></thead><tbody>{frows}</tbody></table>') if frows else ""
    detail = " ".join(filter(None, [
      f"bank {mcs.get('bank')}" if mcs.get("bank") else "",
      f"({mcs.get('bank_unit')})" if mcs.get("bank_unit") else "",
      f"MCACOD {mcs.get('mcacod')}" if mcs.get("mcacod") else "",
      f"MSCOD {mcs.get('mscod')}" if mcs.get("mscod") else "",
      f"= {mcs.get('decode')}" if mcs.get("decode") else (
        f"= {mca.get('headline')}" if mca.get("headline") else ""),
    ]))
    panels.append(panel(
      n, "Machine-Check (MCA) decode",
      "Bundled Intel MCA decoder DB over the attached PythonSV / SOL log",
      f"{'UNCORRECTED' if mca.get('uncorrected') else 'corrected'} machine-check — "
      f"{_e(detail or mca.get('headline') or 'see decode')}"
      f"{' (' + str(mca.get('count')) + ' status values)' if mca.get('count') else ''}.",
      ftable))

  # 3) Curated evidence lines from the log
  for e in (lf.get("evidence") or [])[:2]:
    lines = e.get("lines") or []
    if not lines:
      continue
    n += 1
    logbox = '<div class="log-box">' + _e("\n".join(lines[:6])) + "</div>"
    panels.append(panel(
      n, str(e.get("category", "Log evidence")),
      "Attached serial / PythonSV / BMC log (smoking-gun lines)",
      f"{len(lines)} matching line(s) for <em>{_e(e.get('category'))}</em>.", logbox))

  # 4) Axon SVTools signatures
  axon = target.get("axon_svtools_signatures") or []
  if axon:
    n += 1
    sig_html = "".join(f"<li><code>{_e(s)}</code></li>" for s in axon[:6])
    panels.append(panel(
      n, "Axon SVTools failure signatures",
      "Linked Axon recording (SVTools signature extraction)",
      f"{len(axon)} hardware failure signature(s) matched:"
      f'<ul style="margin:6px 0 0 16px">{sig_html}</ul>'))

  # 5) Last POST checkpoint
  post = decoded.get("post") or {}
  if post.get("codes"):
    n += 1
    last = post["codes"][-1]
    panels.append(panel(
      n, "Last POST / progress checkpoint",
      "BIOS POST-code decoder over checkpoint lines",
      f"Last checkpoint <code>{_e(last.get('code'))}</code> — "
      f"{_e(last.get('description') or last.get('macro') or '')}."))

  if not panels:
    return ""
  return ('<div class="card"><div class="section-title">Evidence From Attached Logs</div>'
          + "".join(panels) + "</div>")


def _evidence_chain_html(result: Dict[str, Any]) -> List[str]:
  decoded = (result.get("log_findings") or {}).get("decoded") or {}
  target = result.get("target") or {}
  steps: List[str] = []
  boot = decoded.get("boot_flow") or {}
  if boot.get("reached_os"):
    steps.append("System booted to OS — this is a runtime / post-boot failure, not a boot hang.")
  elif boot.get("failing_stage"):
    steps.append(f"Boot did not progress past {(boot.get('last_reached') or {}).get('label','?')} "
                 f"(next expected: {boot['failing_stage'].get('label','?')}).")
  ierr = decoded.get("ierr_table") or []
  if ierr:
    r = ierr[0]
    steps.append(f"First {r.get('type')} on Socket {r.get('socket')} from "
                 f"{r.get('source_unit')}" + (f" @ {r.get('address')}" if r.get('address') else "") + ".")
  mca = decoded.get("mca") or {}
  if mca:
    steps.append(f"Decoded {'uncorrected' if mca.get('uncorrected') else 'corrected'} "
                 f"machine-check: {mca.get('headline') or 'see decode'}.")
  mcs = (decoded.get("evidence") or {}).get("mc_status") or {}
  if mcs.get("decode"):
    steps.append(f"MC_STATUS bank {mcs.get('bank')} MCACOD {mcs.get('mcacod')} "
                 f"MSCOD {mcs.get('mscod')} = {mcs.get('decode')}.")
  axon = target.get("axon_svtools_signatures") or []
  if axon:
    steps.append(f"Axon SVTools signature match: {axon[0]}.")
  return steps


def _recommended_fix(result: Dict[str, Any]) -> List[str]:
  decoded = (result.get("log_findings") or {}).get("decoded") or {}
  cf = result.get("comment_findings") or {}
  out: List[str] = []
  if cf.get("workaround"):
    out.append(f"Validate the workaround identified in the ticket: {cf['workaround']}")
  mca = decoded.get("mca") or {}
  if mca.get("action"):
    out.append(str(mca["action"]))
  boot = decoded.get("boot_flow") or {}
  if boot.get("failing_stage"):
    out.append(f"Inspect the BIOS/firmware path entering {boot['failing_stage'].get('label')} "
               "(right after the last good checkpoint).")
  out.append("Confirm the decoded root cause on hardware; capture the MCA bank + RIP.")
  return list(dict.fromkeys([x for x in out if x and x.strip()]))


# Verified Intel spec URLs (sourced from the reference live_debug_report; do not fabricate more).
_CURATED_SPECS = [
  ("BIOS / firmware / boot-hang", "Birchstream BIOS FAS",
   "https://docs.intel.com/documents/arch_datacenter/gnr_family/system%20firmware/bhs_fas/birchstream_bios_fas.html"),
  ("UPI / coherency", "GNR SP/AP IO-Die Overview — UPI topology / link-failure recovery",
   "https://docs.intel.com/documents/arch_datacenter/gnr_family/granite%20rapids%20-%20sp%20and%20ap/io_die_overview.html"),
  ("RAS / MCA", "Xeon 2025/2026 IP-Disable Feature HAS — SSVDM / cold-reset IP-disable behavior",
   "https://docs.intel.com/documents/arch_datacenter/rcf/reset/xeon_2025_2026/feature%20has/xeon_25_26_ip_disable_feature_has.html"),
]


def _spec_references_html(result: Dict[str, Any]) -> str:
  """Attach curated Intel spec links for the failing domain(s) + any doc URLs
  already present in the ticket. Never fabricates URLs."""
  lf = result.get("log_findings") or {}
  target = result.get("target") or {}
  domains = {str(s.get("domain", "")) for s in (lf.get("signatures") or [])}
  links: List[tuple] = [(label, url) for dom, label, url in _CURATED_SPECS if dom in domains]

  # Real doc/wiki URLs mentioned in the ticket itself.
  text = (target.get("full_text") or "") + " " + (target.get("description") or "")
  seen = {u for _, u in links}
  for u in re.findall(r"https?://[^\s)\"'<>\]]+", text):
    if (("docs.intel.com" in u or "intel.com/wiki" in u or "goto.intel.com" in u)
        and u not in seen):
      seen.add(u)
      links.append((u, u))
  if not links:
    return ""
  items = "".join(f'<li><a href="{_e(url)}" target="_blank">{_e(label)}</a></li>' for label, url in links[:8])
  return ('<div class="rc-section" style="grid-column:1 / -1"><h4 class="mt">Spec References</h4>'
          f'<ul>{items}</ul></div>')


def _related_hsds_html(result: Dict[str, Any]) -> str:
  rows: List[str] = []
  for s in (result.get("similar") or [])[:6]:
    sid = _e(s.get("id") or s.get("hsd_id") or "")
    title = _e(s.get("title") or s.get("summary") or "")
    rows.append(f'<tr><td>{sid}</td><td>{title}</td><td>Similar sighting (HSDES search)</td></tr>')
  for rid in (result.get("reference_hsds_used") or []):
    rows.append(f'<tr><td>{_e(rid)}</td><td>—</td><td>Clone / parent reference (auto-enrichment)</td></tr>')
  tr = result.get("transferred_sync") or {}
  if tr.get("target_id"):
    rows.append(f'<tr><td>{_e(tr.get("target_id"))}</td><td>{_e(tr.get("title") or "")}</td>'
                f'<td>Transferred sub-team ticket</td></tr>')
  if not rows:
    return ""
  return ('<div class="card"><div class="section-title">Related HSDs</div>'
          '<table class="related-table"><thead><tr><th>HSD ID</th><th>Title</th>'
          '<th>Relevance</th></tr></thead>'
          f'<tbody>{"".join(rows)}</tbody></table></div>')


def _root_cause_evidence_html(result: Dict[str, Any]) -> str:
  try:
    from .analyzer import _audit_root_cause_evidence
  except Exception:
    return ""
  audit = _audit_root_cause_evidence(
    result.get("target") or {}, result.get("log_findings"),
    result.get("kb_recall") or {}, result.get("similar") or [])
  if not audit:
    return ""
  have = [a for a in audit if a.get("present")]
  missing = [a for a in audit if not a.get("present")]
  have_html = "".join(
    f"<li><strong>{_e(a['label'])}:</strong> {_e(a.get('detail') or 'captured')}</li>"
    for a in have)
  miss_items = []
  for a in missing:
    cmds = "".join(f"<li><code>{_e(c)}</code></li>" for c in a.get("commands", []))
    miss_items.append(
      f"<li><strong>{_e(a['label'])}</strong> — {_e(a.get('collect'))}."
      + (f'<ul style="margin:4px 0 0 4px">{cmds}</ul>' if cmds else "") + "</li>")
  parts = [f'<div class="card"><div class="section-title">Root-Cause Evidence '
           f'({len(have)} of {len(audit)} key facts decoded)</div>']
  if have_html:
    parts.append('<div class="rc-section"><h4>Evidence on hand (decoded from logs / Axon)</h4>'
                 f'<ul class="evidence-have">{have_html}</ul></div>')
  if miss_items:
    parts.append('<div class="rc-section"><h4 class="mt">Recommended data to collect to confirm '
                 'the root cause</h4>'
                 f'<ol class="collect-list">{"".join(miss_items)}</ol></div>')
  parts.append("</div>")
  return "".join(parts)


def render_structured_report_html(result: Dict[str, Any],
                                  title: Optional[str] = None,
                                  app_name: str = APP_NAME) -> str:
  """Render the analyze() result dict into a phase-based Live-Debug-style HTML page."""
  target = result.get("target") or {}
  lf = result.get("log_findings") or {}
  decoded = lf.get("decoded") or {}
  hsd_id = str(target.get("id") or "")
  ttitle = str(target.get("title") or "Root Cause Analysis")
  platform = " / ".join(
    p for p in dict.fromkeys([str(result.get("family") or ""), str(target.get("family") or "")])
    if p) or "Unknown"
  component = str(target.get("component") or "")
  status = str(target.get("status") or "")
  priority = str(target.get("priority") or "")
  owner = str(target.get("owner") or "")
  from time import strftime
  generated = strftime("%Y-%m-%d %H:%M")

  confidence = _confidence_from_result(result)
  conf_class = _confidence_class(confidence)
  attachments = len(result.get("attachments") or [])
  fetched = result.get("attachments_fetched", 0) or 0
  lines = lf.get("lines_scanned", 0) or 0
  related = (len(result.get("similar") or []) + len(result.get("reference_hsds_used") or [])
             + (1 if (result.get("transferred_sync") or {}).get("target_id") else 0))

  rc_badge, rc_text, rc_open = _primary_root_cause(result)
  rc_text = rc_text.replace("**", "")  # strip markdown bold for HTML display
  _dispositioned = rc_badge.startswith("Dispositioned") or rc_badge.startswith("Functional")
  if _dispositioned:
    result_badge = f'<span class="badge badge-manual">{_e(rc_badge)}</span>'
  elif confidence >= 75:
    result_badge = '<span class="badge badge-found">✓ Root Cause Found</span>'
  elif confidence >= 40:
    result_badge = '<span class="badge badge-likely">◐ Likely Cause Identified</span>'
  else:
    result_badge = '<span class="badge badge-open">● Investigating</span>'

  hsd_url = f"https://hsdes.intel.com/appstore/article/#/{_e(hsd_id)}" if hsd_id else "#"

  # Session parameters
  attach_rows = "".join(
    f"<li><code>{_e(f)}</code></li>" for f in (result.get("attachment_files") or [])[:12])
  attach_cell = f'<ul style="margin:0 0 0 16px">{attach_rows}</ul>' if attach_rows else "—"
  kv = (
    '<div class="card"><div class="section-title">Session Parameters &amp; Artifacts</div>'
    '<table class="kv"><tbody>'
    f'<tr><td>HSD ID</td><td>{_e(hsd_id)}</td></tr>'
    f'<tr><td>Title</td><td>{_e(ttitle)}</td></tr>'
    f'<tr><td>Platform / Family</td><td>{_e(platform)}</td></tr>'
    f'<tr><td>Status / Priority</td><td>{_e(status) or "—"} / {_e(priority) or "—"}</td></tr>'
    f'<tr><td>Owner</td><td>{_e(owner) or "—"}</td></tr>'
    f'<tr><td>Analyser mode</td><td>Automated (offline log + ticket analysis)</td></tr>'
    f'<tr><td>Attachments processed</td><td>{fetched} of {attachments} scanned{attach_cell if attach_rows else ""}</td></tr>'
    f'<tr><td>Log volume analysed</td><td>{lines:,} lines</td></tr>'
    '</tbody></table></div>'
  )

  # Evidence chain + fix
  chain = _evidence_chain_html(result)
  chain_html = "".join(
    f'<div class="ev-step"><span class="ev-num">{i}</span><div class="ev-body">{_e(c)}</div></div>'
    for i, c in enumerate(chain, 1)) or '<p style="font-size:0.9em">No decoded evidence chain available.</p>'
  fixes = _recommended_fix(result)
  fix_html = "".join(f"<li>{_e(x)}</li>" for x in fixes)
  spec_html = _spec_references_html(result)
  final_rc = (
    '<div class="card rootcause-card"><div class="section-title">Final Root Cause '
    f'(confidence {confidence}%)</div>'
    '<div class="rootcause-grid">'
    '<div class="rc-section"><h4>Evidence Chain</h4>'
    f'<div class="ev-chain">{chain_html}</div></div>'
    '<div class="rc-section"><h4>Recommended Fix / Next Steps</h4>'
    f'<ol>{fix_html}</ol></div>'
    f'{spec_html}'
    '</div></div>'
  )

  meta_bits = " &nbsp;|&nbsp; ".join(filter(None, [
    f"Component: <strong>{_e(component)}</strong>" if component else "",
    f"Platform: {_e(platform)}",
    f"Status/Priority: <strong>{_e(status) or '—'} / {_e(priority) or '—'}</strong>",
    f"Owner: <strong>{_e(owner) or '—'}</strong>",
    f"Generated: {_e(generated)}",
  ]))

  doc_title = _e(title or f"{app_name} — HSD {hsd_id}")
  return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{doc_title}</title>
<style>{_STRUCT_CSS}</style>
</head>
<body>
<main class="wrap">
  <div class="report-header">
    <h1><a href="{hsd_url}" target="_blank">HSD {_e(hsd_id)}</a></h1>
    <div class="subtitle">{_e(ttitle)}</div>
    <div class="meta">{meta_bits}</div>
    <div class="header-badges">
      {result_badge}
      <span class="badge badge-manual">Automated Offline Log Analysis</span>
      <span class="pill pill-brand">{_e(app_name)}</span>
    </div>
  </div>

  <div class="metrics-row">
    <div class="metric-card"><div class="value">{fetched}</div><div class="label">Attachments Analysed</div></div>
    <div class="metric-card"><div class="value {conf_class}">{confidence}%</div><div class="label">Root-Cause Confidence</div></div>
    <div class="metric-card"><div class="value">{lines:,}</div><div class="label">Log Lines Scanned</div></div>
    <div class="metric-card"><div class="value">{related}</div><div class="label">Related HSDs</div></div>
  </div>

  <div class="rc-box {'open' if rc_open else ''}">
    <span class="rc-badge">{_e(rc_badge)}</span>
    <p>{_e(rc_text)}</p>
  </div>

  {kv}
  {_boot_stage_rows(decoded)}
  {_hypotheses_table(decoded)}
  {_evidence_panels(result)}
  {final_rc}
  {_root_cause_evidence_html(result)}
  {_related_hsds_html(result)}

  <footer>Generated by {_e(app_name)} &nbsp;|&nbsp; HSD {_e(hsd_id)} &nbsp;|&nbsp; {_e(generated)}</footer>
</main>
</body>
</html>
"""
