"""Axon REST API Client.

Client for Intel's Axon failure-record storage service.
https://axon.intel.com/swagger-ui/index.html

Axon stores test failure records (crashdumps, logs, metadata) indexed by a
string record ID.  BugScout uses this client to:
  - Look up a record and enumerate its content types (attached files/objects).
  - Download individual content objects into a local directory.
  - Execute Axon queries to locate records by metadata criteria.

Authentication flow
-------------------
Axon uses a two-step token exchange:
  1. Acquire an Azure AD access token for the Axon application.
  2. Exchange it for an Axon API token via ``GET /api/v2/token``.

Step 1 uses ``msal`` with silent-cache → device-code fallback.
The MSAL token cache is persisted to ``~/.bugscout/axon_token_cache.bin`` so
re-authentication is only needed after token expiry (~1 h).

Required third-party packages (add to requirements.txt):
  msal>=1.28
  requests>=2.31
  certifi
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import certifi
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Axon application / tenant constants
# These may need updating if Intel rotates the Axon AAD app registration.
# ---------------------------------------------------------------------------
_AXON_BASE_URL = "https://axon.intel.com"
_AXON_AAD_CLIENT_ID = os.environ.get("AXON_AAD_CLIENT_ID", "")
_AXON_AAD_TENANT_ID = os.environ.get("AXON_AAD_TENANT_ID", "46c98d88-e344-4ed4-8496-4ed7712e255d")  # Intel tenant
_AXON_AAD_SCOPE = os.environ.get(
    "AXON_AAD_SCOPE",
    # Default: the Axon app's own scope.  Override via env var if Intel changes it.
    "api://axon.intel.com/.default",
)
_TOKEN_CACHE_PATH = Path.home() / ".bugscout" / "axon_token_cache.bin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(name: str, fallback: str) -> str:
    """Sanitize a filename, removing path-traversal and unsafe characters."""
    if not name:
        return fallback
    name = Path(name).name  # strip directory components
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name or fallback


def _intel_ca_bundle() -> str:
    """Return a CA bundle that includes Intel internal root certificates."""
    intel_certs_path = (
        "\\\\amr.corp.intel.com\\ec\\proj\\ha\\sighting\\share\\hsdes_2.0\\"
        "Tools\\OpenSource_py\\certs\\20240813-Intel_certs\\pem_files\\"
        "Intel_Combined_All.pem"
    )
    import tempfile

    ca_bundle = certifi.where()
    if os.path.exists(intel_certs_path):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pem") as tmp:
            with open(ca_bundle) as f:
                tmp.write(f.read())
            with open(intel_certs_path) as f:
                tmp.write("\n")
                tmp.write(f.read())
            return tmp.name
    return ca_bundle


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

def _acquire_azure_token(client_id: str, tenant_id: str, scope: str) -> str:
    """Acquire an Azure AD access token using MSAL.

    Tries silent (cached) first; falls back to device-code interactive flow.

    Args:
        client_id: AAD application (client) ID.
        tenant_id: AAD tenant ID.
        scope: OAuth2 scope string.

    Returns:
        Access token string.

    Raises:
        RuntimeError: If token acquisition fails.
    """
    try:
        import msal  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "msal is required for Axon authentication.  "
            "Install it with: pip install msal"
        ) from exc

    _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = msal.SerializableTokenCache()
    if _TOKEN_CACHE_PATH.exists():
        cache.deserialize(_TOKEN_CACHE_PATH.read_text(encoding="utf-8"))

    if not client_id:
        raise RuntimeError(
            "AXON_AAD_CLIENT_ID environment variable is not set. "
            "Contact the Axon team (axon.support@intel.com) for the AAD app registration details."
        )

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    # Try silent refresh first
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(scopes=[scope], account=accounts[0])

    # Fall back to device-code flow
    if not result or "access_token" not in result:
        flow = app.initiate_device_flow(scopes=[scope])
        if "user_code" not in flow:
            raise RuntimeError(f"Device flow initiation failed: {flow}")
        print(f"\n[Axon Auth] {flow['message']}\n")
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(
            f"Failed to acquire Azure token: {result.get('error_description', result)}"
        )

    # Persist cache
    if cache.has_state_changed:
        _TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")

    return result["access_token"]


# ---------------------------------------------------------------------------
# AxonClient
# ---------------------------------------------------------------------------

class AxonClient:
    """Read-only client for the Axon REST API.

    Handles authentication (Azure AD → Axon token exchange), SSL, and the
    most useful failure-record endpoints for BugScout triage workflows.

    Example::

        client = AxonClient()
        record  = client.get_record("axon-abc123")
        content = client.list_content_types("axon-abc123")
        client.download_content("axon-abc123", content[0], dest_dir=Path("./logs"))
    """

    def __init__(
        self,
        base_url: str = _AXON_BASE_URL,
        aad_client_id: str = _AXON_AAD_CLIENT_ID,
        aad_tenant_id: str = _AXON_AAD_TENANT_ID,
        aad_scope: str = _AXON_AAD_SCOPE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._aad_client_id = aad_client_id
        self._aad_tenant_id = aad_tenant_id
        self._aad_scope = aad_scope
        self._axon_token: str | None = None
        self._ca_bundle = _intel_ca_bundle()

        self.session = requests.Session()
        self.session.verify = self._ca_bundle
        self.session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Internal token management
    # ------------------------------------------------------------------

    def _ensure_token(self) -> None:
        """Acquire and cache the Axon API token (refresh if absent)."""
        if self._axon_token:
            return
        azure_token = _acquire_azure_token(
            client_id=self._aad_client_id,
            tenant_id=self._aad_tenant_id,
            scope=self._aad_scope,
        )
        self._axon_token = self._exchange_for_axon_token(azure_token)
        self.session.headers["Authorization"] = f"Bearer {self._axon_token}"

    def _exchange_for_axon_token(self, azure_token: str) -> str:
        """Exchange an Azure Bearer token for an Axon API token.

        Calls ``GET /api/v2/token`` with the Azure token in the Authorization
        header and returns the Axon-specific token from the response.

        Args:
            azure_token: Azure AD access token.

        Returns:
            Axon API token string.
        """
        resp = self.session.get(
            f"{self.base_url}/api/v2/token",
            headers={"Authorization": f"Bearer {azure_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        # Axon returns {"token": "..."} or the token value directly
        if isinstance(data, dict):
            token = data.get("token") or data.get("access_token") or data.get("axon_token")
            if not token:
                # Some versions return the whole dict as the bearer value
                token = data.get("value") or json.dumps(data)
        else:
            token = str(data)
        if not token:
            raise RuntimeError(f"Unexpected token exchange response: {data!r}")
        return token

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        """Authenticated GET with auto-token injection."""
        self._ensure_token()
        resp = self.session.get(f"{self.base_url}{path}", **kwargs)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        """Authenticated POST with auto-token injection."""
        self._ensure_token()
        resp = self.session.post(f"{self.base_url}{path}", **kwargs)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Record / Failure endpoints
    # ------------------------------------------------------------------

    def get_record(self, record_id: str, hide_system: bool = False) -> dict[str, Any]:
        """Return all metadata and content-type list for a record.

        Calls ``GET /api/v1/record/{id}``.

        Args:
            record_id: Axon record / failure ID.
            hide_system: If True, omit system-generated metadata fields.

        Returns:
            Parsed JSON response (dict).
        """
        params = {"hide_system": str(hide_system).lower()}
        resp = self._get(f"/api/v1/record/{record_id}", params=params)
        return resp.json()

    def get_record_metadata(
        self, record_id: str, hide_system: bool = False
    ) -> dict[str, Any]:
        """Return only the record-level metadata (no content metadata).

        Calls ``GET /api/v1/record/{id}/metadata``.

        Args:
            record_id: Axon record / failure ID.
            hide_system: If True, omit system-generated metadata fields.

        Returns:
            Parsed JSON response (dict).
        """
        params = {"hide_system": str(hide_system).lower()}
        resp = self._get(f"/api/v1/record/{record_id}/metadata", params=params)
        return resp.json()

    def list_content_types(self, record_id: str) -> list[str]:
        """Return the list of content-type names attached to a record.

        Calls ``GET /api/v1/record/{id}/content``.

        Args:
            record_id: Axon record / failure ID.

        Returns:
            List of content-type name strings (e.g. ``["crashdump", "serial_log"]``).
        """
        resp = self._get(f"/api/v1/record/{record_id}/content")
        data = resp.json()
        # API returns a list of names or a dict with a list
        if isinstance(data, list):
            return [str(item) for item in data]
        if isinstance(data, dict):
            return [str(item) for item in (data.get("content_types") or data.get("data") or [])]
        return []

    def get_content_metadata(
        self, record_id: str, content_type: str, hide_system: bool = False
    ) -> dict[str, Any]:
        """Return metadata for a specific content type on a record.

        Calls ``GET /api/v1/record/{id}/content/{contentType}/metadata``.

        Args:
            record_id: Axon record ID.
            content_type: Content type name (e.g. ``"crashdump"``).
            hide_system: If True, omit system metadata fields.

        Returns:
            Parsed JSON response (dict).
        """
        params = {"hide_system": str(hide_system).lower()}
        resp = self._get(
            f"/api/v1/record/{record_id}/content/{content_type}/metadata",
            params=params,
        )
        return resp.json()

    def get_content_download_url(
        self, record_id: str, content_type: str, filename: str = ""
    ) -> str:
        """Return a pre-signed download URL for a content object.

        Calls ``GET /api/v1/record/{id}/content/{contentType}/object/url``.

        Args:
            record_id: Axon record ID.
            content_type: Content type name.
            filename: Optional filename hint for the download URL.

        Returns:
            Pre-signed URL string.
        """
        params: dict[str, str] = {}
        if filename:
            params["filename"] = filename
        resp = self._get(
            f"/api/v1/record/{record_id}/content/{content_type}/object/url",
            params=params,
        )
        data = resp.json()
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("url") or data.get("download_url") or ""
        return ""

    def download_content(
        self,
        record_id: str,
        content_type: str,
        dest_dir: Path | str,
        filename_hint: str = "",
        skip_existing: bool = True,
    ) -> Path | None:
        """Download a content object to a local file.

        Calls ``GET /api/v1/record/{id}/content/{contentType}/object``.
        The response is a redirect to Azure Storage; ``requests`` follows it
        automatically.

        Args:
            record_id: Axon record ID.
            content_type: Content type name.
            dest_dir: Directory to write the file into.
            filename_hint: Preferred filename; falls back to content_type.
            skip_existing: If True, skip if a file with that name already exists.

        Returns:
            Path of the written file, or None if skipped / failed.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        params: dict[str, str] = {}
        if filename_hint:
            params["filename"] = filename_hint

        self._ensure_token()
        resp = self.session.get(
            f"{self.base_url}/api/v1/record/{record_id}/content/{content_type}/object",
            params=params,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Derive filename from Content-Disposition or fall back to content_type
        filename = _filename_from_response(resp, content_type, filename_hint)
        dest = dest_dir / filename

        if dest.exists() and skip_existing:
            logger.info("  Skipped (exists): %s", filename)
            return None

        dest.write_bytes(resp.content)
        logger.info("  Downloaded: %s (%d bytes)", filename, len(resp.content))
        return dest

    # ------------------------------------------------------------------
    # Query endpoint
    # ------------------------------------------------------------------

    def execute_query(
        self,
        query_body: dict[str, Any] | str,
        as_alias: str | None = None,
        count: bool = True,
    ) -> Any:
        """Execute an ad-hoc Axon query and return matching records.

        Calls ``POST /api/v1/query/execute``.

        The query body follows the Axon V2 query format — see
        https://readthedocs.intel.com/axon/apis/query/execute_query.html

        Example query body::

            {
                "criteria": {
                    "op": "AND",
                    "criteria": [
                        {"field": "hsd_id", "op": "eq", "value": "15012329795"}
                    ]
                },
                "fields": ["id", "hsd_id", "platform", "testcase"],
                "limit": 50
            }

        Args:
            query_body: Axon query dict (or JSON string).
            as_alias: Optional warehouse alias for Snowflake queries.
            count: Whether the response should include total count.

        Returns:
            Parsed JSON response (list of records or dict with ``data`` key).
        """
        params: dict[str, str] = {"count": str(count).lower()}
        if as_alias:
            params["as"] = as_alias

        if isinstance(query_body, dict):
            payload = json.dumps(query_body)
        else:
            payload = query_body

        self._ensure_token()
        resp = self.session.post(
            f"{self.base_url}/api/v1/query/execute",
            data=payload,
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    def search_by_hsd_id(self, hsd_id: int | str, limit: int = 50) -> list[dict[str, Any]]:
        """Convenience wrapper: find Axon records linked to an HSD article.

        Constructs and executes a query filtering on the ``hsd_id`` metadata
        field.

        Args:
            hsd_id: HSD article ID to search for.
            limit: Maximum number of records to return.

        Returns:
            List of matching record dicts.
        """
        query = {
            "criteria": {
                "op": "AND",
                "criteria": [
                    {"field": "hsd_id", "op": "eq", "value": str(hsd_id)}
                ],
            },
            "fields": ["id", "hsd_id", "platform", "testcase", "content_types"],
            "limit": limit,
        }
        result = self.execute_query(query)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("data") or result.get("records") or []
        return []


# ---------------------------------------------------------------------------
# Filename helper (shared with axon_record_fetcher)
# ---------------------------------------------------------------------------

def _filename_from_response(
    response: requests.Response, content_type: str, hint: str = ""
) -> str:
    """Derive a safe local filename from an HTTP response."""
    cd = response.headers.get("Content-Disposition", "")

    # RFC 5987 encoded filename*=UTF-8''...
    m = re.search(r"filename\*=(?:UTF-8'')?([^\s;]+)", cd, re.IGNORECASE)
    if m:
        from urllib.parse import unquote

        return _safe_filename(unquote(m.group(1)), f"{content_type}.bin")

    # Plain filename=
    m = re.search(r'filename=["\']?([^"\';\r\n]+)["\']?', cd, re.IGNORECASE)
    if m:
        return _safe_filename(m.group(1).strip(), f"{content_type}.bin")

    # Hint provided by caller
    if hint:
        return _safe_filename(hint, f"{content_type}.bin")

    return f"{content_type}.bin"
