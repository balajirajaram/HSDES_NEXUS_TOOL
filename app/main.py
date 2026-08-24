"""FastAPI app: serves the UI and the /api endpoints.

Authentication: a simple **Intel username + password login** at launch. Credentials
are used to authenticate to HSDES (HTTP Basic) and are held ONLY in a server-side,
in-memory session (keyed by a random session id in a signed cookie) — never written
to disk and never placed in the cookie itself. On a domain-joined Intel machine you
can instead set HSDES_AUTH_MODE=auto to use Kerberos SSO with no prompt at all.

SECURITY NOTE: prefer HSDES_AUTH_MODE=auto (Kerberos) or a personal API key over
typing your domain password. Always serve over HTTPS in any shared deployment.
"""

import os
import secrets
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .analyzer import analyze, kb
from .batch_learn import batch_learn
from .bugscout_bridge import (
    bugscout_finalize_batch,
    bugscout_prepare_batch,
    bugscout_render_live_debug_report,
    bugscout_render_report,
    cache_log_index,
    cache_log_search,
    feature_status,
    handbook_search,
    list_bugscout_runs,
    list_cached_logs,
    parse_crashdump_file,
    start_live_debug_session,
)
from .config import config
from .hsdes_client import HSDESClient
from .llm_client import llm
from .report_html import APP_NAME, render_report_html, render_structured_report_html

app = FastAPI(title="HSDES NEXUS")
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)


@app.middleware("http")
async def _no_cache(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp

_STATIC = os.path.join(os.path.dirname(__file__), "static")
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


def _save_report(hsd_id: str, markdown: str, result: Optional[Dict] = None) -> tuple[str, str]:
    """Persist every analysis to output/hsd_<id>_<timestamp>.md and .html."""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    stem = f"hsd_{hsd_id}_{time.strftime('%Y%m%d_%H%M%S')}"
    md_path = os.path.join(_OUTPUT_DIR, f"{stem}.md")
    html_path = os.path.join(_OUTPUT_DIR, f"{stem}.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    title = f"{APP_NAME} — HSD {hsd_id}"
    if result:
        html_doc = render_structured_report_html(result, title=title)
    else:
        html_doc = render_report_html(markdown, title=title)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return md_path, html_path

# Server-side credential store: session_id -> {"username","password"}.
# In-memory only; cleared on logout and on process restart.
_SESSIONS: Dict[str, Dict[str, str]] = {}


class AnalyzeRequest(BaseModel):
    hsd_id: str
    symptoms: str
    log_text: Optional[str] = None
    fetch_attachments: bool = True


class LoginRequest(BaseModel):
    username: str
    password: str


class BatchLearnRequest(BaseModel):
    query_id: Optional[str] = None
    product: Optional[str] = None
    hsd_ids: Optional[list] = None
    limit: int = 100


class CrashdumpRequest(BaseModel):
    input_path: str
    output_dir: Optional[str] = None


class HandbookSearchRequest(BaseModel):
    query: str
    top_k: int = 4


class LogIndexRequest(BaseModel):
    file_path: str


class LogSearchRequest(BaseModel):
    file_path: str
    keywords: List[str]
    lines: int = 60
    section: Optional[str] = None


class LiveDebugInitRequest(BaseModel):
    hsd_id: str
    execution_mode: str = "manual"
    server: str = ""
    ssh_user: str = ""
    max_iterations: int = 10
    initial_logs_json: Optional[str] = None


class BugScoutPrepareRequest(BaseModel):
    input_csv: str


class BugScoutFinalizeRequest(BaseModel):
    responses_jsonl: str
    output_dir: Optional[str] = None


class BugScoutReportRequest(BaseModel):
    input_csv: str
    output_dir: Optional[str] = None


class LiveDebugReportRequest(BaseModel):
    session_id: str


def _creds(request: Request) -> Optional[Dict[str, str]]:
    sid = request.session.get("sid")
    return _SESSIONS.get(sid) if sid else None


def _kerberos() -> bool:
    return config.HSDES_AUTH_MODE.lower() in ("auto", "kerberos")


@app.get("/")
async def index():
    return FileResponse(
        os.path.join(_STATIC, "index.html"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/api/health")
async def health():
    return {
        "auth_mode": config.HSDES_AUTH_MODE,
        "kerberos_auto": _kerberos(),
        "llm_enabled": llm.enabled,
        "mode": "llm" if llm.enabled else "offline",
        "kb_entries": kb.count(),
    }


@app.get("/api/me")
async def me(request: Request):
    creds = _creds(request)
    if creds:
        return {"authenticated": True, "username": creds.get("username", "")}
    if _kerberos():
        return {"authenticated": True, "username": "(Kerberos SSO)"}
    return {"authenticated": False}


@app.post("/api/login")
async def login(request: Request, body: LoginRequest):
    if not body.username.strip() or not body.password:
        return JSONResponse(status_code=400,
                            content={"error": "Username and password required."})
    # Verify credentials with a lightweight HSDES call before accepting.
    client = HSDESClient(username=body.username, password=body.password)
    probe = await client.get_article("1")
    if probe and isinstance(probe, dict) and "401" in str(probe.get("error", "")):
        return JSONResponse(status_code=401,
                            content={"error": "Invalid Intel username or password."})
    sid = secrets.token_urlsafe(24)
    _SESSIONS[sid] = {"username": body.username.strip(), "password": body.password}
    request.session["sid"] = sid
    return {"authenticated": True, "username": body.username.strip()}


@app.post("/api/logout")
async def logout(request: Request):
    sid = request.session.pop("sid", None)
    if sid:
        _SESSIONS.pop(sid, None)
    return {"authenticated": False}


@app.post("/api/analyze")
async def api_analyze(request: Request, req: AnalyzeRequest):
    if not req.hsd_id.strip() or not req.symptoms.strip():
        return JSONResponse(status_code=400,
                            content={"error": "Both 'hsd_id' and 'symptoms' are required."})
    creds = _creds(request)
    if not creds and not _kerberos():
        return JSONResponse(status_code=401, content={"error": "Please sign in first."})
    result = await analyze(
        req.hsd_id.strip(), req.symptoms.strip(),
        username=(creds or {}).get("username"),
        password=(creds or {}).get("password"),
        log_text=req.log_text,
        fetch_attachments=req.fetch_attachments,
    )
    if result.get("report_markdown"):
        md_path, html_path = _save_report(req.hsd_id.strip(), result["report_markdown"], result)
        result["saved_path"] = md_path
        result["saved_html_path"] = html_path
    return result


@app.post("/api/batch_learn")
async def api_batch_learn(request: Request, body: BatchLearnRequest):
    creds = _creds(request)
    if not creds and not _kerberos():
        return JSONResponse(status_code=401, content={"error": "Please sign in first."})
    if not body.query_id and not body.hsd_ids and not body.product:
        return JSONResponse(status_code=400,
                            content={"error": "Provide 'query_id', 'product', or 'hsd_ids'."})
    return await batch_learn(
        hsd_ids=body.hsd_ids, query_id=body.query_id, product=body.product, limit=body.limit,
        username=(creds or {}).get("username"), password=(creds or {}).get("password"),
    )


@app.get("/api/products")
async def api_products():
    from .products import all_products
    return {k: {"display": v.get("display", k),
                "master_queries": v.get("master_queries", [])}
            for k, v in all_products().items()}


@app.get("/api/kb")
async def api_kb():
    return {"entries": kb.all()}


@app.get("/api/bugscout/features")
async def api_bugscout_features():
    return feature_status()


@app.post("/api/bugscout/crashdump")
async def api_bugscout_crashdump(body: CrashdumpRequest):
    try:
        return parse_crashdump_file(body.input_path.strip(), body.output_dir)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/handbook-search")
async def api_bugscout_handbook_search(body: HandbookSearchRequest):
    q = body.query.strip()
    if not q:
        return JSONResponse(status_code=400, content={"error": "query is required."})
    try:
        return {"query": q, "matches": handbook_search(q, top_k=max(1, min(12, body.top_k)))}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/log-index")
async def api_bugscout_log_index(body: LogIndexRequest):
    path = body.file_path.strip()
    if not path:
        return JSONResponse(status_code=400, content={"error": "file_path is required."})
    try:
        return cache_log_index(path)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/log-search")
async def api_bugscout_log_search(body: LogSearchRequest):
    path = body.file_path.strip()
    keys = [k.strip() for k in (body.keywords or []) if k and k.strip()]
    if not path:
        return JSONResponse(status_code=400, content={"error": "file_path is required."})
    if not keys:
        return JSONResponse(status_code=400, content={"error": "At least one keyword is required."})
    try:
        return {
            "file_path": path,
            "keywords": keys,
            "results": cache_log_search(path, keys, lines=max(1, min(500, body.lines)),
                                         section=(body.section or "").strip() or None),
        }
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/bugscout/log-cache")
async def api_bugscout_log_cache():
    try:
        return {"cache": list_cached_logs()}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/batch-prepare")
async def api_bugscout_batch_prepare(body: BugScoutPrepareRequest):
    src = body.input_csv.strip()
    if not src:
        return JSONResponse(status_code=400, content={"error": "input_csv is required."})
    try:
        return bugscout_prepare_batch(src)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/batch-finalize")
async def api_bugscout_batch_finalize(body: BugScoutFinalizeRequest):
    src = body.responses_jsonl.strip()
    if not src:
        return JSONResponse(status_code=400, content={"error": "responses_jsonl is required."})
    try:
        return bugscout_finalize_batch(src, (body.output_dir or "").strip() or None)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/batch-report")
async def api_bugscout_batch_report(body: BugScoutReportRequest):
    src = body.input_csv.strip()
    if not src:
        return JSONResponse(status_code=400, content={"error": "input_csv is required."})
    try:
        return bugscout_render_report(src, (body.output_dir or "").strip() or None)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/live-debug-report")
async def api_bugscout_live_debug_report(body: LiveDebugReportRequest):
    sid = body.session_id.strip()
    if not sid:
        return JSONResponse(status_code=400, content={"error": "session_id is required."})
    try:
        return bugscout_render_live_debug_report(sid)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/bugscout/runs")
async def api_bugscout_runs():
    try:
        return list_bugscout_runs()
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/bugscout/live-debug-init")
async def api_bugscout_live_debug_init(body: LiveDebugInitRequest):
    hsd = body.hsd_id.strip()
    if not hsd:
        return JSONResponse(status_code=400, content={"error": "hsd_id is required."})
    mode = body.execution_mode.strip().lower()
    if mode not in {"manual", "local", "ssh", "auto"}:
        return JSONResponse(status_code=400, content={"error": "execution_mode must be one of manual|local|ssh|auto."})
    if mode == "ssh" and not body.server.strip():
        return JSONResponse(status_code=400, content={"error": "server is required when execution_mode is ssh."})
    try:
        return start_live_debug_session(
            hsd_id=hsd,
            execution_mode=mode,
            server=body.server.strip(),
            ssh_user=body.ssh_user.strip(),
            max_iterations=max(1, min(40, body.max_iterations)),
            initial_logs_json=(body.initial_logs_json or "").strip() or None,
        )
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
