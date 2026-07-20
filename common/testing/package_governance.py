"""Composition adapter for package governance observations and reports."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from common.meta.base.governance_control import (
    DetectorObservation,
    EnforcementObservation,
    IssueObservation,
    ProofObservation,
)
from common.meta.data.governance_control import governance_control_index
from common.meta.extension.check_package_contract import discover_packages
from common.meta.extension.governance_control_report import render_governance_markdown

ROOT = Path(__file__).resolve().parents[2]


def _head_sha(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)

    payload = (
        json.loads(args.observations.read_text(encoding="utf-8"))
        if args.observations
        else {}
    )
    observed_at = datetime.fromisoformat(
        str(payload.get("observed_at") or datetime.now(UTC).isoformat()).replace(
            "Z", "+00:00"
        )
    )
    report = governance_control_index(
        [package.contract for package in discover_packages(args.repo_root.resolve())],
        target_sha=str(payload.get("target_sha") or _head_sha(args.repo_root)),
        detector_observations=[
            DetectorObservation.model_validate(item)
            for item in payload.get("detectors", [])
        ],
        proof_observations=[
            ProofObservation.model_validate(item) for item in payload.get("proofs", [])
        ],
        enforcement_observations=[
            EnforcementObservation.model_validate(item)
            for item in payload.get("enforcement", [])
        ],
        issue_observations=[
            IssueObservation.model_validate(item) for item in payload.get("issues", [])
        ],
        observed_at=observed_at,
    )
    rendered_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    rendered_markdown = render_governance_markdown(report)
    if args.json_out:
        args.json_out.write_text(rendered_json, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(rendered_markdown, encoding="utf-8")
    if not args.json_out and not args.markdown_out:
        print(rendered_markdown, end="")
    return 0


__all__ = ["main"]
