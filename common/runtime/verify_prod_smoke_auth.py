#!/usr/bin/env python3
"""Pre-flight authentication probe for production smoke test credentials (#2370).

Validates that PROD_SMOKE_EMAIL and PROD_SMOKE_PASSWORD can authenticate against
the target instance (/api/auth/login) and receive a valid JWT access token,
preventing post-deploy rollback in release.yml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence


def verify_auth(
    base_url: str,
    email: str,
    password: str,
    timeout: float = 15.0,
) -> bool:
    """Send login and identity verification requests to the target instance."""
    login_url = f"{base_url.rstrip('/')}/api/auth/login"
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        login_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "smoke-auth-probe/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"[FAIL] Login returned unexpected HTTP status: {resp.status}")
                return False
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(
            f"[FAIL] Authentication rejected by {login_url}: HTTP {exc.code} - {body}"
        )
        return False
    except Exception as exc:
        print(f"[FAIL] Could not connect to {login_url}: {exc}")
        return False

    token = data.get("access_token")
    user_id = data.get("id")
    user_email = data.get("email")
    if not token:
        print("[FAIL] Login response did not contain an access_token.")
        return False

    # Verify token with /api/auth/me
    me_url = f"{base_url.rstrip('/')}/api/auth/me"
    me_req = urllib.request.Request(
        me_url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "smoke-auth-probe/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(me_req, timeout=timeout) as me_resp:
            if me_resp.status != 200:
                print(f"[FAIL] Token verification returned HTTP {me_resp.status}")
                return False
            me_data = json.loads(me_resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[FAIL] Could not verify token with {me_url}: {exc}")
        return False

    print("[OK] Production smoke authentication verified successfully.")
    print(f"Target:   {base_url}")
    print(f"User ID:  {user_id}")
    print(f"Email:    {user_email}")
    print(f"Token:    Verified via /api/auth/me ({me_data.get('email')})")
    print("Status:   Credentials are valid and ready for production smoke test.")
    return True


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for production smoke authentication verification."""
    parser = argparse.ArgumentParser(
        description="Verify production smoke test credentials against live instance."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("APP_URL", "https://report.zitian.party"),
        help="Base application URL (default: https://report.zitian.party)",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("PROD_SMOKE_EMAIL", ""),
        help="Smoke test user email (default: read from PROD_SMOKE_EMAIL)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("PROD_SMOKE_PASSWORD", ""),
        help="Smoke test user password (default: read from PROD_SMOKE_PASSWORD)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Request timeout in seconds (default: 15.0)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run production smoke authentication verification CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    email = args.email.strip()
    password = args.password.strip()

    if not email or not password:
        print("[ERROR] Smoke credentials missing.", file=sys.stderr)
        print(
            "Please provide credentials via arguments or environment variables:",
            file=sys.stderr,
        )
        print("  export PROD_SMOKE_EMAIL='user@example.com'", file=sys.stderr)
        print("  export PROD_SMOKE_PASSWORD='secret'", file=sys.stderr)
        print(
            "  python tools/verify_prod_smoke_auth.py --url https://report.zitian.party",
            file=sys.stderr,
        )
        return 2

    success = verify_auth(args.url, email, password, timeout=args.timeout)
    return 0 if success else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
