#!/usr/bin/env python3
"""Pure validation library for the critical product proof matrix.

This is intentionally smaller than full AC traceability. It protects the core
product journeys from being "covered" only by broad AC string references while
broad registry hygiene stays with ``check_ac_traceability.run_traceability``.

This module is a LIBRARY, not a CLI gate. ``validate_matrix_contract`` /
``validate_matrix`` / ``validate_outcomes`` (and the ``build_matrix_payload``
helper) are imported by the single consolidated gate
(:mod:`common.testing.check_ac_index`, Gate A) and by the matrix unit tests. There
is no ``main()`` / argument parser / markdown report renderer here any more: the
one gate entry point is ``tools/check_ac_index.py``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common.testing.ac_registry_format import load_registry_entries
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
BEHAVIORAL_ROOTS = (
    "apps/backend/tests/",
    "apps/frontend/src/",
    "tests/e2e/",
)
BROAD_CONTRACT_DENYLIST = {
    "tests/tooling/test_issue_459_infra_contracts.py",
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
        return [error for result in [*self.proofs, *self.outcomes] for error in result.errors]


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


def _epic_path(repo_root: Path, epic_id: str) -> Path | None:
    matches = sorted((repo_root / "docs" / "project").glob(f"{epic_id}.*.md"))
    return matches[0] if matches else None


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_outcome_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def _readme_outcome_ids(text: str) -> tuple[list[str], list[str]]:
    """Extract the README Core Proof Paths outcome table."""
    lines = text.splitlines()
    table_start: int | None = None
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.lower() for cell in _markdown_cells(line)]
        if cells and cells[0] == "outcome id":
            table_start = index + 1
            break

    if table_start is None:
        return [], ["README.md missing parseable macro outcome table with `Outcome ID` header"]

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
        if not first or set(first) <= {"-", ":"}:
            continue
        ids.append(first)

    if not ids:
        return ids, ["README.md macro outcome table has no outcome rows"]
    return ids, []


def _macro_ownership_section(text: str) -> str | None:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if re.fullmatch(r"#{2,6}\s+Macro Proof Ownership\s*", line.strip()):
            start = index + 1
            break
    if start is None:
        return None

    collected: list[str] = []
    for line in lines[start:]:
        if re.match(r"^#{2,6}\s+", line):
            break
        collected.append(line)
    return "\n".join(collected)


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
    trust_mode = str(proof.get("trust_mode", ""))
    source_classes = [str(source_class) for source_class in proof.get("source_classes", [])]
    mirror_proof_id = str(proof.get("mirror_proof_id", ""))
    rel_file = str(proof.get("file", ""))
    test_name = str(proof.get("test", ""))
    errors = list(shape_errors)

    if trust_mode:
        if trust_mode not in VALID_TRUST_MODES:
            errors.append(f"{proof_id}: invalid trust_mode {trust_mode!r}")
        if not source_classes:
            errors.append(f"{proof_id}: source_classes are required when trust_mode is set")
        if trust_mode == "llm_ocr_post_merge" and not mirror_proof_id:
            errors.append(f"{proof_id}: llm_ocr_post_merge proof requires mirror_proof_id")

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
            trust_mode=trust_mode,
            source_classes=source_classes,
            mirror_proof_id=mirror_proof_id,
            errors=errors,
        )

    path = repo_root / rel_file
    if "_ac_stubs" in path.parts:
        errors.append(f"{proof_id}: critical proof cannot point at _ac_stubs")
    if rel_file in BROAD_CONTRACT_DENYLIST:
        errors.append(f"{proof_id}: broad contract tests cannot satisfy critical proof")
    if scope == "behavioral" and not rel_file.startswith(BEHAVIORAL_ROOTS):
        errors.append(f"{proof_id}: behavioral proof must live under product test roots, got {rel_file}")
    if not path.exists():
        errors.append(f"{proof_id}: file does not exist: {rel_file}")
        return ProofResult(
            proof_id,
            scope,
            ci_tier,
            rel_file,
            test_name,
            ac_ids,
            "fail",
            trust_mode,
            source_classes,
            mirror_proof_id,
            errors,
        )

    anchor = _find_anchor(path, test_name)
    if anchor is None:
        errors.append(f"{proof_id}: test anchor not found: {test_name}")
        return ProofResult(
            proof_id,
            scope,
            ci_tier,
            rel_file,
            test_name,
            ac_ids,
            "fail",
            trust_mode,
            source_classes,
            mirror_proof_id,
            errors,
        )

    stable_refs = set(AC_PATTERN.findall(anchor.stable_text))
    file_refs = set(AC_PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
    missing_stable_refs = [ac_id for ac_id in ac_ids if ac_id not in stable_refs]
    for ac_id in missing_stable_refs:
        if ac_id in file_refs:
            errors.append(f"{proof_id}: {ac_id} is only a file/body reference; put it in the test name or docstring")
        else:
            errors.append(f"{proof_id}: {ac_id} is missing from the test name or docstring")

    required_markers = {str(marker) for marker in proof.get("required_markers", [])}
    missing_markers = sorted(required_markers - anchor.markers)
    if missing_markers:
        errors.append(f"{proof_id}: missing pytest markers on {test_name}: {', '.join(missing_markers)}")

    return ProofResult(
        proof_id=proof_id,
        scope=scope,
        ci_tier=ci_tier,
        file=rel_file,
        test=test_name,
        ac_ids=ac_ids,
        status="fail" if errors else scope,
        trust_mode=trust_mode,
        source_classes=source_classes,
        mirror_proof_id=mirror_proof_id,
        errors=errors,
    )


def validate_matrix(repo_root: Path, matrix: dict[str, Any]) -> list[ProofResult]:
    proofs = matrix.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        raise ValueError("critical proof matrix must define a non-empty proofs list")
    registry_ids = _load_registry_ids(repo_root)
    results = [
        _validate_proof(proof, repo_root=repo_root, registry_ids=registry_ids, index=index)
        for index, proof in enumerate(proofs)
        if isinstance(proof, dict)
    ]
    seen_proof_ids: set[str] = set()
    duplicate_proof_ids: set[str] = set()
    for result in results:
        if result.proof_id in seen_proof_ids:
            duplicate_proof_ids.add(result.proof_id)
        seen_proof_ids.add(result.proof_id)
    if duplicate_proof_ids:
        results.append(
            ProofResult(
                proof_id="__matrix__",
                scope="static_contract",
                ci_tier="pr_ci",
                trust_mode="",
                source_classes=[],
                file="",
                test="",
                ac_ids=[],
                status="fail",
                mirror_proof_id="",
                errors=["critical proof matrix duplicate proof ids: " + ", ".join(sorted(duplicate_proof_ids))],
            )
        )
    by_id = {result.proof_id: result for result in results}
    for result in results:
        if not result.mirror_proof_id:
            continue
        mirror = by_id.get(result.mirror_proof_id)
        if mirror is None:
            result.errors.append(f"{result.proof_id}: unknown mirror_proof_id {result.mirror_proof_id}")
            continue
        if mirror.trust_mode != "deterministic_pr" or mirror.ci_tier != "pr_ci":
            result.errors.append(
                f"{result.proof_id}: mirror proof {result.mirror_proof_id} must be deterministic_pr in pr_ci"
            )
        missing_classes = sorted(set(result.source_classes) - set(mirror.source_classes))
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
    owner_epics = [str(epic) for epic in raw_owner_epics] if isinstance(raw_owner_epics, list) else []
    proof_ids = [str(proof_id) for proof_id in raw_proof_ids] if isinstance(raw_proof_ids, list) else []
    issue = str(outcome.get("issue", ""))
    errors: list[str] = []

    required = {"id", "status", "owner_epics"}
    missing = sorted(required - set(outcome))
    if missing:
        errors.append(f"{outcome_id}: missing required outcome keys: {', '.join(missing)}")

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

        epic_text = epic_path.read_text(encoding="utf-8", errors="ignore")
        ownership_section = _macro_ownership_section(epic_text)
        if ownership_section is None:
            errors.append(f"{outcome_id}: owner EPIC {epic_id} missing `## Macro Proof Ownership` section")
        elif outcome_id not in ownership_section:
            errors.append(f"{outcome_id}: owner EPIC {epic_id} missing macro outcome declaration")

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


def _validate_readme_contract(repo_root: Path, outcomes: list[OutcomeResult]) -> OutcomeResult:
    readme_path = repo_root / "README.md"
    errors: list[str] = []
    text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    if not text:
        errors.append("README.md missing")
    if "## Core Proof Paths" not in text:
        errors.append("README.md missing `## Core Proof Paths` section")
    # The critical proof matrix is now a derived (not committed) view of the one
    # AC-keyed graph; the README links the source-of-truth model and gate
    # instead of the retired committed YAML.
    if "docs/ssot/critical-proof-outcomes.yaml" not in text:
        errors.append("README.md missing critical proof outcomes source link")
    if "tools/check_ac_index.py" not in text:
        errors.append("README.md missing AC index consistency gate command")

    matrix_ids = [outcome.outcome_id for outcome in outcomes if not outcome.outcome_id.startswith("__")]
    readme_ids, table_errors = _readme_outcome_ids(text)
    errors.extend(table_errors)

    seen: set[str] = set()
    duplicate_ids: set[str] = set()
    for outcome_id in readme_ids:
        if outcome_id in seen:
            duplicate_ids.add(outcome_id)
        seen.add(outcome_id)
    if duplicate_ids:
        errors.append(f"README macro outcomes duplicate ids: {', '.join(sorted(duplicate_ids))}")

    matrix_set = set(matrix_ids)
    readme_set = set(readme_ids)
    missing = sorted(matrix_set - readme_set)
    unknown = sorted(readme_set - matrix_set)
    if missing:
        errors.append(f"README macro outcomes missing ids: {', '.join(missing)}")
    if unknown:
        errors.append(f"README macro outcomes include unknown ids: {', '.join(unknown)}")

    for outcome in outcomes:
        if outcome.outcome_id.startswith("__"):
            continue
        if outcome.outcome_id not in text:
            errors.append(f"README.md missing macro outcome id `{outcome.outcome_id}`")

    return OutcomeResult(
        outcome_id="__readme_contract__",
        status="contract",
        owner_epics=[],
        proof_ids=[],
        issue="",
        errors=errors,
    )


def validate_outcomes(
    repo_root: Path,
    matrix_payload: dict[str, Any],
    proof_results: list[ProofResult],
) -> list[OutcomeResult]:
    raw_outcomes = matrix_payload.get("outcomes")
    if not isinstance(raw_outcomes, list) or not raw_outcomes:
        return [
            OutcomeResult(
                outcome_id="__macro_outcomes__",
                status="fail",
                owner_epics=[],
                proof_ids=[],
                issue="",
                errors=["critical proof matrix must define a non-empty outcomes list"],
            )
        ]

    proof_by_id = {proof.proof_id: proof for proof in proof_results}
    outcomes: list[OutcomeResult] = []
    for index, outcome in enumerate(raw_outcomes):
        if not isinstance(outcome, dict):
            outcomes.append(
                OutcomeResult(
                    outcome_id=f"__outcome_{index}__",
                    status="fail",
                    owner_epics=[],
                    proof_ids=[],
                    issue="",
                    errors=[f"outcome[{index}] must be a mapping"],
                )
            )
            continue
        outcomes.append(
            _validate_outcome(
                outcome,
                repo_root=repo_root,
                proof_by_id=proof_by_id,
                index=index,
            )
        )

    seen: set[str] = set()
    duplicates: set[str] = set()
    for outcome in outcomes:
        if outcome.outcome_id.startswith("__"):
            continue
        if outcome.outcome_id in seen:
            duplicates.add(outcome.outcome_id)
        seen.add(outcome.outcome_id)

    missing = sorted(REQUIRED_OUTCOME_IDS - seen)
    unknown = sorted(seen - REQUIRED_OUTCOME_IDS)
    global_errors: list[str] = []
    if duplicates:
        global_errors.append(f"macro outcomes duplicate ids: {', '.join(sorted(duplicates))}")
    if missing:
        global_errors.append(f"macro outcomes missing required ids: {', '.join(missing)}")
    if unknown:
        global_errors.append(f"macro outcomes include unknown ids: {', '.join(unknown)}")
    if global_errors:
        outcomes.append(
            OutcomeResult(
                outcome_id="__macro_outcomes__",
                status="fail",
                owner_epics=[],
                proof_ids=[],
                issue="",
                errors=global_errors,
            )
        )

    readme_contract = _validate_readme_contract(repo_root, outcomes)
    if readme_contract.errors:
        outcomes.append(readme_contract)
    return outcomes


def build_matrix_payload(repo_root: Path) -> dict[str, Any]:
    """Build the critical proof matrix payload in-memory from the AC graph.

    The matrix is a DERIVED view of the one AC-keyed graph (see
    ``common.testing.ac_graph``); it is never committed-materialized, so the
    validator reads the freshly-built payload instead of a checked-in file.

    Only the proofs + outcomes drive the matrix payload, so this routes through
    the lightweight ``build_proofs_only`` path — skipping the AC-reference scan
    and the vision build that the full graph performs. The payload (and thus all
    downstream validation) is identical to the full-graph build, only faster.
    """
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_proofs_only(repo_root))


def validate_matrix_contract(repo_root: Path, matrix_payload: dict[str, Any] | None = None) -> MatrixValidation:
    if matrix_payload is None:
        matrix_payload = build_matrix_payload(repo_root)
    proofs = validate_matrix(repo_root, matrix_payload)
    outcomes = validate_outcomes(repo_root, matrix_payload, proofs)
    return MatrixValidation(proofs=proofs, outcomes=outcomes)
