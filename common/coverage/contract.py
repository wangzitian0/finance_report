"""The ``coverage`` package's machine-checkable :class:`PackageContract`.

``coverage`` is internal tooling — the unified-coverage policy + lcov helpers
(``policy``, ``check_policy``, ``calculate_unified_coverage``, ``merge_lcov``,
``build_unified_lcov``, ``strip_lcov_branches``, ``analyzer``) — not a domain
bounded context, so it publishes no curated symbol language (``interface=[]``);
callers import its modules directly. The contract governs it as an ``infra`` leaf
(L1, `depends_on=[]`) with invariants pinned to its tests.
A curated published-language surface is a future cleanup.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="coverage",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    roles=[
        "policy",
        "check_policy",
        "calculate_unified_coverage",
        "merge_lcov",
        "build_unified_lcov",
        "strip_lcov_branches",
        "analyzer",
    ],
    implementations={"be": "common/coverage", "fe": None},
    interface=[],
    events=[],
    invariants=[
        Invariant(
            id="registered-source-missing-from-lcov-fails",
            statement="The coverage policy fails when a registered source file is missing from the lcov report, so uncovered source is never silently dropped.",
            test="tests/tooling/test_coverage_policy.py::test_compare_component_fails_when_source_file_is_missing_from_lcov",
        ),
        Invariant(
            id="source-set-recursive-with-exclusions",
            statement="The expected coverage source set recursively includes all eligible files except the declared exclusions.",
            test="tests/tooling/test_coverage_policy.py::test_expected_sources_recursively_include_all_eligible_files_except_exclusions",
        ),
    ],
    roadmap=[],
)

# Test roots this package owns (aggregated into the execution matrix's
# generated ownership view; see common/testing/matrix.py, issue #1558).
TEST_ROOTS: tuple[str, ...] = (
    "tests/tooling/test_coverage_policy.py",
    "tests/tooling/test_coverage_analyzer.py",
    "tests/tooling/test_calculate_unified_coverage.py",
    "tests/tooling/test_coverage_artifact_preflight.py",
)
