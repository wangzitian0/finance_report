"""Purge throwaway test/QA accounts implementation from a staging database (#997 item 4)."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(1, str(BACKEND_DIR))

import src.orm_registry  # noqa: E402, F401
from src.config import settings  # noqa: E402
from src.database import async_session_maker  # noqa: E402
from src.identity import (  # noqa: E402
    DEFAULT_TEST_EMAIL_PATTERN,
    PERSISTENT_TEST_EMAILS,
    STAGING_DISPOSABLE_EMAIL_PATTERN,
    is_safe_purge_environment,
    purge_staging_tenant_data,
    purge_test_accounts,
)


def _redact(database_url: str) -> str:
    if "://" in database_url and "@" in database_url:
        scheme, _, tail = database_url.partition("://")
        host = tail.split("@", 1)[1]
        return f"{scheme}://***@{host}"
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
        default=None,
        help="Email regex selecting test accounts.",
    )
    parser.add_argument(
        "--staging-rotate",
        action="store_true",
        help="Rotate aged disposable staging tenants including append-only ledger/trace/envelope rows.",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=14,
        help="Minimum account age in days for --staging-rotate (default: 14).",
    )
    parser.add_argument(
        "--keep-email",
        action="append",
        default=[],
        help="Persistent test/demo email to exclude from --staging-rotate (repeatable).",
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
    raw_environment = (
        os.environ.get("ENVIRONMENT")
        or os.environ.get("ENV")
        or os.environ.get("INFRA_ENVIRONMENT")
    )
    pattern = args.pattern or (
        STAGING_DISPOSABLE_EMAIL_PATTERN
        if args.staging_rotate
        else DEFAULT_TEST_EMAIL_PATTERN
    )
    print(
        f"[purge-test-accounts] target={target} environment={raw_environment!r} "
        f"mode={mode} staging_rotate={args.staging_rotate}"
    )

    if args.apply and not is_safe_purge_environment(raw_environment) and not args.force:
        print(
            f"Refusing to --apply in environment {raw_environment!r}. "
            "Re-run with --force only if you are certain this is not production.",
            file=sys.stderr,
        )
        return 2

    if args.staging_rotate and not is_safe_purge_environment(raw_environment):
        print(
            f"Refusing --staging-rotate outside dev/staging environments ({raw_environment!r}).",
            file=sys.stderr,
        )
        return 2

    try:
        re.compile(pattern)
    except re.error as exc:
        print(f"Invalid --pattern regex: {exc}", file=sys.stderr)
        return 2

    async with async_session_maker() as session:
        if args.staging_rotate:
            keep = set(PERSISTENT_TEST_EMAILS)
            keep.update(args.keep_email)
            env_test_user = os.environ.get("TEST_USER_EMAIL", "").strip()
            if env_test_user:
                keep.add(env_test_user)
            report = await purge_staging_tenant_data(
                session,
                environment=raw_environment,
                pattern=pattern,
                older_than_days=args.older_than_days,
                exclude_emails=keep,
                apply=args.apply,
            )
        else:
            report = await purge_test_accounts(
                session, pattern=pattern, apply=args.apply
            )
        if args.apply:
            await session.commit()

    print(report.summary())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
