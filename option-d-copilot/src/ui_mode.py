#!/usr/bin/env python3
"""
UI mode launcher for Auto HSD Analyser.

This starts a local web server and provides a simple dashboard to open:
- Latest generated report
- All available report folders
- Management flowchart assets
"""

from __future__ import annotations

import argparse
import html
import os
import socket
import threading
import time
import webbrowser
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _relative_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _latest_report(repo_root: Path) -> Optional[Path]:
    reports = sorted(
        repo_root.glob("output/**/session_report.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


def _all_reports(repo_root: Path) -> list[Path]:
    return sorted(
        repo_root.glob("output/**/session_report.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _find_free_port(host: str, preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, preferred_port))
            return preferred_port
        except OSError:
            s.bind((host, 0))
            return int(s.getsockname()[1])


def _render_dashboard(repo_root: Path, host: str, port: int) -> str:
    latest = _latest_report(repo_root)
    all_reports = _all_reports(repo_root)

    flowchart_html = repo_root / "docs" / "how-it-works-flowchart.html"
    flowchart_png = repo_root / "docs" / "how-it-works-flowchart.png"
    management_overview = repo_root / "docs" / "management-overview.md"
    demo_guide = repo_root / "docs" / "demo-guide.md"

    latest_link = ""
    if latest is not None:
        latest_rel = _relative_posix(latest, repo_root)
        latest_link = (
            f'<a class="primary" href="/{html.escape(latest_rel)}" target="_blank" '
            f'rel="noopener noreferrer">Open latest report</a>'
        )
    else:
        latest_link = '<span class="muted">No reports found yet in output/</span>'

    report_items = []
    for report in all_reports:
        rel = _relative_posix(report, repo_root)
        stamp = datetime.fromtimestamp(report.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        report_items.append(
            "<li>"
            f"<a href=\"/{html.escape(rel)}\" target=\"_blank\" rel=\"noopener noreferrer\">{html.escape(rel)}</a>"
            f" <span class=\"stamp\">({stamp})</span>"
            "</li>"
        )

    if not report_items:
        report_items.append('<li class="muted">No report files found.</li>')

    quick_links = []
    for p in [flowchart_html, flowchart_png, management_overview, demo_guide]:
        if p.exists():
            rel = _relative_posix(p, repo_root)
            quick_links.append(
                "<li>"
                f"<a href=\"/{html.escape(rel)}\" target=\"_blank\" rel=\"noopener noreferrer\">{html.escape(rel)}</a>"
                "</li>"
            )

    if not quick_links:
        quick_links.append('<li class="muted">No docs links found.</li>')

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Auto HSD Analyser - UI Mode</title>
  <style>
    :root {{
      --bg: #f7f4ef;
      --card: #fffdfa;
      --text: #1f2933;
      --muted: #5f6c7b;
      --brand: #0b7285;
      --brand-2: #f08c00;
      --line: #d8dde3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 20% -10%, #ffe8cc 0, rgba(255,232,204,0) 35%),
        radial-gradient(circle at 100% 0%, #d0ebff 0, rgba(208,235,255,0) 32%),
        var(--bg);
      min-height: 100vh;
    }}
    .wrap {{
      max-width: 1000px;
      margin: 0 auto;
      padding: 28px 18px 44px;
    }}
    .hero {{
      background: linear-gradient(135deg, #ffffff 0%, #fff7ed 100%);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 24px;
      box-shadow: 0 8px 30px rgba(20, 20, 20, 0.06);
    }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    p {{ margin: 8px 0; line-height: 1.45; }}
    .muted {{ color: var(--muted); }}
    .row {{
      margin-top: 22px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px;
    }}
    .card h2 {{ margin: 0 0 12px; font-size: 18px; }}
    ul {{ margin: 8px 0 0 18px; padding: 0; }}
    li {{ margin: 8px 0; }}
    a {{ color: var(--brand); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .primary {{
      display: inline-block;
      background: linear-gradient(120deg, var(--brand) 0%, #1098ad 100%);
      color: white;
      padding: 10px 14px;
      border-radius: 10px;
      font-weight: 600;
      text-decoration: none;
      margin: 6px 0 4px;
    }}
    .primary:hover {{ text-decoration: none; filter: brightness(0.95); }}
    .stamp {{ color: var(--muted); font-size: 12px; }}
    .meta {{
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px dashed var(--line);
      font-size: 13px;
      color: var(--muted);
    }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      background: #fff3bf;
      border: 1px solid #ffd43b;
      color: #5c3d00;
      font-size: 12px;
      margin-left: 8px;
      vertical-align: middle;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Auto HSD Analyser <span class="badge">UI Mode</span></h1>
      <p>Local dashboard for opening generated ticket reports and demo assets.</p>
      <p class="muted">Server: http://{html.escape(host)}:{port}</p>
      {latest_link}
      <div class="meta">Tip: Keep this process running while presenting. Press Ctrl+C in terminal to stop.</div>
    </section>

    <section class="row">
      <article class="card">
        <h2>Generated Reports</h2>
        <ul>
          {''.join(report_items)}
        </ul>
      </article>

      <article class="card">
        <h2>Demo / Management Assets</h2>
        <ul>
          {''.join(quick_links)}
        </ul>
      </article>
    </section>
  </div>
</body>
</html>
"""


class _RepoHandler(SimpleHTTPRequestHandler):
    repo_root: Path
    dashboard_html: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.repo_root), **kwargs)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.dashboard_html.encode("utf-8"))
            return
        return super().do_GET()

    def log_message(self, format: str, *args) -> None:
        # Keep logs concise in interactive demos.
        print("[ui] " + format % args)


def run_ui(host: str, port: int, open_browser: bool = True) -> None:
    repo_root = _repo_root()
    chosen_port = _find_free_port(host, port)

    handler_cls = type("RepoHandler", (_RepoHandler,), {})
    handler_cls.repo_root = repo_root
    handler_cls.dashboard_html = _render_dashboard(repo_root, host, chosen_port)

    server = HTTPServer((host, chosen_port), handler_cls)
    url = f"http://{host}:{chosen_port}/"

    print(f"[ui] Serving repository: {repo_root}")
    print(f"[ui] Dashboard URL: {url}")

    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ui] Shutting down UI mode...")
    finally:
        server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch Auto HSD Analyser UI mode")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Preferred port (default: 8765)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start server without opening browser automatically",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_ui(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
