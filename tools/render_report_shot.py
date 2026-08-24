"""Render the top of a sample HTML report to a slide-quality PNG."""
import glob
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "presentation", "report_screenshot.png")

report = sys.argv[1] if len(sys.argv) > 1 else sorted(
    glob.glob(os.path.join(HERE, "output", "hsd_16031066261_*.html")))[-1]
url = "file:///" + report.replace("\\", "/").replace(" ", "%20")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1480, "height": 1180}, device_scale_factor=2)
    pg.goto(url, wait_until="networkidle")
    pg.screenshot(path=OUT, clip={"x": 0, "y": 0, "width": 1480, "height": 1180})
    b.close()
print("Report screenshot:", OUT)
