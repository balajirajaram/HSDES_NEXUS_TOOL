import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    HSDES_BASE_URL = os.getenv("HSDES_BASE_URL", "https://hsdes-api.intel.com/rest")
    HSDES_API_TOKEN = os.getenv("HSDES_API_TOKEN", "")
    # Auth mode for HSDES: 'basic' (username+password login), 'token', or
    # 'auto'/'kerberos' (use the logged-in Intel user via Negotiate — no prompt).
    HSDES_AUTH_MODE = os.getenv("HSDES_AUTH_MODE", "basic")
    # Signs the session cookie (holds only a random session id, never credentials).
    SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-dev-secret")

    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

    KB_DB_PATH = os.getenv("KB_DB_PATH", "kb/hsd_kb.sqlite")

    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))

    @property
    def hsdes_enabled(self) -> bool:
        return bool(self.HSDES_API_TOKEN)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.LLM_BASE_URL and self.LLM_API_KEY)


config = Config()
