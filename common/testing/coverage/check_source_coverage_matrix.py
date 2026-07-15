#!/usr/bin/env python3
"""Validate source coverage matrix for product trust."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MATRIX = (
    REPO_ROOT / "common" / "testing" / "data" / "source-coverage-matrix.yaml"
)
VALID_PROOF_LEVELS = {"pr_deterministic", "post_merge_llm_ocr", "manual_trusted", "gap"}
ISSUE_RE = re.compile(r"^#\d+$")
EPIC_RE = re.compile(r"^EPIC-\d{3}$")


@dataclass
class SourceCoverageResult:
    source_id: str
    proof_levels: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _load(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _validate_source(source: dict[str, Any], repo_root: Path) -> SourceCoverageResult:
    source_id = str(source.get("id", ""))
    errors: list[str] = []
    raw_proof_levels = source.get("proof_levels", [])
    proof_levels = (
        [str(level) for level in raw_proof_levels]
        if isinstance(raw_proof_levels, list)
        else []
    )

    required = {
        "id",
        "owner_epics",
        "supported_formats",
        "supported_institutions",
        "proof_levels",
        "ingestion_path",
        "review_requirement",
        "traceability_target",
        "test_anchors",
    }
    missing = sorted(required - set(source))
    if missing:
        errors.append(
            f"{source_id or '<missing id>'}: missing keys: {', '.join(missing)}"
        )

    if not source_id:
        errors.append("source class missing id")
    owner_epics = source.get("owner_epics", [])
    if not isinstance(owner_epics, list) or not owner_epics:
        errors.append(f"{source_id}: owner_epics must be a non-empty list")
    else:
        for epic in owner_epics:
            if not EPIC_RE.fullmatch(str(epic)):
                errors.append(f"{source_id}: invalid owner EPIC {epic!r}")
            elif not sorted((repo_root / "docs" / "project").glob(f"{epic}.*.md")):
                errors.append(f"{source_id}: owner EPIC does not exist: {epic}")

    if "proof_levels" in source and not isinstance(raw_proof_levels, list):
        errors.append(f"{source_id}: proof_levels must be a list")
    elif not proof_levels:
        errors.append(f"{source_id}: proof_levels must be non-empty")
    unknown = sorted(set(proof_levels) - VALID_PROOF_LEVELS)
    if unknown:
        errors.append(f"{source_id}: unknown proof levels: {', '.join(unknown)}")
    if "gap" in proof_levels and not ISSUE_RE.fullmatch(
        str(source.get("gap_issue", ""))
    ):
        errors.append(f"{source_id}: gap proof level requires gap_issue like #696")
    if (
        proof_levels == ["post_merge_llm_ocr"]
        and source.get("requires_pr_deterministic_mirror") is not False
    ):
        errors.append(f"{source_id}: post_merge_llm_ocr cannot be the only proof level")

    anchors = source.get("test_anchors", [])
    if not isinstance(anchors, list) or not anchors:
        errors.append(f"{source_id}: test_anchors must be a non-empty list")
    else:
        for anchor in anchors:
            file_name = str(anchor).split("::", 1)[0]
            if not (repo_root / file_name).exists():
                errors.append(
                    f"{source_id}: test anchor file does not exist: {file_name}"
                )

    return SourceCoverageResult(
        source_id=source_id, proof_levels=proof_levels, errors=errors
    )


def validate_source_coverage(
    repo_root: Path, matrix_path: Path
) -> list[SourceCoverageResult]:
    payload = _load(matrix_path)
    raw_required_classes = payload.get("required_source_classes", [])
    required_classes = (
        [str(item) for item in raw_required_classes]
        if isinstance(raw_required_classes, list)
        else []
    )
    sources = payload.get("source_classes", [])
    results: list[SourceCoverageResult] = []
    matrix_shape_errors: list[str] = []
    if "required_source_classes" in payload and not isinstance(
        raw_required_classes, list
    ):
        matrix_shape_errors.append("required_source_classes must be a list")
    if not isinstance(sources, list):
        matrix_shape_errors.append("source_classes must be a list")
        return [SourceCoverageResult("__matrix__", errors=matrix_shape_errors)]

    by_id: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            results.append(
                SourceCoverageResult(
                    "__source__", errors=["source entry must be a mapping"]
                )
            )
            continue
        source_id = str(source.get("id", ""))
        if source_id in by_id:
            duplicates.add(source_id)
        by_id[source_id] = source
        results.append(_validate_source(source, repo_root))

    missing = sorted(set(required_classes) - set(by_id))
    unknown = sorted(set(by_id) - set(required_classes))
    global_errors: list[str] = []
    if missing:
        global_errors.append(f"missing required source classes: {', '.join(missing)}")
    if unknown:
        global_errors.append(f"unknown source classes: {', '.join(unknown)}")
    if duplicates:
        global_errors.append(
            f"duplicate source classes: {', '.join(sorted(duplicates))}"
        )
    global_errors = matrix_shape_errors + global_errors
    if global_errors:
        results.append(SourceCoverageResult("__matrix__", errors=global_errors))
    return results


def render_report(results: list[SourceCoverageResult]) -> str:
    errors = [error for result in results for error in result.errors]
    lines = [
        "# Source Coverage Matrix Report",
        "",
        "| Source | Proof levels | Validation |",
        "|---|---|---|",
    ]
    for result in results:
        if result.source_id.startswith("__") and not result.errors:
            continue
        lines.append(
            f"| `{result.source_id}` | {', '.join(result.proof_levels) or '-'} | "
            f"{'fail' if result.errors else 'ok'} |"
        )
    lines.extend(["", "## Errors", ""])
    lines.extend(f"- {error}" for error in errors) if errors else lines.append(
        "No source coverage errors found."
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate source coverage matrix.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    matrix_path = args.matrix if args.matrix.is_absolute() else repo_root / args.matrix
    results = validate_source_coverage(repo_root, matrix_path)
    report = render_report(results)
    print(report)
    errors = [error for result in results for error in result.errors]
    if errors:
        for error in errors:
            print(f"::error title=Source coverage matrix::{error}", file=sys.stderr)
        return 1
    print(
        f"Source coverage matrix passed: {len([result for result in results if not result.source_id.startswith('__')])} source class(es) validated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
