from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

_AUTH_HEADER_RE = re.compile(r"(?i)\b(cookie|set-cookie|authorization)\s*:\s*[^\r\n]+")
_ACCESS_TOKEN_COOKIE_RE = re.compile(r"(?i)\b(finance_access_token)\s*=\s*[^\s;'\"']+")


def redact_playwright_auth_headers(text: str) -> str:
    return _ACCESS_TOKEN_COOKIE_RE.sub(
        r"\1=[REDACTED]", _AUTH_HEADER_RE.sub(r"\1: [REDACTED]", text)
    )


def build_auth_cookie(app_url: str, access_token: str) -> dict[str, object]:
    parsed = urlparse(app_url)
    if not parsed.hostname:
        raise ValueError(
            f"APP_URL must include a hostname for auth cookie injection: {app_url}"
        )
    cookie: dict[str, object] = {
        "name": "finance_access_token",
        "value": str(access_token),
        "domain": parsed.hostname,
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
    }
    if parsed.scheme == "https":
        cookie["secure"] = True
    return cookie


def build_runner_browser_session(
    auth_context: dict[str, Any], app_url: str
) -> tuple[dict[str, object], str]:
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
            f"Invalid auth context for browser session injection: user_id={user_id}, has_token={bool(token)}, user_email={user_email}"
        )
    init_script = f"localStorage.setItem('finance_user_id', {json.dumps(str(user_id))});\nlocalStorage.setItem('finance_user_email', {json.dumps(user_email)});"
    return build_auth_cookie(app_url, token), init_script
