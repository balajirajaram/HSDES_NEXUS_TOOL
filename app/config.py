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

    # ---- Optional MCP enrichment (Geni HSDES / Co-Design HSDES agents) ----
    # When set, the analyzer ALSO queries these internal MCP servers (Streamable
    # HTTP, JSON-RPC) and folds their answer into the ticket context, so a report
    # is grounded in HSDES REST + Geni + Co-Design together. Each is independent
    # and optional; leave blank to disable. A bearer token (per user) is required.
    MCP_PROTOCOL_VERSION = os.getenv("MCP_PROTOCOL_VERSION", "2025-06-18")
    # Geni HSDES / Axon / HSD-index agent gateway.
    GENI_MCP_URL = os.getenv("GENI_MCP_URL", "")
    GENI_MCP_TOOL = os.getenv("GENI_MCP_TOOL", "HSDTool")
    GENI_MCP_TOKEN = os.getenv("GENI_MCP_TOKEN", "")
    # Co-Design HSDES agent gateway.
    CODESIGN_MCP_URL = os.getenv("CODESIGN_MCP_URL", "")
    CODESIGN_MCP_TOOL = os.getenv("CODESIGN_MCP_TOOL", "codesign-ask-hsd-agent")
    CODESIGN_MCP_TOKEN = os.getenv("CODESIGN_MCP_TOKEN", "")

    # Optional path to the Axon CLI binary (e.g. ~/bin/axon). When set (or the
    # `axon` binary is on PATH), the analyzer downloads linked Axon recordings and
    # folds their metadata + log content into the decode. Leave blank to disable.
    AXON_CLI_PATH = os.getenv("AXON_CLI_PATH", "")
    # Short-lived Axon bearer token (from `acquire-tokens` skill or refresh_axon_token.ps1).
    # Read fresh from env each time so a refreshed .env is picked up without restart.
    @property
    def AXON_GENI_TOKEN(self) -> str:  # type: ignore[override]
        return os.getenv("AXON_GENI_TOKEN", "")



    # Optional live enrichment: a local BIOS/IFWI source checkout. When set, the
    # analyzer greps it for the exact code sites found in logs (e.g.
    # MultiSocketLib.c:1241) and includes the surrounding source in the report.
    BIOS_REPO_PATH = os.getenv("BIOS_REPO_PATH", "")

    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))

    @property
    def hsdes_enabled(self) -> bool:
        return bool(self.HSDES_API_TOKEN)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.LLM_BASE_URL and self.LLM_API_KEY)


config = Config()
