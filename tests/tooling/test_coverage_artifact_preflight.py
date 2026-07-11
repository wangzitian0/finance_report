"""Coverage artifact preflight + tooling coverage tiering.

Covers two related concerns on the unified coverage pipeline:

- #414 (AC14.1.20): the unified aggregation must fail *explicitly* and name the
  offending component LCOV when a CI-critical artifact is missing or empty,
  rather than silently treating it as 0% and emitting a misleading number.
- #923 (AC14.1.21): coverage components carry an explicit ``tier``
  (``ci-critical`` vs ``best-effort``). The preflight enforces presence only for
  ``ci-critical`` tiers, so a missing best-effort ``tools`` artifact does not
  hard-fail the aggregation while application and shared-library trees stay
  strictly gated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.testing.coverage import calculate_unified_coverage as cuc  # noqa: E402
from common.meta.extension.coverage.policy import (  # noqa: E402
    CI_CRITICAL,
    BEST_EFFORT,
    COMPONENT_BY_NAME,
    CoverageComponent,
)


def _component(name: str, lcov_path: str, tier: str) -> CoverageComponent:
    return CoverageComponent(
        name=name,
        component_root="",
        source_subdir=name,
        extensions=(".py",),
        ci_lcov_path=lcov_path,
        local_lcov_paths=(),
        exclude_patterns=(),
        tier=tier,
    )


def _write_lcov(path: Path, covered: int, total: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"SF:{path.stem}/mod.py\nDA:1,1\nLH:{covered}\nLF:{total}\nend_of_record\n"
    )


# ---------------------------------------------------------------------------
# #923 — tooling coverage tiering (AC14.1.21)
# ---------------------------------------------------------------------------


class TestCoverageTiering:
    """AC-meta.coverage-tiers.2: components are tiered ci-critical vs best-effort."""

    def test_AC14_1_21_tools_component_is_best_effort_tier(self):
        # tools/ is largely one-off governance / CI glue: best-effort, not gated
        # on artifact presence.
        assert COMPONENT_BY_NAME["tools"].tier == BEST_EFFORT

    def test_AC14_1_21_app_and_common_components_are_ci_critical_tier(self):
        for name in ("backend", "frontend", "common"):
            assert COMPONENT_BY_NAME[name].tier == CI_CRITICAL, name

    def test_AC14_1_21_preflight_skips_best_effort_missing_artifact(self, tmp_path):
        # ci-critical artifact present, best-effort tools artifact absent ->
        # preflight passes (no error) because best-effort is not enforced.
        critical = _component("backend", "coverage/backend.lcov", CI_CRITICAL)
        best_effort = _component("tools", "coverage/tools.lcov", BEST_EFFORT)
        _write_lcov(tmp_path / "coverage" / "backend.lcov", 5, 10)
        # tools.lcov intentionally not written

        errors = cuc.required_artifacts_preflight(
            (critical, best_effort), repo_root=tmp_path
        )

        assert errors == []


# ---------------------------------------------------------------------------
# #414 — artifact preflight fails explicitly (AC14.1.20)
# ---------------------------------------------------------------------------


class TestRequiredArtifactsPreflight:
    """AC-meta.coverage-tiers.1: missing/empty CI-critical artifacts fail explicitly."""

    def test_AC14_1_20_preflight_fails_when_ci_critical_artifact_missing(
        self, tmp_path
    ):
        critical = _component("backend", "coverage/backend.lcov", CI_CRITICAL)
        # backend.lcov intentionally absent

        errors = cuc.required_artifacts_preflight((critical,), repo_root=tmp_path)

        assert len(errors) == 1
        # error must name the offending component and its expected LCOV path
        assert "backend" in errors[0]
        assert "coverage/backend.lcov" in errors[0]

    def test_AC14_1_20_preflight_fails_when_ci_critical_artifact_empty(self, tmp_path):
        critical = _component("frontend", "coverage/frontend.lcov", CI_CRITICAL)
        empty = tmp_path / "coverage" / "frontend.lcov"
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("")  # exists but no measured lines

        errors = cuc.required_artifacts_preflight((critical,), repo_root=tmp_path)

        assert len(errors) == 1
        assert "frontend" in errors[0]
        assert "empty" in errors[0].lower()

    def test_AC14_1_20_preflight_passes_when_all_present(self, tmp_path):
        backend = _component("backend", "coverage/backend.lcov", CI_CRITICAL)
        frontend = _component("frontend", "coverage/frontend.lcov", CI_CRITICAL)
        _write_lcov(tmp_path / "coverage" / "backend.lcov", 5, 10)
        _write_lcov(tmp_path / "coverage" / "frontend.lcov", 8, 10)

        assert (
            cuc.required_artifacts_preflight((backend, frontend), repo_root=tmp_path)
            == []
        )

    def test_AC14_1_20_main_fails_fast_with_named_missing_artifact(
        self, tmp_path, monkeypatch, capsys
    ):
        """main() exits non-zero and names the missing artifact before aggregating."""
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setenv("BASELINE_FILE", "")

        critical = _component("backend", "coverage/backend.lcov", CI_CRITICAL)
        monkeypatch.setattr(cuc, "PREFLIGHT_COMPONENTS", (critical,))
        # backend.lcov absent -> preflight must fail

        with pytest.raises(SystemExit) as exc:
            cuc.main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "backend" in combined
        assert "coverage/backend.lcov" in combined
        # must fail BEFORE writing a misleading unified-coverage.json
        assert not (tmp_path / "unified-coverage.json").exists()


# ---------------------------------------------------------------------------
# #414 — opt-in strict gate vs lenient default (CI parity)
# ---------------------------------------------------------------------------


class TestPreflightOptIn:
    """AC14.1.20: the preflight is opt-in so the always-run CI step never aborts
    on a legitimately-absent artifact, yet still fails loudly when a caller
    explicitly requires a component that is missing/empty."""

    def test_AC14_1_20_default_preflight_is_lenient(self):
        # No flag, no env -> nothing enforced -> a real missing artifact must not
        # be a hard abort. The shipped default component set is empty.
        assert cuc.PREFLIGHT_COMPONENTS == ()

    def test_AC14_1_20_resolve_required_components_lenient_inputs(self):
        assert cuc.resolve_required_components(None) == ()
        assert cuc.resolve_required_components("") == ()
        assert cuc.resolve_required_components("  ,  ") == ()

    def test_AC14_1_20_resolve_required_components_named(self):
        resolved = cuc.resolve_required_components("backend, frontend")
        assert [c.name for c in resolved] == ["backend", "frontend"]

    def test_AC14_1_20_resolve_required_components_all_keyword(self):
        resolved = cuc.resolve_required_components("all")
        assert {c.name for c in resolved} == {c.name for c in cuc.COMPONENTS}

    def test_AC14_1_20_resolve_required_components_unknown_raises(self):
        with pytest.raises(ValueError) as exc:
            cuc.resolve_required_components("nope")
        assert "nope" in str(exc.value)

    def _lenient_main_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setenv("BASELINE_FILE", "")
        monkeypatch.delenv(cuc.REQUIRED_COMPONENTS_ENV, raising=False)
        # Real component LCOVs are absent under tmp_path; with no required list
        # this must be tolerated (lenient).

    def test_AC14_1_20_main_lenient_default_exits_zero_when_artifacts_missing(
        self, tmp_path, monkeypatch
    ):
        self._lenient_main_env(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cuc.main()  # no --require-artifacts, no env
        assert exc.value.code == 0
        # lenient path still produces the report (does not abort the always-run step)
        assert (tmp_path / "unified-coverage.json").exists()

    def test_AC14_1_20_main_require_flag_fails_when_required_component_missing(
        self, tmp_path, monkeypatch, capsys
    ):
        self._lenient_main_env(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cuc.main(["--require-artifacts", "backend"])
        assert exc.value.code == 1
        combined = "".join(capsys.readouterr())
        assert "backend" in combined
        assert "coverage/backend.lcov" in combined
        assert not (tmp_path / "unified-coverage.json").exists()

    def test_AC14_1_20_main_require_env_fails_when_required_component_missing(
        self, tmp_path, monkeypatch
    ):
        self._lenient_main_env(tmp_path, monkeypatch)
        monkeypatch.setenv(cuc.REQUIRED_COMPONENTS_ENV, "common")
        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 1
        assert not (tmp_path / "unified-coverage.json").exists()


# ---------------------------------------------------------------------------
# #1689 — component-scoped PR coverage gate
# ---------------------------------------------------------------------------


class TestGateComponentsScoping:
    """AC8.13.163: --gate-components/COVERAGE_GATE_COMPONENTS narrows the
    no-regression check to the named components on a PR; other components'
    regressions are reported but do not fail the job. Omitted -> unchanged
    strict "gate everything" behavior (main-branch push's safe default)."""

    def _scoped_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.delenv(cuc.REQUIRED_COMPONENTS_ENV, raising=False)
        monkeypatch.delenv(cuc.GATE_COMPONENTS_ENV, raising=False)

        baseline_path = tmp_path / "unified-coverage.json"
        baseline_path.write_text(
            '{"coverage_percent": 50, "breakdown": '
            '{"backend": {"coverage_percent": 50}, '
            '"frontend": {"coverage_percent": 0}}}'
        )
        monkeypatch.setenv("BASELINE_FILE", "unified-coverage.json")

        # backend regresses (0% current vs a 50% floor); frontend's floor is
        # already 0%, so its 0% current is NOT a regression. common/tools have
        # no baseline entry at all, so they are never compared either way.
        _write_lcov(tmp_path / "coverage" / "backend.lcov", covered=0, total=10)

    def test_AC8_13_163_unscoped_default_fails_on_backend_and_unified(
        self, tmp_path, monkeypatch, capsys
    ):
        self._scoped_env(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cuc.main()  # no --gate-components -> "all" (unchanged, strict)
        assert exc.value.code == 1
        combined = "".join(capsys.readouterr())
        for regressed_name in ("backend", "unified"):
            marker = f"- {regressed_name}:"
            assert marker in combined

    def test_AC8_13_163_scoped_to_the_regressed_component_still_fails(
        self, tmp_path, monkeypatch, capsys
    ):
        """AC-testing.coverage.6: calculate_unified_coverage's no-regression gate accepts a
        --gate-components/COVERAGE_GATE_COMPONENTS scope: on pull_request events it
        BLOCKS only on regressions in the components the PR actually changed (an
        unrelated component's regression, and the blended "unified" total, are still
        computed and reported but do not fail the job); every component is still merged
        into unified-coverage.json regardless of scope, and a push to main always omits
        the scope (full, unscoped, unchanged-strict gate) (#1689) (Was EPIC-008
        AC8.13.163).
        """
        self._scoped_env(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cuc.main(["--gate-components", "backend"])
        assert exc.value.code == 1
        combined = "".join(capsys.readouterr())
        backend_marker = "- backend:"
        assert backend_marker in combined
        # The blended unified total is not attributable to a scoped run.
        unified_marker = "- unified:"
        assert unified_marker not in combined

    def test_AC8_13_163_scoped_away_from_the_regressed_component_passes(
        self, tmp_path, monkeypatch
    ):
        self._scoped_env(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cuc.main(["--gate-components", "frontend"])
        # backend's regression is out of scope -> informational only, not
        # gate-failing; frontend itself has no regression -> the job passes.
        assert exc.value.code == 0
        assert (tmp_path / "unified-coverage.json").exists()

    def test_AC8_13_163_env_var_fallback_matches_the_cli_flag(
        self, tmp_path, monkeypatch
    ):
        self._scoped_env(tmp_path, monkeypatch)
        monkeypatch.setenv(cuc.GATE_COMPONENTS_ENV, "frontend")
        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0

    def test_AC8_13_163_unknown_gate_component_name_fails_loudly(
        self, tmp_path, monkeypatch
    ):
        self._scoped_env(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cuc.main(["--gate-components", "nope"])
        assert exc.value.code == 2

    def test_AC8_13_163_main_branch_push_omits_the_flag_and_stays_strict(
        self, tmp_path, monkeypatch
    ):
        # Documents the CI wiring contract (ci.yml only sets
        # COVERAGE_GATE_COMPONENTS on pull_request events): with the env unset,
        # a regression anywhere still fails the run, matching today's
        # main-branch push behavior exactly.
        self._scoped_env(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 1
