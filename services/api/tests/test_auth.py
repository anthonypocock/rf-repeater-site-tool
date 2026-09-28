#!/usr/bin/env python3
"""Checks for optional Supabase Auth enforcement."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.auth import AuthError, require_authenticated  # noqa: E402


class Headers:
    def __init__(
        self,
        authorization: str = "",
        proxy_secret: str = "",
        email: str = "",
    ) -> None:
        self.values = {
            "authorization": authorization,
            "x-site-finder-proxy-secret": proxy_secret,
            "x-auth-request-email": email,
        }

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name.lower(), default)


def main() -> None:
    old_enabled = os.environ.get("MVP_AUTH_ENABLED")
    old_url = os.environ.get("MVP_SUPABASE_URL")
    old_key = os.environ.get("MVP_SUPABASE_PUBLISHABLE_KEY")
    old_gateway_secret = os.environ.get("MVP_GATEWAY_SECRET")
    try:
        os.environ["MVP_AUTH_ENABLED"] = "false"
        assert require_authenticated(Headers()) is None

        os.environ["MVP_AUTH_ENABLED"] = "true"
        os.environ["MVP_GATEWAY_SECRET"] = "pilot-secret"
        gateway_user = require_authenticated(
            Headers(proxy_secret="pilot-secret", email="pilot@example.com")
        )
        assert gateway_user == {
            "id": "gateway:pilot@example.com",
            "auth_method": "gateway_proxy",
            "email": "pilot@example.com",
        }
        try:
            require_authenticated(Headers())
        except AuthError as error:
            assert "Supabase is not configured" in str(error)
        else:  # pragma: no cover - explicit failure path
            raise AssertionError("missing gateway credentials should fail")
        try:
            require_authenticated(Headers(proxy_secret="wrong-secret"))
        except AuthError as error:
            assert "Invalid gateway proxy secret" in str(error)
        else:  # pragma: no cover - explicit failure path
            raise AssertionError("wrong gateway secret should fail")

        os.environ["MVP_SUPABASE_URL"] = "https://example.supabase.co"
        os.environ["MVP_SUPABASE_PUBLISHABLE_KEY"] = "YOUR_SUPABASE_PUBLISHABLE_KEY"
        try:
            require_authenticated(Headers())
        except AuthError as error:
            assert "Missing bearer token" in str(error)
        else:  # pragma: no cover - explicit failure path
            raise AssertionError("AuthError was not raised for missing token")
        with patch("app.auth._fetch_user", return_value={"id": "supabase-user"}):
            assert require_authenticated(Headers(authorization="Bearer valid-token")) == {
                "id": "supabase-user"
            }
    finally:
        _restore_env("MVP_AUTH_ENABLED", old_enabled)
        _restore_env("MVP_SUPABASE_URL", old_url)
        _restore_env("MVP_SUPABASE_PUBLISHABLE_KEY", old_key)
        _restore_env("MVP_GATEWAY_SECRET", old_gateway_secret)

    print("auth checks passed")


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    main()
