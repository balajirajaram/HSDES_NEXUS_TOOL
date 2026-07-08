"""OpenID Connect (Authorization Code + PKCE) login via Authlib.

Each user authenticates with their own Intel SSO identity. The resulting
access token is kept only in that user's server-side session (signed cookie)
and used as the bearer token for their HSDES calls. No shared secret, no
per-user token pasting.
"""

from authlib.integrations.starlette_client import OAuth

from .config import config

oauth = OAuth()

if config.oidc_enabled:
    oauth.register(
        name="intel",
        client_id=config.OIDC_CLIENT_ID,
        client_secret=config.OIDC_CLIENT_SECRET,
        server_metadata_url=f"{config.OIDC_ISSUER}/.well-known/openid-configuration",
        client_kwargs={
            "scope": config.OIDC_SCOPES,
            "code_challenge_method": "S256",  # PKCE
        },
    )


def current_user(request) -> dict | None:
    return request.session.get("user")


def current_access_token(request) -> str | None:
    return request.session.get("access_token")
