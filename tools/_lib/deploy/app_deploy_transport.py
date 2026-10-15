"""Dispatch one App deploy request and prove the matching infra2 run succeeded."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from infra2_sdk.deploy import Api, LogFetcher, ReceiverRun, github_api_client  # noqa: E402
from infra2_sdk.deploy import dispatch_and_wait as _sdk_dispatch_and_wait  # noqa: E402

from common.runtime.github_api import write_github_output  # noqa: E402
from tools.app_deploy_request import request_from_mapping  # noqa: E402


# The infra2 receiver refuses a Production request that is older than this age.
# The value is PRODUCTION_REQUEST_MAX_AGE_SECONDS in infra2 libs/deploy/app_deploy_request.py.
# infra2_sdk 3.5.0 does not export it, so this module holds a copy.
PRODUCTION_APPROVAL_WINDOW_SECONDS = 24 * 60


def print_approval_notice(message: str) -> None:
    """Show the notice in the run log, and as an annotation in GitHub Actions."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::notice title=Production approval needed::{message}")
    print(message, file=sys.stderr)


def _utc_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _approval_notice(run: Mapping[str, Any]) -> str:
    created = _utc_time(run.get("created_at"))
    if created is None:
        when = "The latest approval time is unknown: the run has no creation time. Approve at once."
    else:
        latest = created + timedelta(seconds=PRODUCTION_APPROVAL_WINDOW_SECONDS)
        when = (
            f"The receiver refuses the request after {latest:%Y-%m-%d %H:%M:%S}Z "
            f"(run created {created:%Y-%m-%d %H:%M:%S}Z plus {PRODUCTION_APPROVAL_WINDOW_SECONDS} s)."
        )
    return (
        f"Approval needed: {run.get('html_url')} waits for the owner to approve "
        f"the 'production' environment. {when} "
        "Dispatch the release again if the receiver refuses the request."
    )


def _announce_approval_wait(
    api: Api, request_id: str, announce: Callable[[str], None]
) -> Api:
    """Return api. It announces once when the receiver run of request_id waits for approval."""
    announced = False

    def watching_api(method: str, path: str, body: object = None) -> object:
        nonlocal announced
        payload = api(method, path, body)
        if method == "GET" and not announced:
            runs = (
                payload.get("workflow_runs") if isinstance(payload, Mapping) else None
            )
            for run in runs if isinstance(runs, list) else []:
                if (
                    isinstance(run, Mapping)
                    and request_id in str(run.get("display_title", ""))
                    and run.get("status") == "waiting"
                ):
                    announce(_approval_notice(run))
                    announced = True
                    break
        return payload

    return watching_api


def dispatch_and_wait(
    raw_request: Mapping[str, Any],
    *,
    api: Api,
    fetch_logs: LogFetcher,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 5.0,
    max_attempts: int = 300,
    announce: Callable[[str], None] = print_approval_notice,
) -> ReceiverRun:
    """Validate raw_request under Finance Report's fixed-env authority, then delegate
    the watermark/ambiguity-guard/log-content-verification dispatch algorithm to
    infra2_sdk.deploy.dispatch_and_wait — the shared infra2-receiver-boundary implementation.

    A Production request waits for the owner to approve the infra2 environment. While it waits,
    announce receives one notice with the approval link and the latest approval time."""
    request = request_from_mapping(raw_request)
    if request.deploy_type.value == "prod":
        api = _announce_approval_wait(api, request.request_id, announce)
    return _sdk_dispatch_and_wait(
        request,
        api=api,
        fetch_logs=fetch_logs,
        sleep=sleep,
        poll_interval=poll_interval,
        max_attempts=max_attempts,
    )


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
