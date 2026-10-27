"""Dispatch one App deploy request and prove the matching infra2 run succeeded."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from infra2_sdk.deploy import (  # noqa: E402
    PRODUCTION_APPROVAL_MARGIN_SECONDS,
    PRODUCTION_REQUEST_MAX_AGE_SECONDS,
    Api,
    LogFetcher,
    ReceiverRun,
    announce_approval_wait,
    github_api_client,
    print_approval_notice,
)
from infra2_sdk.deploy import dispatch_and_wait as _sdk_dispatch_and_wait  # noqa: E402

from common.runtime.deploy.app_deploy_request import request_from_mapping  # noqa: E402
from common.runtime.github_api import write_github_output  # noqa: E402

PRODUCTION_APPROVAL_WINDOW_SECONDS = PRODUCTION_REQUEST_MAX_AGE_SECONDS

__all__ = [
    "Api",
    "LogFetcher",
    "PRODUCTION_APPROVAL_MARGIN_SECONDS",
    "PRODUCTION_APPROVAL_WINDOW_SECONDS",
    "PRODUCTION_REQUEST_MAX_AGE_SECONDS",
    "ReceiverRun",
    "announce_approval_wait",
    "dispatch_and_wait",
    "github_api_client",
    "main",
    "print_approval_notice",
]


def dispatch_and_wait(
    raw_request: Mapping[str, Any],
    *,
    api: Api,
    fetch_logs: LogFetcher,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 5.0,
    max_attempts: int = 300,
    announce: Callable[[str], None] = print_approval_notice,
    clock: Callable[[], datetime] | None = None,
) -> ReceiverRun:
    """Validate raw_request under Finance Report's fixed-env authority, then delegate
    the watermark/ambiguity-guard/log-content-verification dispatch algorithm to
    infra2_sdk.deploy.dispatch_and_wait — the shared infra2-receiver-boundary implementation.

    A Production request waits for the owner to approve the infra2 environment. While it waits,
    announce receives one notice with the approval link and the approval deadline."""
    request = request_from_mapping(raw_request)
    if request.deploy_type.value == "prod":
        api = announce_approval_wait(
            api, request.request_id, request.version_ref, announce
        )
    kwargs: dict[str, Any] = {
        "api": api,
        "fetch_logs": fetch_logs,
        "sleep": sleep,
        "poll_interval": poll_interval,
        "max_attempts": max_attempts,
    }
    if clock is not None:
        kwargs["clock"] = clock
    return _sdk_dispatch_and_wait(request, **kwargs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-env", default="INFRA2_PAT")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.getenv(args.token_env, "")
    if not token:
        print(
            f"app deploy transport failed: {args.token_env} is required",
            file=sys.stderr,
        )
        return 1
    if args.timeout <= 0 or args.poll_interval <= 0:
        print(
            "app deploy transport failed: timeout and poll interval must be positive",
            file=sys.stderr,
        )
        return 1
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, Mapping):
            raise ValueError("deploy request must be a JSON object")
        api, fetch_logs = github_api_client(
            token=token,
            user_agent="finance-report-app-deploy-transport",
            timeout=30.0,
        )
        result = dispatch_and_wait(
            raw,
            api=api,
            fetch_logs=fetch_logs,
            poll_interval=float(args.poll_interval),
            max_attempts=max(
                1,
                (args.timeout + args.poll_interval - 1) // args.poll_interval,
            ),
        )
    except (ValueError, RuntimeError, httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"app deploy transport failed: {exc}", file=sys.stderr)
        return 1
    write_github_output(
        {"receiver_run_id": str(result.run_id), "receiver_run_url": result.url}
    )
    print(
        json.dumps({"receiver_run_id": result.run_id, "receiver_run_url": result.url})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
