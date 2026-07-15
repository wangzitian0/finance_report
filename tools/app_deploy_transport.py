"""Dispatch one App deploy request and prove the matching infra2 run succeeded."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.app_deploy_request import request_from_mapping  # noqa: E402

INFRA_REPOSITORY = "wangzitian0/infra2"
WORKFLOW_FILE = "app-deploy-request.yml"
EVENT_TYPE = "app-deploy-request"
_RUNS_PATH = (
    f"/repos/{INFRA_REPOSITORY}/actions/workflows/{WORKFLOW_FILE}/runs"
    "?event=repository_dispatch&per_page=30"
)

Api = Callable[[str, str, object], object]
LogFetcher = Callable[[int], bytes]


@dataclass(frozen=True)
class ReceiverRun:
    run_id: int
    url: str


def dispatch_and_wait(
    raw_request: Mapping[str, Any],
    *,
    api: Api,
    fetch_logs: LogFetcher,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 5.0,
    max_attempts: int = 300,
) -> ReceiverRun:
    """Wait for the only post-watermark run and correlate its logs to request_id."""
    request = request_from_mapping(raw_request)
    canonical = request.to_dict()
    baseline = _workflow_runs(api("GET", _RUNS_PATH, None))
    watermark = max((_run_id(run) for run in baseline), default=0)

    api(
        "POST",
        f"/repos/{INFRA_REPOSITORY}/dispatches",
        {"event_type": EVENT_TYPE, "client_payload": canonical},
    )

    for attempt in range(max_attempts):
        runs = _workflow_runs(api("GET", _RUNS_PATH, None))
        candidates = [run for run in runs if _run_id(run) > watermark]
        if len(candidates) > 1:
            ids = sorted(_run_id(run) for run in candidates)
            raise RuntimeError(
                f"receiver run correlation is ambiguous after watermark {watermark}: {ids}"
            )
        if not candidates:
            if attempt + 1 < max_attempts:
                sleep(poll_interval)
            continue

        run = candidates[0]
        if run.get("status") != "completed":
            if attempt + 1 < max_attempts:
                sleep(poll_interval)
            continue
        run_id = _run_id(run)
        if run.get("conclusion") != "success":
            raise RuntimeError(
                f"infra2 receiver run {run_id} concluded {run.get('conclusion')!r}"
            )
        request_id = request.request_id.encode("utf-8")
        if request_id not in fetch_logs(run_id):
            raise RuntimeError(
                f"infra2 receiver run {run_id} logs do not contain request_id "
                f"{request.request_id!r}"
            )
        url = run.get("html_url")
        if not isinstance(url, str) or not url.startswith(
            f"https://github.com/{INFRA_REPOSITORY}/actions/runs/"
        ):
            raise RuntimeError(f"infra2 receiver run {run_id} has no canonical URL")
        return ReceiverRun(run_id=run_id, url=url)

    raise RuntimeError(
        f"timed out waiting for an infra2 receiver run after watermark {watermark}"
    )


def _workflow_runs(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        raise RuntimeError("GitHub workflow-runs response must be an object")
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list) or not all(isinstance(run, Mapping) for run in runs):
        raise RuntimeError("GitHub workflow-runs response must contain a run list")
    return runs


def _run_id(run: Mapping[str, object]) -> int:
    run_id = run.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise RuntimeError("GitHub workflow run id must be a positive integer")
    return run_id


def _github_api(client: httpx.Client, method: str, path: str, body: object) -> object:
    response = client.request(method, path, json=body if method == "POST" else None)
    if response.status_code >= 400:
        raise RuntimeError(
            f"GitHub API {method} {path.split('?', 1)[0]} failed with "
            f"HTTP {response.status_code}"
        )
    if method == "POST":
        if response.status_code != 204:
            raise RuntimeError(
                f"GitHub dispatch expected HTTP 204, got {response.status_code}"
            )
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        raise RuntimeError("GitHub API response was not valid JSON") from None


def _github_logs(client: httpx.Client, run_id: int) -> bytes:
    response = client.get(f"/repos/{INFRA_REPOSITORY}/actions/runs/{run_id}/logs")
    if response.status_code >= 400:
        raise RuntimeError(
            f"GitHub receiver logs request failed with HTTP {response.status_code}"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            return b"\n".join(archive.read(name) for name in archive.namelist())
    except zipfile.BadZipFile:
        raise RuntimeError(
            "GitHub receiver logs response was not a zip archive"
        ) from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-env", default="INFRA2_PAT")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=int, default=5)
    return parser


def _write_github_output(result: ReceiverRun) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as output:
        print(f"receiver_run_id={result.run_id}", file=output)
        print(f"receiver_run_url={result.url}", file=output)


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
        with httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "finance-report-app-deploy-transport",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            result = dispatch_and_wait(
                raw,
                api=lambda method, path, body=None: _github_api(
                    client, method, path, body
                ),
                fetch_logs=lambda run_id: _github_logs(client, run_id),
                poll_interval=float(args.poll_interval),
                max_attempts=max(
                    1,
                    (args.timeout + args.poll_interval - 1) // args.poll_interval,
                ),
            )
    except (ValueError, RuntimeError, httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"app deploy transport failed: {exc}", file=sys.stderr)
        return 1
    _write_github_output(result)
    print(
        json.dumps({"receiver_run_id": result.run_id, "receiver_run_url": result.url})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
