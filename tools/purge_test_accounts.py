#!/usr/bin/env python3
"""Purge throwaway test/QA accounts from a staging database (#997 item 4).

Thin operator CLI around ``apps/backend/tests/support/account_purge``. The deletion logic,
its safety model, and the email predicate live in that library (and are unit
tested); this wrapper only owns argument parsing, the environment guard, the DB
session, and the final commit.

Examples:
    # Dry run (default) — report what would be purged, change nothing:
    python tools/purge_test_accounts.py

    # Actually delete, on a staging/dev database:
    python tools/purge_test_accounts.py --apply

    # One-off custom predicate:
    python tools/purge_test_accounts.py --pattern '^load-test-.*@example\\.com$' --apply

Accounts still holding immutable posted/reconciled ledger entries are reported as
*blocked* and left untouched — void those entries first (see #988).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
for _path in (ROOT_DIR, BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import src.models._registry  # noqa: E402, F401  -- register every ORM mapper before relationship config
from src.config import settings  # noqa: E402
from src.database import async_session_maker  # noqa: E402
from tests.support.account_purge import (  # noqa: E402
    DEFAULT_TEST_EMAIL_PATTERN,
    is_safe_purge_environment,
    purge_test_accounts,
)


def _redact(database_url: str) -> str:
    """Hide credentials when echoing the target DB back to the operator."""
    if "://" in database_url and "@" in database_url:
        scheme, _, tail = database_url.partition("://")
        host = tail.split("@", 1)[1]
        return f"{scheme}://***@{host}"
    # No recognizable scheme://credentials@host shape — nothing safe to keep, so
    # don't echo a possibly-credential-bearing string back verbatim.
    return "***" if "@" in database_url else database_url


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Purge disposable test/QA accounts from a database."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag the run is a dry run (default).",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_TEST_EMAIL_PATTERN,
        help="Email regex selecting test accounts (default: qa/e2e/load-test prefixes on example.com).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override the environment guard. Required to --apply outside a dev/staging environment.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    target = _redact(settings.database_url)
    mode = "APPLY" if args.apply else "dry-run"
    # Read the RAW environment variable rather than settings.environment, which
    # defaults to "development" when ENVIRONMENT/ENV is unset — an unset variable
    # in a production shell must read as unsafe, not as a safe default (AC8.17.5).
    raw_environment = os.environ.get("ENVIRONMENT") or os.environ.get("ENV")
    print(
        f"[purge-test-accounts] target={target} environment={raw_environment!r} mode={mode}"
    )

    if args.apply and not is_safe_purge_environment(raw_environment) and not args.force:
        print(
            f"Refusing to --apply in environment {raw_environment!r}. "
            "Re-run with --force only if you are certain this is not production.",
            file=sys.stderr,
        )
        return 2

    # Validate the operator-supplied regex up front so a typo is a clean error,
    # not a traceback after we have already touched the database.
    try:
        re.compile(args.pattern)
    except re.error as exc:
        print(f"Invalid --pattern regex: {exc}", file=sys.stderr)
        return 2

    # Reuse the application's configured session maker (pool_pre_ping + pool sizes
    # from src/database.py) rather than spinning up a bare engine.
    async with async_session_maker() as session:
        report = await purge_test_accounts(
            session, pattern=args.pattern, apply=args.apply
        )
        if args.apply:
            await session.commit()

    print(report.summary())
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
