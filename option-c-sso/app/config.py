import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # ---- OIDC / SSO (Intel Azure AD or any OpenID Connect provider) ----
    OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")               # e.g. https://login.microsoftonline.com/<tenant>/v2.0
    OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
    OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
    OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "http://127.0.0.1:8100/auth/callback")
    # Scope MUST include the HSDES API scope so the returned access token is
    # accepted by the HSDES REST API (e.g. "openid profile <hsdes-api-scope>").
    OIDC_SCOPES = os.getenv("OIDC_SCOPES", "openid profile email")
    SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-dev-secret")

    # ---- HSDES ----
    HSDES_BASE_URL = os.getenv("HSDES_BASE_URL", "https://hsdes-api.intel.com/rest")
    # No static HSDES token here: the per-user access token comes from the login session.
    HSDES_API_TOKEN = ""

    # ---- LLM (OpenAI-compatible; a server-side service key is acceptable) ----
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

    # ---- KB ----
    KB_DB_PATH = os.getenv("KB_DB_PATH", "kb/hsd_kb.sqlite")

    # ---- Server ----
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8100"))

    @property
    def hsdes_enabled(self) -> bool:
        return bool(self.HSDES_API_TOKEN)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.LLM_BASE_URL and self.LLM_API_KEY)

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.OIDC_ISSUER and self.OIDC_CLIENT_ID and self.OIDC_CLIENT_SECRET)


config = Config()
