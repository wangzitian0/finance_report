"""Dispatch one App deploy request and prove the matching infra2 run succeeded."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

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
    run_deploy_transport_cli,
)
from infra2_sdk.deploy import dispatch_and_wait as _sdk_dispatch_and_wait  # noqa: E402

from common.runtime.deploy.app_deploy_request import request_from_mapping  # noqa: E402
from common.runtime.github_api import write_github_output  # noqa: E402

__all__ = [
    "Api",
    "LogFetcher",
    "PRODUCTION_APPROVAL_MARGIN_SECONDS",
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


def main(argv: Sequence[str] | None = None) -> int:
    return run_deploy_transport_cli(
        argv,
        dispatch=dispatch_and_wait,
        user_agent="finance-report-app-deploy-transport",
        api_client_factory=github_api_client,
        github_output=write_github_output,
        stdin=sys.stdin,
    )


if __name__ == "__main__":
    raise SystemExit(main())
