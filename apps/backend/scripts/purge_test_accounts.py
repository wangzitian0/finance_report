"""Container-native CLI entrypoint to purge disposable test/QA accounts."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import src.orm_registry  # noqa: E402, F401
from src.config import settings  # noqa: E402
from src.database import async_session_maker  # noqa: E402
from src.identity import (  # noqa: E402
    DEFAULT_TEST_EMAIL_PATTERN,
    PERSISTENT_TEST_EMAILS,
    is_safe_purge_environment,
    purge_test_accounts,
)


def _redact(database_url: str) -> str:
    if "://" in database_url and "@" in database_url:
        scheme, _, tail = database_url.partition("://")
        host = tail.split("@", 1)[1]
        return f"{scheme}://***@{host}"
    return "***" if "@" in database_url else database_url


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Purge disposable test/QA accounts from a database.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag the run is a dry run (default).",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_TEST_EMAIL_PATTERN,
        help="Email regex selecting test accounts.",
    )
    parser.add_argument(
        "--rotate-append-only",
        action="store_true",
        help="Rotate aged disposable tenants including append-only ledger/trace/envelope rows (dev/staging only).",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="Minimum account age in days (recommended: 14 with --rotate-append-only).",
    )
    parser.add_argument(
        "--keep-email",
        action="append",
        default=[],
        help="Persistent test/demo email to exclude (repeatable).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override the environment guard for standard --apply outside a dev/staging environment.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


async def _run(
    args: argparse.Namespace,
    *,
    session_maker: Callable[[], Any] = async_session_maker,
    purge_fn: Callable[..., Any] = purge_test_accounts,
) -> int:
    target = _redact(settings.database_url)
    mode = "APPLY" if args.apply else "dry-run"
    raw_environment = os.environ.get("ENVIRONMENT")
    pattern = args.pattern
    print(
        f"[purge-test-accounts] target={target} environment={raw_environment!r} "
        f"mode={mode} rotate_append_only={args.rotate_append_only}"
    )

    if args.apply and not is_safe_purge_environment(raw_environment) and not args.force:
        print(
            f"Refusing to --apply in environment {raw_environment!r}. "
            "Re-run with --force only if you are certain this is not production.",
            file=sys.stderr,
        )
        return 2

    if args.rotate_append_only and not is_safe_purge_environment(raw_environment):
        print(
            f"Refusing --rotate-append-only outside dev/staging environments ({raw_environment!r}).",
            file=sys.stderr,
        )
        return 2

    try:
        re.compile(pattern)
    except re.error as exc:
        print(f"Invalid --pattern regex: {exc}", file=sys.stderr)
        return 2

    async with session_maker() as session:
        if args.rotate_append_only or args.older_than_days is not None or args.keep_email:
            keep = set(PERSISTENT_TEST_EMAILS)
            keep.update(args.keep_email)
            env_test_user = os.environ.get("TEST_USER_EMAIL", "").strip()
            if env_test_user:
                keep.add(env_test_user)
            report = await purge_fn(
                session,
                pattern=pattern,
                older_than_days=args.older_than_days,
                exclude_emails=keep,
                rotate_append_only=args.rotate_append_only,
                environment=raw_environment,
                apply=args.apply,
            )
        else:
            report = await purge_fn(session, pattern=pattern, apply=args.apply)
        if args.apply:
            await session.commit()

    print(report.summary())
    return 0


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    session_maker: Callable[[], Any] = async_session_maker,
    purge_fn: Callable[..., Any] = purge_test_accounts,
) -> int:
    return asyncio.run(_run(_parse_args(argv), session_maker=session_maker, purge_fn=purge_fn))


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
