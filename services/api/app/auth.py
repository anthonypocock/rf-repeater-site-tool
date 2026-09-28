"""Supabase Auth verification for the MVP API."""

from __future__ import annotations

import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


AUTH_CACHE_TTL_SECONDS = 60.0
_AUTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    supabase_url: str
    publishable_key: str
    gateway_secret: str


class AuthError(Exception):
    """Raised when an API request is not authenticated."""


def auth_config() -> AuthConfig:
    enabled = os.environ.get("MVP_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    return AuthConfig(
        enabled=enabled,
        supabase_url=os.environ.get("MVP_SUPABASE_URL", "").strip().rstrip("/"),
        publishable_key=os.environ.get("MVP_SUPABASE_PUBLISHABLE_KEY", "").strip(),
        gateway_secret=os.environ.get("MVP_GATEWAY_SECRET", "").strip(),
    )


def require_authenticated(headers: Any) -> dict[str, Any] | None:
    config = auth_config()
    if not config.enabled:
        return None
    proxy_secret = headers.get("X-Site-Finder-Proxy-Secret", "")
    if proxy_secret:
        if not config.gateway_secret or not hmac.compare_digest(proxy_secret, config.gateway_secret):
            raise AuthError("Invalid gateway proxy secret.")
        email = headers.get("X-Auth-Request-Email", "").strip()
        user = {"id": f"gateway:{email or 'proxy'}", "auth_method": "gateway_proxy"}
        if email:
            user["email"] = email
        return user
    if not config.supabase_url or not config.publishable_key:
        raise AuthError("Authentication is enabled but Supabase is not configured.")

    token = _bearer_token(headers.get("Authorization", ""))
    if not token:
        raise AuthError("Missing bearer token.")

    cached = _AUTH_CACHE.get(token)
    now = time.time()
    if cached and cached[0] > now:
        return cached[1]

    user = _fetch_user(config, token)
    _AUTH_CACHE[token] = (now + AUTH_CACHE_TTL_SECONDS, user)
    return user


def _bearer_token(value: str) -> str:
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""
    return token.strip()


def _fetch_user(config: AuthConfig, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{config.supabase_url}/auth/v1/user",
        headers={
            "apikey": config.publishable_key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in {400, 401, 403}:
            raise AuthError("Invalid or expired session.") from error
        raise AuthError(f"Supabase auth verification failed: HTTP {error.code}.") from error
    except Exception as error:  # pragma: no cover - defensive external boundary
        raise AuthError("Supabase auth verification failed.") from error

    if not isinstance(payload, dict) or not payload.get("id"):
        raise AuthError("Supabase auth verification returned no user.")
    return payload
