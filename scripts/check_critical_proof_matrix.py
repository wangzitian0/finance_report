#!/usr/bin/env python3
"""Validate the critical product proof matrix.

This is intentionally smaller than full AC traceability. It protects the core
product journeys from being "covered" only by broad AC string references while
leaving broad registry hygiene to scripts/check_ac_traceability.py.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ac_registry_format import load_registry_entries
from ac_traceability_refs import AC_PATTERN

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MATRIX = REPO_ROOT / "docs" / "ssot" / "critical-proof-matrix.yaml"
DEFAULT_REPORT = REPO_ROOT / "docs" / "analysis" / "critical-proof-matrix-report.md"
REGISTRY_PATHS = (
    REPO_ROOT / "docs" / "ac_registry.yaml",
    REPO_ROOT / "docs" / "infra_registry.yaml",
)

VALID_SCOPES = {"behavioral", "static_contract", "manual_gate"}
VALID_CI_TIERS = {"pr_ci", "post_merge_environment", "manual"}
BEHAVIORAL_ROOTS = (
    "apps/backend/tests/",
    "apps/frontend/src/",
    "tests/e2e/",
)
BROAD_CONTRACT_DENYLIST = {
    "scripts/tests/test_issue_459_infra_contracts.py",
}
TEST_CALL_RE = re.compile(
    r"\b(?:it|test)\s*(?:\.\w+)?\s*\(\s*(['\"`])(?P<title>.*?)(?<!\\)\1",
    re.DOTALL,
)


@dataclass(frozen=True)
class TestAnchor:
    stable_text: str
    markers: set[str] = field(default_factory=set)


@dataclass
class ProofResult:
    proof_id: str
    scope: str
    ci_tier: str
    file: str
    test: str
    ac_ids: list[str]
    status: str
    errors: list[str] = field(default_factory=list)


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_registry_ids(repo_root: Path) -> set[str]:
    ids: set[str] = set()
    for default_path in REGISTRY_PATHS:
        registry_path = repo_root / _rel(default_path, REPO_ROOT)
        if not registry_path.exists():
            continue
        for entry in load_registry_entries(registry_path):
            ids.add(str(entry["id"]))
    return ids


def _load_matrix(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _decorator_markers(node: ast.AST) -> set[str]:
    markers: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        text = ast.unparse(decorator)
        prefix = "pytest.mark."
        if text.startswith(prefix):
            markers.add(text[len(prefix) :].split("(", 1)[0].split(".", 1)[0])
    return markers


def _python_anchor(path: Path, test_name: str) -> TestAnchor | None:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name != test_name:
            continue
        doc = ast.get_docstring(node) or ""
        stable_text = f"{node.name}\n{doc}"
        return TestAnchor(stable_text=stable_text, markers=_decorator_markers(node))
    return None


def _typescript_anchor(path: Path, test_name: str) -> TestAnchor | None:
    text = path.read_text(encoding="utf-8")
    for match in TEST_CALL_RE.finditer(text):
        title = match.group("title")
        if title == test_name:
            return TestAnchor(stable_text=title)
    return None


def _find_anchor(path: Path, test_name: str) -> TestAnchor | None:
    if path.suffix == ".py":
        return _python_anchor(path, test_name)
    if path.suffix in {".ts", ".tsx"}:
        return _typescript_anchor(path, test_name)
    return None


def _validate_shape(proof: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    required = {"id", "scope", "ci_tier", "ac_ids"}
    missing = sorted(required - set(proof))
    if missing:
        errors.append(f"proof[{index}] missing required keys: {', '.join(missing)}")
        return errors

    if proof["scope"] not in VALID_SCOPES:
        errors.append(f"{proof['id']}: invalid scope {proof['scope']!r}")
    if proof["ci_tier"] not in VALID_CI_TIERS:
        errors.append(f"{proof['id']}: invalid ci_tier {proof['ci_tier']!r}")
    if not isinstance(proof.get("ac_ids"), list) or not proof["ac_ids"]:
        errors.append(f"{proof['id']}: ac_ids must be a non-empty list")
    if proof["scope"] != "manual_gate":
        for key in ("file", "test"):
            if not proof.get(key):
                errors.append(f"{proof['id']}: {key} is required for {proof['scope']}")
    elif not proof.get("evidence"):
        errors.append(f"{proof['id']}: evidence is required for manual_gate")
    return errors


def _validate_proof(
    proof: dict[str, Any],
    *,
    repo_root: Path,
    registry_ids: set[str],
    index: int,
) -> ProofResult:
    shape_errors = _validate_shape(proof, index)
    proof_id = str(proof.get("id", f"proof[{index}]"))
    scope = str(proof.get("scope", ""))
    ci_tier = str(proof.get("ci_tier", ""))
    ac_ids = [str(ac_id) for ac_id in proof.get("ac_ids", [])]
    rel_file = str(proof.get("file", ""))
    test_name = str(proof.get("test", ""))
    errors = list(shape_errors)

    for ac_id in ac_ids:
        if ac_id not in registry_ids:
            errors.append(f"{proof_id}: unknown AC id {ac_id}")

    if scope == "manual_gate":
        return ProofResult(
            proof_id=proof_id,
            scope=scope,
            ci_tier=ci_tier,
            file=rel_file,
            test=test_name,
            ac_ids=ac_ids,
            status="fail" if errors else "manual",
            errors=errors,
        )

    path = repo_root / rel_file
    if "_ac_stubs" in path.parts:
        errors.append(f"{proof_id}: critical proof cannot point at _ac_stubs")
    if rel_file in BROAD_CONTRACT_DENYLIST:
        errors.append(f"{proof_id}: broad contract tests cannot satisfy critical proof")
    if scope == "behavioral" and not rel_file.startswith(BEHAVIORAL_ROOTS):
        errors.append(
            f"{proof_id}: behavioral proof must live under product test roots, got {rel_file}"
        )
    if not path.exists():
        errors.append(f"{proof_id}: file does not exist: {rel_file}")
        return ProofResult(proof_id, scope, ci_tier, rel_file, test_name, ac_ids, "fail", errors)

    anchor = _find_anchor(path, test_name)
    if anchor is None:
        errors.append(f"{proof_id}: test anchor not found: {test_name}")
        return ProofResult(proof_id, scope, ci_tier, rel_file, test_name, ac_ids, "fail", errors)

    stable_refs = set(AC_PATTERN.findall(anchor.stable_text))
    file_refs = set(AC_PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
    missing_stable_refs = [ac_id for ac_id in ac_ids if ac_id not in stable_refs]
    for ac_id in missing_stable_refs:
        if ac_id in file_refs:
            errors.append(
                f"{proof_id}: {ac_id} is only a file/body reference; put it in the test name or docstring"
            )
        else:
            errors.append(
                f"{proof_id}: {ac_id} is missing from the test name or docstring"
            )

    required_markers = {str(marker) for marker in proof.get("required_markers", [])}
    missing_markers = sorted(required_markers - anchor.markers)
    if missing_markers:
        errors.append(
            f"{proof_id}: missing pytest markers on {test_name}: {', '.join(missing_markers)}"
        )

    return ProofResult(
        proof_id=proof_id,
        scope=scope,
        ci_tier=ci_tier,
        file=rel_file,
        test=test_name,
        ac_ids=ac_ids,
        status="fail" if errors else scope,
        errors=errors,
    )


def validate_matrix(repo_root: Path, matrix_path: Path) -> list[ProofResult]:
    matrix = _load_matrix(matrix_path)
    proofs = matrix.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        raise ValueError(f"{matrix_path} must define a non-empty proofs list")
    registry_ids = _load_registry_ids(repo_root)
    return [
        _validate_proof(proof, repo_root=repo_root, registry_ids=registry_ids, index=index)
        for index, proof in enumerate(proofs)
        if isinstance(proof, dict)
    ]


def render_report(results: list[ProofResult]) -> str:
    counts = {scope: 0 for scope in sorted(VALID_SCOPES)}
    failed = 0
    for result in results:
        if result.errors:
            failed += 1
        elif result.scope in counts:
            counts[result.scope] += 1

    lines = [
        "# Critical Proof Matrix Report",
        "",
        "This report validates only core product proof paths. Full AC string",
        "traceability remains a separate hygiene gate.",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|---|---:|",
        f"| Behavioral proof | {counts['behavioral']} |",
        f"| Static/doc check | {counts['static_contract']} |",
        f"| Manual-only gate | {counts['manual_gate']} |",
        f"| Missing or reference-only | {failed} |",
        "",
        "## Proofs",
        "",
        "| ID | Scope | CI tier | AC IDs | Test anchor | Status |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        ac_cell = ", ".join(f"`{ac_id}`" for ac_id in result.ac_ids)
        anchor = f"`{result.file}::{result.test}`" if result.file else "_manual_"
        status = "fail" if result.errors else result.scope
        lines.append(
            f"| `{result.proof_id}` | {result.scope} | {result.ci_tier} | "
            f"{ac_cell} | {anchor} | {status} |"
        )

    errors = [error for result in results for error in result.errors]
    lines.extend(["", "## Errors", ""])
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("No critical proof matrix errors found.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate critical proof matrix.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    matrix_path = args.matrix if args.matrix.is_absolute() else repo_root / args.matrix
    results = validate_matrix(repo_root, matrix_path)
    report = render_report(results)

    output_path = args.output
    if output_path is not None:
        output_path = output_path if output_path.is_absolute() else repo_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"Wrote critical proof matrix report: {output_path}")
    else:
        print(report)

    errors = [error for result in results for error in result.errors]
    if errors:
        for error in errors:
            print(f"::error title=Critical proof matrix::{error}", file=sys.stderr)
        return 1
    print(f"Critical proof matrix passed: {len(results)} proof path(s) validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
