#!/usr/bin/env python3
"""Pure validation library for AC test-reference traceability.

This module is a LIBRARY, not a CLI gate. Its functions are imported by the
single consolidated gate (:mod:`common.testing.check_ac_index`) — which calls
``run_traceability`` + ``traceability_failure_messages`` inside Gate A — and by
the traceability unit tests. There is no ``main()`` / argument parser / report
printer here any more: the one gate entry point is ``tools/check_ac_index.py``.

It also owns the two shared AC rules: :func:`is_deprecated` (the one deprecation
rule) and :func:`classify_references` (the one real / placeholder / stub /
missing classifier). The protection count, the doc lint and the audit builder
(``build_ac_traceability``) call them instead of keeping copies.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from common.meta.base.gate_util import display_path
from common.testing.ac_scan import ACReferenceStats, collect_references, find_test_files
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


def load_registry(registry_path: Path) -> list[AC]:
    if not registry_path.exists():
        print(f"ERROR: AC registry not found: {registry_path}", file=sys.stderr)
        print("  Run: python tools/generate_ac_registry.py", file=sys.stderr)
        sys.exit(1)

    return [
        AC(
            id=entry["id"],
            epic=int(entry["epic"]),
            epic_name=str(entry.get("epic_name", "")),
            description=str(entry.get("description", "")),
            mandatory=bool(entry.get("mandatory", True)),
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


def collect_referenced_acs(
    test_files: list[Path],
    execution_matrix: ExecutionMatrix | None = None,
    display_root: Path | None = None,
) -> dict[str, ACReferenceStats]:
    if execution_matrix is None:
        execution_matrix = load_execution_matrix()
    root = display_root if display_root is not None else Path.cwd()
    return collect_references(
        test_files,
        display_path=lambda path: display_path(path, root),
        is_ci_file=lambda path: execution_matrix.classify(str(path)).ci_required,
    )


def is_deprecated(description: str) -> bool:
    """The one deprecation rule: a non-blank ``~~strikethrough~~`` description.

    Every AC consumer (this gate, the protection count, the doc lint, the audit
    builder) calls this function. ``~~~~`` and ``~~ ~~`` are not deprecated: an
    empty strikethrough must not exempt a mandatory AC from its test.
    """
    text = description.strip()
    return text.startswith("~~") and text.endswith("~~") and bool(text[2:-2].strip())


def classify_references(stats: ACReferenceStats | None) -> str:
    """The one classifier of an AC's test references.

    Returns ``real`` (a behavioral test), ``placeholder`` (only trivial
    assertions, ``pass`` or skips), ``stub`` (only ``_ac_stubs`` files) or
    ``missing`` (no reference at all), in that priority order.
    """
    if stats is None or not stats.all_files:
        return "missing"
    if stats.real_files:
        return "real"
    if stats.placeholder_files:
        return "placeholder"
    return "stub"


def check_traceability(
    acs: list[AC], references: dict[str, ACReferenceStats]
) -> TraceabilityResult:
    mandatory = [ac for ac in acs if ac.mandatory and not is_deprecated(ac.description)]
    covered: list[str] = []
    unexecuted_only: list[str] = []
    placeholder_only: list[str] = []
    stub_only: list[str] = []
    missing: list[str] = []
    for ac in mandatory:
        stats = references.get(ac.id)
        kind = classify_references(stats)
        if kind == "real":
            (covered if stats.ci_real_files else unexecuted_only).append(ac.id)
        elif kind == "placeholder":
            placeholder_only.append(ac.id)
        elif kind == "stub":
            stub_only.append(ac.id)
        else:
            missing.append(ac.id)
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

    A result with zero mandatory ACs fails: an empty or unreadable registry
    must not pass as "nothing is untraced".
    """
    if result.mandatory_total == 0:
        return [
            "TRACEABILITY GATE FAILED: 0 mandatory AC(s) were scanned.\n"
            "  An empty registry cannot pass. Check docs/ac_registry.yaml, "
            "docs/infra_registry.yaml and their epic_source."
        ]
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
