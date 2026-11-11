#!/usr/bin/env python3
"""Pure validation library for the critical product proof matrix."""

from __future__ import annotations

import ast
import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common.meta.base.gate_util import (
    display_path,
    duplicate_values,
    markdown_table_cells,
    parse_ast_cached,
    pytest_decorator_markers,
    read_text_cached,
)
from common.meta.extension.generate_ac_registry import load_registry_entries
from common.testing.ac_traceability_refs import AC_PATTERN

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATHS = (
    REPO_ROOT / "docs" / "ac_registry.yaml",
    REPO_ROOT / "docs" / "infra_registry.yaml",
)

VALID_SCOPES = {"behavioral", "static_contract", "manual_gate"}
VALID_CI_TIERS = {"pr_ci", "post_merge_environment", "manual"}
VALID_OUTCOME_STATUSES = {"covered", "partial", "gap"}
VALID_TRUST_MODES = {"deterministic_pr", "llm_ocr_post_merge", "hybrid"}
REQUIRED_OUTCOME_IDS = {
    "personal-financial-report-package",
    "asset-distribution-net-worth",
    "monthly-income-spending",
    "investment-performance",
    "annualized-income-long-term",
    "source-ledger-report-traceability",
}
ISSUE_RE = re.compile(r"^#\d+$")
EPIC_RE = re.compile(r"^EPIC-\d{3}$")
BEHAVIORAL_ROOTS = ("apps/backend/tests/", "apps/frontend/src/", "tests/e2e/")
BROAD_CONTRACT_DENYLIST = {"tests/tooling/test_issue_459_infra_contracts.py"}
TEST_CALL_RE = re.compile(
    r"\b(?:it|test)\s*(?:\.\w+)?\s*\(\s*(['\"`])(?P<title>.*?)(?<!\\)\1",
    re.DOTALL,
)

_markdown_cells = markdown_table_cells
_decorator_markers = pytest_decorator_markers


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
    trust_mode: str = ""
    source_classes: list[str] = field(default_factory=list)
    mirror_proof_id: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class OutcomeResult:
    outcome_id: str
    status: str
    owner_epics: list[str]
    proof_ids: list[str]
    issue: str
    errors: list[str] = field(default_factory=list)


@dataclass
class MatrixValidation:
    proofs: list[ProofResult]
    outcomes: list[OutcomeResult]

    @property
    def errors(self) -> list[str]:
        return [err for item in [*self.proofs, *self.outcomes] for err in item.errors]


def _empty_outcome(
    outcome_id: str, errors: list[str], status: str = "fail"
) -> OutcomeResult:
    return OutcomeResult(
        outcome_id=outcome_id,
        status=status,
        owner_epics=[],
        proof_ids=[],
        issue="",
        errors=errors,
    )


def _load_registry_ids(repo_root: Path) -> set[str]:
    return {
        str(entry["id"])
        for default_path in REGISTRY_PATHS
        for entry in load_registry_entries(
            repo_root / display_path(default_path, REPO_ROOT)
        )
    }


def _load_matrix(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _epic_path(repo_root: Path, epic_id: str) -> Path | None:
    matches = sorted((repo_root / "docs" / "project").glob(f"{epic_id}.*.md"))
    return matches[0] if matches else None


def _normalize_outcome_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def _readme_outcome_ids(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    table_start = next(
        (
            idx + 1
            for idx, line in enumerate(lines)
            if line.lstrip().startswith("|")
            and (_markdown_cells(line) or [""])[0].lower() == "outcome id"
        ),
        None,
    )
    if table_start is None:
        return [], [
            "README.md missing parseable macro outcome table with `Outcome ID` header"
        ]

    ids: list[str] = []
    for line in lines[table_start:]:
        if not line.lstrip().startswith("|"):
            if ids:
                break
            continue
        cells = _markdown_cells(line)
        if not cells:
            continue
        first = _normalize_outcome_cell(cells[0])
        if first and not (set(first) <= {"-", ":"}):
            ids.append(first)

    return (
        (ids, [])
        if ids
        else (ids, ["README.md macro outcome table has no outcome rows"])
    )


def _macro_ownership_section(text: str) -> str | None:
    lines = text.splitlines()
    start = next(
        (
            idx + 1
            for idx, line in enumerate(lines)
            if re.fullmatch(r"#{2,6}\s+Macro Proof Ownership\s*", line.strip())
        ),
        None,
    )
    if start is None:
        return None
    collected: list[str] = []
    for line in lines[start:]:
        if re.match(r"^#{2,6}\s+", line):
            break
        collected.append(line)
    return "\n".join(collected)


def _python_anchors(path: Path) -> dict[str, TestAnchor]:
    anchors: dict[str, TestAnchor] = {}
    try:
        module = parse_ast_cached(path)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return anchors
    for node in ast.walk(module):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name not in anchors
        ):
            doc = ast.get_docstring(node) or ""
            anchors[node.name] = TestAnchor(
                stable_text=f"{node.name}\n{doc}",
                markers=_decorator_markers(node),
            )
    return anchors


def _typescript_anchors(path: Path) -> dict[str, TestAnchor]:
    anchors: dict[str, TestAnchor] = {}
    try:
        text = read_text_cached(path)
    except (UnicodeDecodeError, OSError):
        return anchors
    for match in TEST_CALL_RE.finditer(text):
        title = match.group("title")
        anchors.setdefault(title, TestAnchor(stable_text=title))
    return anchors


@functools.lru_cache(maxsize=1024)
def _cached_file_anchors(
    path_str: str, mtime_ns: int, size: int
) -> dict[str, TestAnchor]:
    path = Path(path_str)
    if path.suffix == ".py":
        return _python_anchors(path)
    if path.suffix in {".ts", ".tsx"}:
        return _typescript_anchors(path)
    return {}


def _find_anchor(path: Path, test_name: str) -> TestAnchor | None:
    try:
        resolved = path.resolve()
        st = resolved.stat()
    except OSError:
        return None
    return _cached_file_anchors(str(resolved), st.st_mtime_ns, st.st_size).get(
        test_name
    )


def _validate_shape(proof: dict[str, Any], index: int) -> list[str]:
    missing = sorted({"id", "scope", "ci_tier", "ac_ids"} - set(proof))
    if missing:
        return [f"proof[{index}] missing required keys: {', '.join(missing)}"]
    errors: list[str] = []
    pid = proof["id"]
    if proof["scope"] not in VALID_SCOPES:
        errors.append(f"{pid}: invalid scope {proof['scope']!r}")
    if proof["ci_tier"] not in VALID_CI_TIERS:
        errors.append(f"{pid}: invalid ci_tier {proof['ci_tier']!r}")
    if not isinstance(proof.get("ac_ids"), list) or not proof["ac_ids"]:
        errors.append(f"{pid}: ac_ids must be a non-empty list")
    if proof["scope"] != "manual_gate":
        for key in ("file", "test"):
            if not proof.get(key):
                errors.append(f"{pid}: {key} is required for {proof['scope']}")
    elif not proof.get("evidence"):
        errors.append(f"{pid}: evidence is required for manual_gate")
    return errors


def _validate_proof(
    proof: dict[str, Any],
    *,
    repo_root: Path,
    registry_ids: set[str],
    index: int,
) -> ProofResult:
    errors = _validate_shape(proof, index)
    proof_id = str(proof.get("id", f"proof[{index}]"))
    scope = str(proof.get("scope", ""))
    ci_tier = str(proof.get("ci_tier", ""))
    ac_ids = [str(ac_id) for ac_id in proof.get("ac_ids", [])]
    trust_mode = str(proof.get("trust_mode", ""))
    source_classes = [str(sc) for sc in proof.get("source_classes", [])]
    mirror_proof_id = str(proof.get("mirror_proof_id", ""))
    rel_file = str(proof.get("file", ""))
    test_name = str(proof.get("test", ""))

    def _result(status: str) -> ProofResult:
        return ProofResult(
            proof_id=proof_id,
            scope=scope,
            ci_tier=ci_tier,
            file=rel_file,
            test=test_name,
            ac_ids=ac_ids,
            status=status,
            trust_mode=trust_mode,
            source_classes=source_classes,
            mirror_proof_id=mirror_proof_id,
            errors=errors,
        )

    if trust_mode:
        if trust_mode not in VALID_TRUST_MODES:
            errors.append(f"{proof_id}: invalid trust_mode {trust_mode!r}")
        if not source_classes:
            errors.append(
                f"{proof_id}: source_classes are required when trust_mode is set"
            )
        if trust_mode == "llm_ocr_post_merge" and not mirror_proof_id:
            errors.append(
                f"{proof_id}: llm_ocr_post_merge proof requires mirror_proof_id"
            )

    for ac_id in ac_ids:
        if ac_id not in registry_ids:
            errors.append(f"{proof_id}: unknown AC id {ac_id}")

    if scope == "manual_gate":
        return _result("fail" if errors else "manual")

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
        return _result("fail")

    anchor = _find_anchor(path, test_name)
    if anchor is None:
        errors.append(f"{proof_id}: test anchor not found: {test_name}")
        return _result("fail")

    stable_refs = set(AC_PATTERN.findall(anchor.stable_text))
    missing_stable = [ac_id for ac_id in ac_ids if ac_id not in stable_refs]
    if missing_stable:
        file_refs = set(
            AC_PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore"))
        )
        for ac_id in missing_stable:
            suffix = (
                "is only a file/body reference; put it in the test name or docstring"
                if ac_id in file_refs
                else "is missing from the test name or docstring"
            )
            errors.append(f"{proof_id}: {ac_id} {suffix}")

    required_markers = {str(marker) for marker in proof.get("required_markers", [])}
    missing_markers = sorted(required_markers - anchor.markers)
    if missing_markers:
        errors.append(
            f"{proof_id}: missing pytest markers on {test_name}: {', '.join(missing_markers)}"
        )

    return _result("fail" if errors else scope)


def validate_matrix(repo_root: Path, matrix: dict[str, Any]) -> list[ProofResult]:
    proofs = matrix.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        raise ValueError("critical proof matrix must define a non-empty proofs list")
    registry_ids = _load_registry_ids(repo_root)
    results = [
        _validate_proof(
            proof, repo_root=repo_root, registry_ids=registry_ids, index=idx
        )
        for idx, proof in enumerate(proofs)
        if isinstance(proof, dict)
    ]
    duplicate_proof_ids = duplicate_values([r.proof_id for r in results])
    if duplicate_proof_ids:
        results.append(
            ProofResult(
                proof_id="__matrix__",
                scope="static_contract",
                ci_tier="pr_ci",
                file="",
                test="",
                ac_ids=[],
                status="fail",
                errors=[
                    "critical proof matrix duplicate proof ids: "
                    + ", ".join(duplicate_proof_ids)
                ],
            )
        )
    by_id = {result.proof_id: result for result in results}
    for result in results:
        if not result.mirror_proof_id:
            continue
        mirror = by_id.get(result.mirror_proof_id)
        if mirror is None:
            result.errors.append(
                f"{result.proof_id}: unknown mirror_proof_id {result.mirror_proof_id}"
            )
            continue
        if mirror.trust_mode != "deterministic_pr" or mirror.ci_tier != "pr_ci":
            result.errors.append(
                f"{result.proof_id}: mirror proof {result.mirror_proof_id} must be deterministic_pr in pr_ci"
            )
        missing_classes = sorted(
            set(result.source_classes) - set(mirror.source_classes)
        )
        if missing_classes:
            result.errors.append(
                f"{result.proof_id}: mirror proof {result.mirror_proof_id} missing source classes: {', '.join(missing_classes)}"
            )
    return results


def _validate_outcome(
    outcome: dict[str, Any],
    *,
    repo_root: Path,
    proof_by_id: dict[str, ProofResult],
    index: int,
) -> OutcomeResult:
    outcome_id = str(outcome.get("id", f"outcome[{index}]"))
    status = str(outcome.get("status", ""))
    raw_owner_epics = outcome.get("owner_epics", [])
    raw_proof_ids = outcome.get("proof_ids", [])
    owner_epics = (
        [str(e) for e in raw_owner_epics] if isinstance(raw_owner_epics, list) else []
    )
    proof_ids = (
        [str(p) for p in raw_proof_ids] if isinstance(raw_proof_ids, list) else []
    )
    issue = str(outcome.get("issue", ""))
    errors: list[str] = []

    missing = sorted({"id", "status", "owner_epics"} - set(outcome))
    if missing:
        errors.append(
            f"{outcome_id}: missing required outcome keys: {', '.join(missing)}"
        )
    if status not in VALID_OUTCOME_STATUSES:
        errors.append(f"{outcome_id}: invalid status {status!r}")
    if not isinstance(raw_owner_epics, list) or not owner_epics:
        errors.append(f"{outcome_id}: owner_epics must be a non-empty list")
    if "proof_ids" in outcome and not isinstance(raw_proof_ids, list):
        errors.append(f"{outcome_id}: proof_ids must be a list")

    for epic_id in owner_epics:
        if not EPIC_RE.fullmatch(epic_id):
            errors.append(f"{outcome_id}: invalid owner EPIC id {epic_id!r}")
            continue
        epic_path = _epic_path(repo_root, epic_id)
        if epic_path is None:
            errors.append(f"{outcome_id}: owner EPIC does not exist: {epic_id}")
            continue
        ownership = _macro_ownership_section(
            epic_path.read_text(encoding="utf-8", errors="ignore")
        )
        if ownership is None:
            errors.append(
                f"{outcome_id}: owner EPIC {epic_id} missing `## Macro Proof Ownership` section"
            )
        elif outcome_id not in ownership:
            errors.append(
                f"{outcome_id}: owner EPIC {epic_id} missing macro outcome declaration"
            )

    if status == "covered" and not proof_ids:
        errors.append(f"{outcome_id}: covered outcome requires at least one proof_id")
    if status in {"partial", "gap"} and not ISSUE_RE.fullmatch(issue):
        errors.append(f"{outcome_id}: {status} outcome requires issue like #521")
    if issue and not ISSUE_RE.fullmatch(issue):
        errors.append(f"{outcome_id}: invalid issue reference {issue!r}")

    for proof_id in proof_ids:
        proof = proof_by_id.get(proof_id)
        if proof is None:
            errors.append(f"{outcome_id}: unknown proof_id {proof_id}")
            continue
        if proof.errors:
            errors.append(f"{outcome_id}: proof {proof_id} has validation errors")
        if proof.scope != "behavioral" or not proof.file.startswith("tests/e2e/"):
            errors.append(f"{outcome_id}: proof {proof_id} must be behavioral E2E")

    return OutcomeResult(
        outcome_id=outcome_id,
        status=status,
        owner_epics=owner_epics,
        proof_ids=proof_ids,
        issue=issue,
        errors=errors,
    )


def _validate_readme_contract(
    repo_root: Path, outcomes: list[OutcomeResult]
) -> OutcomeResult:
    readme_path = repo_root / "README.md"
    errors: list[str] = []
    text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    if not text:
        errors.append("README.md missing")
    for token, msg in (
        ("## Core Proof Paths", "README.md missing `## Core Proof Paths` section"),
        (
            "common/testing/data/critical-proof-outcomes.yaml",
            "README.md missing critical proof outcomes source link",
        ),
        (
            "tools/check_ac_index.py",
            "README.md missing AC index consistency gate command",
        ),
    ):
        if token not in text:
            errors.append(msg)

    matrix_ids = [o.outcome_id for o in outcomes if not o.outcome_id.startswith("__")]
    readme_ids, table_errors = _readme_outcome_ids(text)
    errors.extend(table_errors)

    duplicate_ids = duplicate_values(readme_ids)
    if duplicate_ids:
        errors.append(
            f"README macro outcomes duplicate ids: {', '.join(duplicate_ids)}"
        )

    matrix_set, readme_set = set(matrix_ids), set(readme_ids)
    missing = sorted(matrix_set - readme_set)
    unknown = sorted(readme_set - matrix_set)
    if missing:
        errors.append(f"README macro outcomes missing ids: {', '.join(missing)}")
    if unknown:
        errors.append(
            f"README macro outcomes include unknown ids: {', '.join(unknown)}"
        )

    for outcome_id in matrix_ids:
        if outcome_id not in text:
            errors.append(f"README.md missing macro outcome id `{outcome_id}`")

    return _empty_outcome("__readme_contract__", errors, status="contract")


def validate_outcomes(
    repo_root: Path,
    matrix_payload: dict[str, Any],
    proof_results: list[ProofResult],
) -> list[OutcomeResult]:
    raw_outcomes = matrix_payload.get("outcomes")
    if not isinstance(raw_outcomes, list) or not raw_outcomes:
        return [
            _empty_outcome(
                "__macro_outcomes__",
                ["critical proof matrix must define a non-empty outcomes list"],
            )
        ]

    proof_by_id = {proof.proof_id: proof for proof in proof_results}
    outcomes = [
        _validate_outcome(
            outcome, repo_root=repo_root, proof_by_id=proof_by_id, index=idx
        )
        if isinstance(outcome, dict)
        else _empty_outcome(f"__outcome_{idx}__", [f"outcome[{idx}] must be a mapping"])
        for idx, outcome in enumerate(raw_outcomes)
    ]

    declared_ids = [o.outcome_id for o in outcomes if not o.outcome_id.startswith("__")]
    duplicates = duplicate_values(declared_ids)
    seen = set(declared_ids)
    missing = sorted(REQUIRED_OUTCOME_IDS - seen)
    unknown = sorted(seen - REQUIRED_OUTCOME_IDS)
    global_errors: list[str] = []
    if duplicates:
        global_errors.append(f"macro outcomes duplicate ids: {', '.join(duplicates)}")
    if missing:
        global_errors.append(
            f"macro outcomes missing required ids: {', '.join(missing)}"
        )
    if unknown:
        global_errors.append(
            f"macro outcomes include unknown ids: {', '.join(unknown)}"
        )
    if global_errors:
        outcomes.append(_empty_outcome("__macro_outcomes__", global_errors))

    readme_contract = _validate_readme_contract(repo_root, outcomes)
    if readme_contract.errors:
        outcomes.append(readme_contract)
    return outcomes


def build_matrix_payload(repo_root: Path) -> dict[str, Any]:
    """Build the critical proof matrix payload in-memory from the AC graph."""
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_proofs_only(repo_root))


def validate_matrix_contract(
    repo_root: Path, matrix_payload: dict[str, Any] | None = None
) -> MatrixValidation:
    if matrix_payload is None:
        matrix_payload = build_matrix_payload(repo_root)
    proofs = validate_matrix(repo_root, matrix_payload)
    outcomes = validate_outcomes(repo_root, matrix_payload, proofs)
    return MatrixValidation(proofs=proofs, outcomes=outcomes)
