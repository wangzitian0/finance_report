#!/usr/bin/env python3
"""Pure validation library for AC test-reference traceability.

This module is a LIBRARY, not a CLI gate. Its functions are imported by the
single consolidated gate (:mod:`common.testing.check_ac_index`) — which calls
``run_traceability`` + ``traceability_failure_messages`` inside Gate A — and by
the traceability unit tests. There is no ``main()`` / argument parser / report
printer here any more: the one gate entry point is ``tools/check_ac_index.py``.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from common.testing.ac_traceability_refs import AC_PATTERN, classify_reference_file
from common.testing.test_surface import DEFAULT_AC_TEST_DIRS

try:
    from common.meta.extension.ac_registry_format import load_registry_entries
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class AC(NamedTuple):
    id: str
    epic: int
    epic_name: str
    description: str
    mandatory: bool


class TraceabilityResult(NamedTuple):
    covered: list[str]
    placeholder_only: list[str]
    stub_only: list[str]
    unexecuted_only: list[str]
    missing: list[str]
    total: int
    mandatory_total: int


@dataclass
class ACReferenceStats:
    real_files: set[str] = field(default_factory=set)
    ci_real_files: set[str] = field(default_factory=set)
    placeholder_files: set[str] = field(default_factory=set)
    stub_files: set[str] = field(default_factory=set)

    @property
    def all_files(self) -> set[str]:
        return self.real_files | self.placeholder_files | self.stub_files


@dataclass(frozen=True)
class ExecutionRule:
    path_prefix: str
    stage: str
    ci_required: bool


@dataclass(frozen=True)
class ExecutionMatrix:
    rules: list[ExecutionRule]

    def classify(self, path: str) -> ExecutionRule:
        normalized = path.strip().replace("\\", "/")
        best: ExecutionRule | None = None
        for rule in self.rules:
            prefix = rule.path_prefix
            matches = normalized == prefix.rstrip("/") or normalized.startswith(prefix)
            if matches and (best is None or len(prefix) > len(best.path_prefix)):
                best = rule
        if best is not None:
            return best
        if Path(normalized).is_absolute():
            return ExecutionRule(
                path_prefix=normalized, stage="external_test", ci_required=True
            )
        return ExecutionRule(path_prefix="", stage="unclassified", ci_required=False)


EXCLUDED_DIRS = {"node_modules", "__pycache__", ".next", "dist", ".cache"}

TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
DEFAULT_EXECUTION_MATRIX = Path("common/testing/data/test-execution-matrix.yaml")


def load_execution_matrix(path: Path = DEFAULT_EXECUTION_MATRIX) -> ExecutionMatrix:
    if not path.exists():
        return ExecutionMatrix(rules=[])
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules: list[ExecutionRule] = []
    for item in data.get("rules", []):
        path_prefix = str(item.get("path", "")).strip().replace("\\", "/")
        if not path_prefix:
            continue
        rules.append(
            ExecutionRule(
                path_prefix=path_prefix,
                stage=str(item.get("stage", "unclassified")),
                ci_required=bool(item.get("ci_required", False)),
            )
        )
    return ExecutionMatrix(rules=rules)


def _display_path(path: Path, display_root: Path | None = None) -> str:
    root = display_root if display_root is not None else Path.cwd()
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_registry(registry_path: Path) -> list[AC]:
    if not registry_path.exists():
        print(f"ERROR: AC registry not found: {registry_path}", file=sys.stderr)
        print("  Run: python tools/generate_ac_registry.py", file=sys.stderr)
        sys.exit(1)

    return [
        AC(
            id=entry["id"],
            epic=entry["epic"],
            epic_name=entry.get("epic_name", ""),
            description=entry.get("description", ""),
            mandatory=entry.get("mandatory", True),
        )
        for entry in load_registry_entries(registry_path)
    ]


def load_multiple_registries(registry_paths: list[Path]) -> list[AC]:
    """Load multiple AC registries and return combined AC list."""
    all_acs: list[AC] = []
    ac_id_set = set()
    for registry_path in registry_paths:
        acs = load_registry(registry_path)
        for ac in acs:
            # Avoid duplicates: use AC ID as unique identifier
            if ac.id not in ac_id_set:
                all_acs.append(ac)
                ac_id_set.add(ac.id)
    return all_acs


def find_test_files(test_dirs: list[Path]) -> list[Path]:
    test_files: list[Path] = []
    for base in test_dirs:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for fname in files:
                if fname.startswith("test_") or fname.endswith(TEST_FILE_SUFFIXES):
                    test_files.append(Path(root) / fname)
    return test_files


def collect_referenced_acs(
    test_files: list[Path],
    execution_matrix: ExecutionMatrix | None = None,
    display_root: Path | None = None,
) -> dict[str, ACReferenceStats]:
    references: dict[str, ACReferenceStats] = {}
    if execution_matrix is None:
        execution_matrix = load_execution_matrix()
    for fpath in test_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        kind = classify_reference_file(fpath, content)
        display_path = _display_path(fpath, display_root)
        execution = execution_matrix.classify(display_path)
        for m in AC_PATTERN.finditer(content):
            ac_id = m.group(0)
            stats = references.setdefault(ac_id, ACReferenceStats())
            if kind == "stub":
                stats.stub_files.add(display_path)
            elif kind == "placeholder":
                stats.placeholder_files.add(display_path)
            else:
                stats.real_files.add(display_path)
                if execution.ci_required:
                    stats.ci_real_files.add(display_path)
    return references


def is_deprecated(ac: AC) -> bool:
    description = ac.description.strip()
    return (
        description.startswith("~~")
        and description.endswith("~~")
        and len(description) > 4
    )


def check_traceability(
    acs: list[AC], references: dict[str, ACReferenceStats]
) -> TraceabilityResult:
    mandatory = [ac for ac in acs if ac.mandatory and not is_deprecated(ac)]
    covered = [
        ac.id
        for ac in mandatory
        if references.get(ac.id) and references[ac.id].ci_real_files
    ]
    unexecuted_only = [
        ac.id
        for ac in mandatory
        if references.get(ac.id)
        and references[ac.id].real_files
        and not references[ac.id].ci_real_files
    ]
    placeholder_only = [
        ac.id
        for ac in mandatory
        if references.get(ac.id)
        and not references[ac.id].real_files
        and references[ac.id].placeholder_files
    ]
    stub_only = [
        ac.id
        for ac in mandatory
        if references.get(ac.id)
        and not references[ac.id].real_files
        and not references[ac.id].placeholder_files
        and references[ac.id].stub_files
    ]
    missing = [
        ac.id
        for ac in mandatory
        if not references.get(ac.id) or not references[ac.id].all_files
    ]
    return TraceabilityResult(
        covered=covered,
        placeholder_only=placeholder_only,
        stub_only=stub_only,
        unexecuted_only=unexecuted_only,
        missing=missing,
        total=len(acs),
        mandatory_total=len(mandatory),
    )


def traceability_failure_messages(result: TraceabilityResult) -> list[str]:
    """Return the ordered traceability failure messages (verbatim).

    Exactly ONE message is emitted, matching ``main()``'s priority order
    (unexecuted-only > placeholder-only > stub-only > missing). This is the
    single source of the gate wording, reused by both ``main()`` and the
    consolidated ``check_ac_index`` gate so neither drifts from the other.
    """
    if result.unexecuted_only:
        return [
            "TRACEABILITY GATE FAILED: "
            f"{len(result.unexecuted_only)} mandatory AC(s) have real references only in non-CI-required stages.\n"
            "  Move at least one behavioral proof into a CI-required test stage or update common/testing/data/test-execution-matrix.yaml with the matching CI workflow."
        ]
    if result.placeholder_only:
        return [
            "TRACEABILITY GATE FAILED: "
            f"{len(result.placeholder_only)} mandatory AC(s) are covered only by placeholder assertions.\n"
            "  Replace expect(true).toBe(true), pure pass, or skipped placeholder tests with behavioral checks."
        ]
    if result.stub_only:
        return [
            "TRACEABILITY GATE FAILED: "
            f"{len(result.stub_only)} mandatory AC(s) are covered only by _ac_stubs.\n"
            "  Replace generated AC stubs with behavioral tests that exercise production paths."
        ]
    if result.missing:
        return [
            f"TRACEABILITY GATE FAILED: {len(result.missing)} mandatory AC(s) have no test reference.\n"
            f'  Add docstrings like """{result.missing[0]}: description""" to at least one test per AC.'
        ]
    return []


def run_traceability(repo_root: Path) -> TraceabilityResult:
    """Run the traceability scan anchored at ``repo_root`` (no CWD dependency).

    Composes the registry load, the test-file scan, the execution-matrix
    CI-stage classification, and ``check_traceability`` — resolving every path
    against ``repo_root`` so it can be invoked as a library from the consolidated
    gate. Same code, same classifications, same result shape.
    """
    registry_paths = [repo_root / "docs" / "ac_registry.yaml"]
    infra_registry_path = repo_root / "docs" / "infra_registry.yaml"
    if infra_registry_path.exists():
        acs = load_multiple_registries(registry_paths + [infra_registry_path])
    else:
        acs = load_multiple_registries(registry_paths)

    test_dirs = [repo_root / d for d in DEFAULT_AC_TEST_DIRS]
    test_files = find_test_files(test_dirs)
    execution_matrix = load_execution_matrix(repo_root / DEFAULT_EXECUTION_MATRIX)
    references = collect_referenced_acs(
        test_files, execution_matrix=execution_matrix, display_root=repo_root
    )
    return check_traceability(acs, references)
