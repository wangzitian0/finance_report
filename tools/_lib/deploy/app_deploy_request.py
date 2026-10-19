"""Render a validated Finance Report fixed-environment request without side effects."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from infra2_sdk.deploy import (  # noqa: E402
    DeployOperation,
    DeployRequest,
    DeployType,
    canonical_json,
    render_sender_request,
    validate_sender_request,
)

SERVICE = "finance_report/app"
SOURCE_REPOSITORY = "wangzitian0/finance_report"
CONTRACT_VERSION = 1
_REPO_LABEL = "Finance Report"
_SOURCE_RUN_PATH_RE = re.compile(
    rf"\A/{re.escape(SOURCE_REPOSITORY)}/actions/runs/([1-9][0-9]*)\Z"
)

__all__ = [
    "CONTRACT_VERSION",
    "DeployOperation",
    "DeployRequest",
    "DeployType",
    "SERVICE",
    "SOURCE_REPOSITORY",
    "_SOURCE_RUN_PATH_RE",
    "canonical_json",
    "main",
    "render_request",
    "request_from_mapping",
]


def request_from_mapping(raw: Mapping[str, Any]) -> DeployRequest:
    """Deserialize and enforce Finance Report's narrower sender authority."""
    return validate_sender_request(
        raw,
        service=SERVICE,
        source_repository=SOURCE_REPOSITORY,
        repo_label=_REPO_LABEL,
        supported_deploy_types=(DeployType.STAGING.value, DeployType.PRODUCTION.value),
        version_ref_error="version_ref must be a release tag like vX.Y.Z",
        prod_staging_required_error="evidence.staging_run_url is required for prod",
        prod_review_required_error="evidence.reviewed_change_url is required for prod",
        prod_staging_url_error="evidence.staging_run_url must be a canonical Finance Report GitHub URL",
        prod_review_url_error="evidence.reviewed_change_url must be a canonical Finance Report GitHub URL",
    )


def render_request(
    *,
    request_id: str,
    deploy_type: str = DeployType.STAGING.value,
    version_ref: str,
    source_sha: str,
    source_run_url: str,
    source_run_id: str,
    staging_run_url: str = "",
    reviewed_change_url: str = "",
) -> DeployRequest:
    """Build the only request shape this repository is allowed to emit."""
    return render_sender_request(
        service=SERVICE,
        source_repository=SOURCE_REPOSITORY,
        repo_label=_REPO_LABEL,
        request_id=request_id,
        deploy_type=deploy_type,
        version_ref=version_ref,
        source_sha=source_sha,
        source_run_url=source_run_url,
        source_run_id=source_run_id,
        staging_run_url=staging_run_url,
        reviewed_change_url=reviewed_change_url,
        supported_deploy_types=(DeployType.STAGING.value, DeployType.PRODUCTION.value),
        version_ref_error="version_ref must be a release tag like vX.Y.Z",
        prod_staging_required_error="evidence.staging_run_url is required for prod",
        prod_review_required_error="evidence.reviewed_change_url is required for prod",
        prod_staging_url_error="evidence.staging_run_url must be a canonical Finance Report GitHub URL",
        prod_review_url_error="evidence.reviewed_change_url must be a canonical Finance Report GitHub URL",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", required=True)
    parser.add_argument(
        "--deploy-type",
        choices=(DeployType.STAGING.value, DeployType.PRODUCTION.value),
        default=DeployType.STAGING.value,
    )
    parser.add_argument("--version-ref", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-run-url", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--staging-run-url", default="")
    parser.add_argument("--reviewed-change-url", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        request = render_request(
            request_id=args.request_id,
            deploy_type=args.deploy_type,
            version_ref=args.version_ref,
            source_sha=args.source_sha,
            source_run_url=args.source_run_url,
            source_run_id=args.source_run_id,
            staging_run_url=args.staging_run_url,
            reviewed_change_url=args.reviewed_change_url,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(canonical_json(request), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
