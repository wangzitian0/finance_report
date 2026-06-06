"""AC8.13.50: Authentication cookie helpers for E2E browser fixtures."""

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
