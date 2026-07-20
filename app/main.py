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
from typing import Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .analyzer import analyze, kb
from .batch_learn import batch_learn
from .config import config
from .hsdes_client import HSDESClient
from .llm_client import llm

app = FastAPI(title="Auto HSD Analyser")
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
_STATIC = os.path.join(os.path.dirname(__file__), "static")

# Server-side credential store: session_id -> {"username","password"}.
# In-memory only; cleared on logout and on process restart.
_SESSIONS: Dict[str, Dict[str, str]] = {}


class AnalyzeRequest(BaseModel):
    hsd_id: str
    symptoms: str
    log_text: Optional[str] = None
    fetch_attachments: bool = False


class LoginRequest(BaseModel):
    username: str
    password: str


class BatchLearnRequest(BaseModel):
    query_id: Optional[str] = None
    product: Optional[str] = None
    hsd_ids: Optional[list] = None
    limit: int = 100


def _creds(request: Request) -> Optional[Dict[str, str]]:
    sid = request.session.get("sid")
    return _SESSIONS.get(sid) if sid else None


def _kerberos() -> bool:
    return config.HSDES_AUTH_MODE.lower() in ("auto", "kerberos")


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


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
    return await analyze(
        req.hsd_id.strip(), req.symptoms.strip(),
        username=(creds or {}).get("username"),
        password=(creds or {}).get("password"),
        log_text=req.log_text,
        fetch_attachments=req.fetch_attachments,
    )


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


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
