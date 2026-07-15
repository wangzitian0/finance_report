"""Shared GitHub Actions transport, timestamp parsing, and output writing."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any


def parse_github_time(value: str | None) -> datetime | None:
    """Parse an optional GitHub ISO timestamp as a UTC datetime."""

    if value is None or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def write_github_output(values: dict[str, str]) -> None:
    """Append GitHub Actions outputs when the runner exposes ``GITHUB_OUTPUT``."""

    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            print(f"{key}={value}", file=handle)


class GitHubActionsClient:
    """Small standard-library GitHub Actions client shared by runtime and CI waits."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        api_url: str = "https://api.github.com",
        user_agent: str = "finance-report-wait-for-cheap-ci/1.0",
    ) -> None:
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.user_agent = user_agent

    def _request_json(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        url = f"{self.api_url}/repos/{self.repository}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API HTTP {exc.code} for {url}: {body[:500]}"
            ) from exc

    def get_workflow_runs(self, commit_sha: str) -> list[dict[str, Any]]:
        payload = self._request_json(
            "/actions/workflows/ci.yml/runs", {"head_sha": commit_sha}
        )
        return payload.get("workflow_runs") or []

    def get_run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        payload = self._request_json(f"/actions/runs/{run_id}/jobs")
        return payload.get("jobs") or []

    def get_run_payload(self, run_id: int) -> dict[str, Any]:
        return self._request_json(f"/actions/runs/{run_id}")

    def list_workflow_runs(
        self, workflow_id: int, *, max_pages: int = 5
    ) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload = self._request_json(
                f"/actions/workflows/{workflow_id}/runs",
                {"per_page": "100", "page": str(page)},
            )
            batch = payload.get("workflow_runs", [])
            if not isinstance(batch, list) or not batch:
                break
            runs.extend(batch)
            if len(batch) < 100:
                break
        return runs
