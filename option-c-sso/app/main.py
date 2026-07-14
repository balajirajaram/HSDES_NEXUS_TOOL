"""FastAPI app (Option C — per-user SSO).

Auth flow:
  GET  /login          -> redirect to Intel SSO (OIDC authorization code + PKCE)
  GET  /auth/callback  -> exchange code, store user + access token in session
  GET  /logout         -> clear session
Protected:
  POST /api/analyze    -> requires a logged-in session; uses the user's own
                          access token as the HSDES bearer. No shared secret.
"""

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .analyzer import analyze, kb
from .auth import current_access_token, current_user, oauth
from .config import config
from .llm_client import llm

app = FastAPI(title="Auto HSD Analyser — SSO (GNR/SRF/CWF)")
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
_STATIC = os.path.join(os.path.dirname(__file__), "static")


class AnalyzeRequest(BaseModel):
    hsd_id: str
    symptoms: str


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


# ---- Auth ----
@app.get("/login")
async def login(request: Request):
    if not config.oidc_enabled:
        return JSONResponse(
            status_code=503,
            content={"error": "OIDC not configured. Set OIDC_* in .env."},
        )
    return await oauth.intel.authorize_redirect(request, config.OIDC_REDIRECT_URI)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.intel.authorize_access_token(request)
    except Exception as exc:
        return JSONResponse(status_code=401, content={"error": f"Login failed: {exc}"})
    userinfo = token.get("userinfo") or {}
    request.session["user"] = {
        "name": userinfo.get("name") or userinfo.get("preferred_username", "user"),
        "email": userinfo.get("email") or userinfo.get("preferred_username", ""),
    }
    request.session["access_token"] = token.get("access_token", "")
    return RedirectResponse(url="/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


@app.get("/api/me")
async def me(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"authenticated": False})
    return {"authenticated": True, "user": user}


# ---- Status ----
@app.get("/api/health")
async def health():
    return {
        "oidc_enabled": config.oidc_enabled,
        "mcp_enabled": config.mcp_enabled,
        "llm_enabled": llm.enabled,
        "mode": "llm" if llm.enabled else "offline",
        "kb_entries": kb.count(),
    }


# ---- Protected analysis ----
@app.post("/api/analyze")
async def api_analyze(request: Request, req: AnalyzeRequest):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Not signed in."})
    if not req.hsd_id.strip() or not req.symptoms.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Both 'hsd_id' and 'symptoms' are required."},
        )
    # The user's own SSO access token is used as the HSDES bearer for this request.
    token = current_access_token(request)
    return await analyze(req.hsd_id.strip(), req.symptoms.strip(), hsdes_token=token)


@app.get("/api/kb")
async def api_kb(request: Request):
    if not current_user(request):
        return JSONResponse(status_code=401, content={"error": "Not signed in."})
    return {"count": kb.count(), "entries": kb.all()}


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
