"""FastAPI app: serves the UI and the /api endpoints."""

import os

from fastapi import FastAPI, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from .analyzer import analyze, kb
from .hsdes_client import hsdes
from .llm_client import llm

app = FastAPI(title="Auto HSD Analyser — GNR/SRF/CWF")
_STATIC = os.path.join(os.path.dirname(__file__), "static")


class AnalyzeRequest(BaseModel):
    hsd_id: str
    symptoms: str


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.get("/api/health")
async def health():
    return {
        # True only if a server-side fallback token is configured. Each user
        # normally supplies their own token from the browser instead.
        "server_hsdes_fallback": hsdes.enabled,
        "llm_enabled": llm.enabled,
        "mode": "llm" if llm.enabled else "offline",
        "kb_entries": kb.count(),
    }


@app.post("/api/analyze")
async def api_analyze(
    req: AnalyzeRequest,
    x_hsdes_token: Optional[str] = Header(default=None),
):
    if not req.hsd_id.strip() or not req.symptoms.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Both 'hsd_id' and 'symptoms' are required."},
        )
    # The user's own token arrives per-request via the X-HSDES-Token header and
    # is never stored server-side.
    return await analyze(req.hsd_id.strip(), req.symptoms.strip(),
                         hsdes_token=x_hsdes_token)


@app.get("/api/kb")
async def api_kb():
    return {"count": kb.count(), "entries": kb.all()}


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
