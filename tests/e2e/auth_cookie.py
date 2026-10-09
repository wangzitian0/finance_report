"""AC8.13.50: Authentication cookie helpers for E2E browser fixtures."""

import json
from typing import Any
from urllib.parse import urlparse


def build_auth_cookie(app_url: str, access_token: str) -> dict[str, object]:
    parsed_app_url = urlparse(app_url)
    if not parsed_app_url.hostname:
        raise ValueError(
            f"APP_URL must include a hostname for auth cookie injection: {app_url}"
        )

    cookie: dict[str, object] = {
        "name": "finance_access_token",
        "value": str(access_token),
        "domain": parsed_app_url.hostname,
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
    }
    if parsed_app_url.scheme == "https":
        cookie["secure"] = True
    return cookie


def build_runner_browser_session(
    auth_context: dict[str, Any], app_url: str
) -> tuple[dict[str, object], str]:
    """Return the auth cookie and the localStorage init script for a benchmark runner session.

    Raises ValueError when the context has no access token, user id, or user email.
    """
    user_data = auth_context.get("user_data") or {}
    user_email = auth_context.get("user_email")
    token = user_data.get("access_token")
    user_id = user_data.get("id") or (
        user_data.get("user", {}).get("id")
        if isinstance(user_data.get("user"), dict)
        else None
    )

    if not token or not user_id or not user_email:
        raise ValueError(
            f"Invalid auth context for browser session injection: "
            f"user_id={user_id}, has_token={bool(token)}, user_email={user_email}"
        )

    init_script = f"""
        localStorage.setItem('finance_user_id', {json.dumps(str(user_id))});
        localStorage.setItem('finance_user_email', {json.dumps(user_email)});
    """
    return build_auth_cookie(app_url, token), init_script
