# Auto HSD Analyser — Option C (Per-User SSO)

A web version of the HSD triage tool where **every user signs in with their own Intel
identity (SSO / OpenID Connect)**. Each user's own access token is used for their HSDES
calls — there is **no shared token and nothing to paste**. This is the "hosted shared
tool, but still per-user permissions" model.

```
Browser ──(1) Sign in──▶ Intel SSO (OIDC + PKCE)
        ◀─(2) code────
Server  ──(3) exchange code──▶ token (per user, kept in that user's session)
        ──(4) HSDES call with the user's own bearer token──▶ HSDES REST
```

The analysis engine (self-learning KB, HSDES client, LLM reasoning, A–H report) is the
same as the main tool — only the auth layer differs.

---

## Agentic self-learning loop (team-wide)

Every analysis runs the loop and **grows a shared, server-side Knowledge Base** — so the
hosted app gets smarter for the whole team over time (not just one laptop):

```
READ (full HSD: header + description + comments, via the user's SSO token)
  -> RECALL (search shared KB, score confidence)
  -> ANALYZE (LLM produces A-H report + a structured learned case)
  -> WRITE-BACK (upsert the case into the shared KB, tagged confirmed vs hypothesis)
  -> next user with the same signature gets an instant, KB-first answer
```

- The HSDES client reads the ticket **fully** — description **and the comment/update
  thread** (the real debug narrative), not just the header.
- The learned KB is a single SQLite DB on the server (`KB_DB_PATH`), shared by all users.
- Nothing fabricated: entries store only what was read/confirmed, with provenance +
  timestamp; HSDES remains the source of truth on any conflict.

---

## Reading via the internal MCP (HTTPS) — optional, MCP-first

The tool can read HSDs from an **internal MCP server over HTTPS** (e.g. the Geni
agent-gateway that exposes `HSDTool` / `HSDIndexTool`) using the **signed-in user's
OAuth bearer token** — the same rich reads you get inside Copilot, but from the web app.

- Set `MCP_SERVER_URL` in `.env`; the tool then uses **MCP first** and falls back to
  HSDES REST if the MCP call fails.
- Implemented in [app/mcp_reader.py](app/mcp_reader.py) as a minimal MCP **Streamable
  HTTP** JSON-RPC client (`initialize` → `notifications/initialized` → `tools/call`).
- Discovered endpoint (validate for your tenant):
  `https://laas-aks-prod01.laas.icloud.intel.com/agentgateway/api/a2a/geni/genivalidationmcpserver/`

```
MCP_SERVER_URL=https://laas-aks-prod01.laas.icloud.intel.com/agentgateway/api/a2a/geni/genivalidationmcpserver/
MCP_TOOL_NAME=HSDTool
```

> The exact tool name / argument schema varies per MCP server. `MCP_TOOL_NAME` and the
> argument mapping in `app/mcp_reader.py` (`read_article`) may need a one-line tweak to
> match the server's `tools/list` contract — validate against the live endpoint once a
> real OAuth token is available. The user's SSO scope must be accepted by that MCP.

---

## When to use this vs the other options
- **Option C (this)** — you want to **host one shared web app** but keep per-user HSDES
  permissions and avoid distributing secrets. Requires an SSO app registration.
- **Option D (`../option-d-copilot`)** — you just want each engineer to run it **locally
  in VS Code / GitHub Copilot** with zero hosting and zero tokens.

---

## Prerequisites

1. Python 3.10+
2. An **OIDC app registration** with your IdP (Intel Azure AD). You need:
   - Issuer URL (discovery at `<issuer>/.well-known/openid-configuration`)
   - Client ID + Client Secret
   - Redirect URI = `http://127.0.0.1:8100/auth/callback` (add the deployed URL too)
   - A **scope that authorizes the HSDES REST API**, so the issued access token is
     accepted by HSDES (e.g. `api://<hsdes-app-id>/.default`).
3. (Optional) An OpenAI-compatible LLM endpoint for full reasoning; otherwise OFFLINE
   deterministic reports.

> Work with your IT / IdP admins to create the app registration and to confirm the
> exact HSDES API scope/audience. Without a scope that HSDES accepts, sign-in will
> succeed but HSDES calls will be rejected.

---

## Setup & run (Windows PowerShell)

```powershell
cd option-c-sso
./run.ps1            # creates venv, installs deps, copies .env.example -> .env
```

Edit `.env` and fill in:
```
OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
OIDC_CLIENT_ID=<client-id>
OIDC_CLIENT_SECRET=<client-secret>
OIDC_REDIRECT_URI=http://127.0.0.1:8100/auth/callback
OIDC_SCOPES=openid profile email api://<hsdes-app-id>/.default
SESSION_SECRET=<long-random-string>
LLM_BASE_URL=...        # optional
LLM_API_KEY=...         # optional
```

Re-run `./run.ps1`, open **http://127.0.0.1:8100**, click **Sign in**, then analyse.

### Manual start (any OS)
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # edit it
uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload
```

---

## How auth works (routes)

| Route | Purpose |
|-------|---------|
| `GET /login` | Redirects to Intel SSO (OIDC authorization code + PKCE). |
| `GET /auth/callback` | Exchanges the code; stores user + access token in the session. |
| `GET /logout` | Clears the session. |
| `GET /api/me` | Returns the signed-in user or 401. |
| `POST /api/analyze` | **Protected.** Uses the user's own token as the HSDES bearer. |
| `GET /api/kb` | **Protected.** Lists learned KB entries. |

Tokens live only in the signed session cookie (server-side session via
`SessionMiddleware`). Nothing is written to `.env` or disk.

---

## Deploying for the team

1. Host behind HTTPS (e.g. internal app service / container).
2. Register the deployed callback URL (`https://<host>/auth/callback`) in the IdP.
3. Set a strong `SESSION_SECRET` and real `OIDC_*` values as environment variables.
4. Share the URL — each user signs in as themselves. No tokens change hands.

---

## Security notes
- `SESSION_SECRET` must be long and random in production; rotate if leaked.
- Always serve over HTTPS in deployment so session cookies aren't exposed.
- The HSDES field mapping in `app/hsdes_client.py` is best-effort — align it to your
  tenant's REST contract.
- Intel Internal Use Only.
