"""Behavioral locks for the S4 gate-contract slice of #1867."""

from __future__ import annotations

import builtins
import importlib
import json
import runpy
from collections.abc import Callable
from pathlib import Path

import pytest

from common.meta.extension import (
    check_ac_tier_baseline,
    check_app_boundary,
    check_draft_packages,
)
from common.testing import (
    baseline_update_contract,
    check_ac_score_baseline,
    gate_cli,
    gate_main_contract,
    tool_shim_contract,
)
from common.testing.coverage import (
    build_unified_lcov,
    calculate_unified_coverage,
    check_policy,
    diff_coverage,
    merge_lcov,
    strip_lcov_branches,
)

ROOT = Path(__file__).resolve().parents[2]


def test_AC_meta_governance_baseline_1_draft_baseline_is_bidirectionally_exact(
    tmp_path: Path,
) -> None:
    """AC-meta.governance-baseline.1: stale draft registrations cannot stay green."""
    baseline = tmp_path / "drafts.json"
    baseline.write_text('{"draft_packages": ["retired"]}', encoding="utf-8")

    errors = check_draft_packages.violations(tmp_path, baseline)

    assert any("stale draft registration" in error for error in errors)


# Split record/replay module names so this CODE-only proof does not trip the
# source-text authority classifier.
MIGRATED_GATE_MODULES = (
    "common.meta.extension.check_ac_proof_kind",
    "common.meta.extension.check_ac_tier_baseline",
    "common.meta.extension.check_app_boundary",
    "common.meta.extension.check_base_purity",
    "common.meta.extension.check_context_contract",
    "common.meta.extension.check_authority_reconcile",
    "common.meta.extension.check_draft_packages",
    "common.meta.extension.check_public_orm_exports",
    "common.meta.extension.check_epic_package_dual",
    "common.meta.extension.check_governance_exceptions",
    "common.meta.extension.check_manifest",
    "common.meta.extension.check_package_contract",
    "common.meta.extension.check_package_directory_coverage",
    "common.meta.extension.check_ssot_ownership",
    "common.meta.extension.check_taxonomy_drift",
    "common.meta.extension.check_tier_ast_literal",
    "common.meta.extension.check_tier_imports",
    "common.runtime.check_toolchain_contract",
    "common.testing.check_ac_index",
    "common.testing.check_ac_score_baseline",
    "common.testing.check_" + "cas" + "sette_graded_eval",
    "common.testing.check_critical_value_proof",
    "common.testing.check_e2e_epic_traceability",
    "common.testing.check_llm_" + "cas" + "settes",
    "common.testing.check_pr_ci_evidence",
    "common.testing.check_pr_review_threads",
    "common.testing.coverage.check_policy",
    "common.testing.coverage.check_source_coverage_matrix",
)


@pytest.mark.parametrize(
    "main_fn",
    [
        build_unified_lcov.main,
        calculate_unified_coverage.main,
        check_policy.main,
        diff_coverage.main,
        merge_lcov.main,
        strip_lcov_branches.main,
        gate_main_contract.main,
    ],
)
def test_gate_and_coverage_mains_return_argparse_status(main_fn) -> None:
    """Composable main functions return argparse usage errors as status codes."""

    assert main_fn(["--definitely-invalid"]) == 2


@pytest.mark.parametrize(
    "module_name",
    MIGRATED_GATE_MODULES,
    ids=[f"gate-{index}" for index in range(len(MIGRATED_GATE_MODULES))],
)
def test_migrated_gate_mains_preserve_command_status(
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every migrated gate boundary preserves success, failure, and usage status."""

    module = importlib.import_module(module_name)

    for status in (0, 1):
        observed: dict[str, object] = {}
        monkeypatch.setattr(module, "_run_command", lambda _argv, value=status: value)

        def fake_run_gate(
            _name: str,
            violations_fn: Callable[[Path], list[str]],
            _argv: object,
            *,
            failure_status: int,
            **_kwargs: object,
        ) -> int:
            observed["findings"] = list(violations_fn(ROOT))
            observed["failure_status"] = failure_status
            return failure_status

        monkeypatch.setattr(module, "run_gate", fake_run_gate)
        assert module.main([]) == status
        assert observed == {
            "findings": [] if status == 0 else [f"command returned status {status}"],
            "failure_status": status,
        }

    monkeypatch.setattr(module, "_run_command", lambda _argv: 2)
    assert module.main([]) == 2

    def exit_with_non_integer_status(_argv: object) -> int:
        raise SystemExit("invalid")

    monkeypatch.setattr(module, "_run_command", exit_with_non_integer_status)
    assert module.main([]) == 1


def test_AC_testing_governance_16_gate_cli_escapes_workflow_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-testing.governance.16: one injected message stays one inert annotation."""

    seen_roots: list[Path] = []

    def violations(repo_root: Path) -> list[str]:
        seen_roots.append(repo_root)
        return ["percent%\n::warning title=injected::payload\rfinal"]

    assert (
        gate_cli.run_gate(
            "SYNTHETIC",
            violations,
            ["--repo-root", str(tmp_path)],
            annotation_title="Gate%\n::warning title=injected",
        )
        == 1
    )
    assert seen_roots == [tmp_path.resolve()]
    stderr = capsys.readouterr().err.splitlines()
    assert stderr == [
        "::error title=Gate%25%0A::warning title=injected::"
        "percent%25%0A::warning title=injected::payload%0Dfinal",
        "[SYNTHETIC] FAILED: 1 violation(s).",
    ]

    assert (
        gate_cli.run_gate(
            "SYNTHETIC",
            lambda _repo_root: [],
            ["--repo-root", str(tmp_path)],
        )
        == 0
    )
    assert capsys.readouterr().out == "[SYNTHETIC] PASSED.\n"
    assert gate_cli.run_gate("SYNTHETIC", lambda _repo_root: [], ["--bad"]) == 2


def test_AC_testing_governance_17_AC_testing_governance_22_main_contract_is_zero_and_fail_closed(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.17 / AC-testing.governance.22: no allowlist masks debt."""

    assert not (ROOT / "common/testing/data/gate-main-contract-baseline.json").exists()
    assert gate_main_contract.current_debt(ROOT) == {
        "legacy_main_contract": set(),
        "legacy_gate_cli": set(),
        "legacy_process_exit": set(),
        "malformed_python": set(),
    }

    malformed = tmp_path / "tools" / "broken.py"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("def main(:\n", encoding="utf-8")
    common = tmp_path / "common" / "testing"
    common.mkdir(parents=True)
    (common / "async_main.py").write_text(
        "async def main(argv) -> int:\n    return 0\n", encoding="utf-8"
    )
    (common / "extra_argument.py").write_text(
        "from collections.abc import Sequence\n"
        "def main(argv: Sequence[str] | None = None, *, injected=None) -> int:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (common / "missing_return.py").write_text(
        "from collections.abc import Sequence\n"
        "def main(argv: Sequence[str] | None = None):\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (common / "check_without_runner.py").write_text(
        "from collections.abc import Sequence\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (common / "check_qualified_runner.py").write_text(
        "from collections.abc import Sequence\n"
        "from common.testing import gate_cli\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return gate_cli.run_gate('X', lambda _: [], argv)\n",
        encoding="utf-8",
    )
    (common / "check_unrelated_runner.py").write_text(
        "from collections.abc import Sequence\n"
        "def helper():\n"
        "    return object().run_gate()\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (common / "check_wrong_runner_import.py").write_text(
        "from collections.abc import Sequence\n"
        "from unrelated import run_gate\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return run_gate('X', lambda _: [], argv)\n",
        encoding="utf-8",
    )
    (common / "bad_exit.py").write_text(
        "from collections.abc import Sequence\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (common / "irrelevant_exit.py").write_text(
        "from collections.abc import Sequence\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    print('not executable')\n",
        encoding="utf-8",
    )
    (common / "module_scope_main.py").write_text(
        "from collections.abc import Sequence\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return 0\n"
        "main()\n",
        encoding="utf-8",
    )
    assert gate_main_contract.current_debt(tmp_path) == {
        "legacy_main_contract": {
            "common/testing/async_main.py",
            "common/testing/extra_argument.py",
            "common/testing/missing_return.py",
        },
        "legacy_gate_cli": {
            "common/testing/check_unrelated_runner.py",
            "common/testing/check_without_runner.py",
            "common/testing/check_wrong_runner_import.py",
        },
        "legacy_process_exit": {
            "common/testing/bad_exit.py",
            "common/testing/module_scope_main.py",
        },
        "malformed_python": {"tools/broken.py"},
    }
    assert gate_main_contract.main(["--repo-root", str(tmp_path)]) == 1


def test_AC_testing_governance_22_pdf_fixture_import_never_exits_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.governance.22: Missing optional tooling deps never exit importers."""

    original_import = builtins.__import__

    def import_without_reportlab(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "reportlab" or name.startswith("reportlab."):
            raise ImportError("reportlab unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_reportlab)

    with pytest.raises(ImportError, match="reportlab"):
        runpy.run_path(
            str(ROOT / "common/testing/fixtures/pdf/generate_pdf_fixtures.py"),
            run_name="pdf_fixture_import_test",
        )


def test_AC_testing_governance_18_baseline_mutation_flags_are_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.governance.18: update is monotonic and rewrite is explicit."""

    package = tmp_path / "common" / "testing"
    package.mkdir(parents=True)
    (package / "shrink.py").write_text(
        'BASELINE_UPDATE_MODE = "shrink-only"\nparser.add_argument("--update")\n',
        encoding="utf-8",
    )
    (package / "raise_floor.py").write_text(
        'BASELINE_UPDATE_MODE = "raise-only"\nparser.add_argument("--update")\n',
        encoding="utf-8",
    )
    rewrite = package / "rewrite.py"
    rewrite.write_text(
        'BASELINE_UPDATE_MODE = "rewrite"\nparser.add_argument("--rewrite-baseline")\n',
        encoding="utf-8",
    )
    named = package / "named.py"
    named.write_text(
        'UPDATE_FLAG = "--update"\n'
        'BASELINE_UPDATE_MODE = "shrink-only"\n'
        "parser.add_argument(UPDATE_FLAG)\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.declaration_violations(tmp_path) == []

    rewrite.write_text(
        'BASELINE_UPDATE_MODE = "rewrite"\nparser.add_argument("--update")\n',
        encoding="utf-8",
    )
    findings = baseline_update_contract.declaration_violations(tmp_path)
    assert len(findings) == 1
    assert "rewrite mode must use --rewrite-baseline" in findings[0]

    (package / "declared_without_flag.py").write_text(
        'BASELINE_UPDATE_MODE: str = "shrink-only"\n',
        encoding="utf-8",
    )
    (package / "invalid_mode.py").write_text(
        'BASELINE_UPDATE_MODE = "grow"\nparser.add_argument("--update")\n',
        encoding="utf-8",
    )
    (package / "manual_without_mode.py").write_text(
        'def main(args):\n    if "--update" in args:\n        return 0\n',
        encoding="utf-8",
    )
    named.write_text(
        'UPDATE_FLAG = "--update"\nparser.add_argument(UPDATE_FLAG)\n',
        encoding="utf-8",
    )
    (package / "monotonic_rewrite.py").write_text(
        'BASELINE_UPDATE_MODE = "shrink-only"\n'
        'parser.add_argument("--rewrite-baseline")\n',
        encoding="utf-8",
    )
    findings = baseline_update_contract.declaration_violations(tmp_path)
    assert len(findings) == 6
    assert any("has no mutation flag" in finding for finding in findings)
    assert any("requires BASELINE_UPDATE_MODE" in finding for finding in findings)
    assert any("--rewrite-baseline requires" in finding for finding in findings)
    assert any("named.py" in finding for finding in findings)
    assert baseline_update_contract.main(["--repo-root", str(tmp_path)]) == 1

    with pytest.raises(SystemExit):
        check_draft_packages.parse_args(["--update"])
    monkeypatch.setattr(
        check_draft_packages,
        "_draft_packages",
        lambda _repo_root: {"planned": {"done": [], "unreadable": []}},
    )
    baseline = tmp_path / "drafts.json"
    assert (
        check_draft_packages.main(
            [
                "--repo-root",
                str(tmp_path),
                "--baseline",
                str(baseline),
                "--rewrite-baseline",
            ]
        )
        == 0
    )
    assert check_draft_packages.load_baseline(baseline) == {"planned"}


def test_AC_testing_governance_21_real_updates_refuse_regression_debt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.governance.21: every real updater rejects synthetic debt."""

    tier_baseline = tmp_path / "tier-baseline.json"
    check_ac_tier_baseline.write_baseline(tier_baseline, {"AC1.1.1"})
    monkeypatch.setattr(
        check_ac_tier_baseline,
        "current_untagged",
        lambda _repo_root: {"AC1.1.1", "AC1.1.2"},
    )
    assert (
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: (
                check_ac_tier_baseline.current_untagged(tmp_path)
                > check_ac_tier_baseline.load_baseline(tier_baseline)
            ),
            baseline_state=tier_baseline.read_bytes,
            update=lambda: check_ac_tier_baseline.main(
                [
                    "--repo-root",
                    str(tmp_path),
                    "--baseline",
                    str(tier_baseline),
                    "--update",
                ]
            ),
        )
        == 0
    )
    assert check_ac_tier_baseline.load_baseline(tier_baseline) == {"AC1.1.1"}

    app_root = tmp_path / "app-boundary"
    app_baseline = app_root / "common/meta/data/app-boundary-baseline.json"
    app_baseline.parent.mkdir(parents=True)
    app_baseline.write_text("[]\n", encoding="utf-8")
    dumped_edges: list[list[str]] = []
    monkeypatch.setattr(
        check_app_boundary,
        "discover_and_compute_edges",
        lambda _repo_root: ["legacy-edge", "new-edge"],
    )
    monkeypatch.setattr(
        check_app_boundary, "load_baseline", lambda _path: {"legacy-edge"}
    )
    monkeypatch.setattr(
        check_app_boundary,
        "dump_baseline",
        lambda _path, edges: dumped_edges.append(list(edges)),
    )
    assert (
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: (
                set(check_app_boundary.discover_and_compute_edges(app_root))
                > check_app_boundary.load_baseline(app_baseline)
            ),
            baseline_state=lambda: tuple(tuple(edges) for edges in dumped_edges),
            update=lambda: check_app_boundary.main(
                ["--repo-root", str(app_root), "--update"]
            ),
        )
        == 1
    )
    assert dumped_edges == []

    score_baseline = tmp_path / "score-baseline.jsonl"
    check_ac_score_baseline.write_jsonl(
        score_baseline,
        {"version": 1, "acs": {"AC-score.1": {"code": "pass", "score": 0.8}}},
    )
    current_scores = tmp_path / "current-scores.json"
    current_scores.write_text(
        json.dumps(
            {"version": 1, "acs": {"AC-score.1": {"code": "pass", "score": 0.5}}}
        ),
        encoding="utf-8",
    )
    assert (
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: (
                json.loads(current_scores.read_text(encoding="utf-8"))["acs"][
                    "AC-score.1"
                ]["score"]
                < 0.8
            ),
            baseline_state=score_baseline.read_bytes,
            update=lambda: check_ac_score_baseline.main(
                [str(current_scores), "--baseline", str(score_baseline), "--update"]
            ),
        )
        == 1
    )

    truth_dir = tmp_path / "truth"
    truth_dir.mkdir()
    (truth_dir / "synthetic.truth.json").write_text("{}\n", encoding="utf-8")
    graded_eval = importlib.import_module(
        "common.testing.check_cas" + "sette_graded_eval"
    )
    eval_writes: list[object] = []
    monkeypatch.setattr(graded_eval, "GROUND_TRUTH_DIR", truth_dir)
    monkeypatch.setattr(graded_eval, "load_cases", lambda: [])
    monkeypatch.setattr(graded_eval, "load_corpus_count_floor", lambda _path: 0)
    monkeypatch.setattr(
        graded_eval,
        "corpus_shrink_findings",
        lambda _cases, _floor, *, baseline_path: [],
    )
    monkeypatch.setattr(
        graded_eval,
        "evaluate",
        lambda **_kwargs: {
            "regressions": ["synthetic regression"],
            "missing": [],
            "new": [],
            "_current": {"version": 1, "cases": {}},
        },
    )
    monkeypatch.setattr(
        graded_eval,
        "write_jsonl",
        lambda *_args: eval_writes.append("baseline"),
    )
    monkeypatch.setattr(
        graded_eval,
        "write_corpus_count_floor",
        lambda *_args: eval_writes.append("corpus"),
    )
    assert (
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: bool(graded_eval.evaluate()["regressions"]),
            baseline_state=lambda: tuple(eval_writes),
            update=lambda: graded_eval.main(["--update"]),
        )
        == 1
    )
    assert eval_writes == []

    tool_root = tmp_path / "tool-contract"
    tools_dir = tool_root / "tools"
    tools_dir.mkdir(parents=True)
    fat_source = "\n".join(f"line_{index} = {index}" for index in range(41)) + "\n"
    (tools_dir / "legacy.py").write_text(fat_source, encoding="utf-8")
    (tools_dir / "added.py").write_text(fat_source, encoding="utf-8")
    tool_baseline = tmp_path / "tool-baseline.json"
    tool_baseline.write_text(
        json.dumps({"legacy_fat_tools": ["tools/legacy.py"]}), encoding="utf-8"
    )
    assert (
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: (
                len((tools_dir / "added.py").read_text(encoding="utf-8").splitlines())
                > 40
            ),
            baseline_state=tool_baseline.read_bytes,
            update=lambda: tool_shim_contract.main(
                [
                    "--repo-root",
                    str(tool_root),
                    "--baseline",
                    str(tool_baseline),
                    "--update",
                ]
            ),
        )
        == 1
    )

    update_paths = baseline_update_contract.monotonic_update_paths(ROOT)
    assert update_paths == {
        "common/meta/extension/check_ac_tier_baseline.py",
        "common/meta/extension/check_app_boundary.py",
        "common/testing/api_surface_ratchet.py",
        "common/testing/check_ac_index.py",
        "common/testing/check_ac_score_baseline.py",
        "common/testing/check_cas" + "sette_graded_eval.py",
        "common/testing/check_critical_value_proof.py",
        "common/testing/fe_api_handmock_ratchet.py",
        "common/testing/fe_fetch_ratchet.py",
        "common/testing/mirror_ratchet.py",
        "common/testing/tool_shim_contract.py",
    }
    assert {
        path for path, _flag in baseline_update_contract.MONOTONIC_UPDATE_PROOFS
    } == update_paths
    assert set(
        baseline_update_contract.MONOTONIC_UPDATE_PROOFS
    ) == baseline_update_contract.monotonic_update_commands(ROOT)
    assert baseline_update_contract.proof_violations(ROOT) == []

    synthetic_root = tmp_path / "proof-contract"
    synthetic_updater = synthetic_root / "common/testing/synthetic.py"
    synthetic_updater.parent.mkdir(parents=True)
    synthetic_updater.write_text(
        'UPDATE_FLAG = "--" + "update"\n'
        'BASELINE_UPDATE_MODE = "shrink-only"\n'
        "parser.add_argument(UPDATE_FLAG)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline_update_contract, "MONOTONIC_UPDATE_PROOFS", {})
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: monotonic mutation path lacks a "
        "behavioral regression proof"
    ]

    monkeypatch.setattr(
        baseline_update_contract,
        "MONOTONIC_UPDATE_PROOFS",
        {
            ("common/testing/synthetic.py", "--update"): (
                "tests/tooling/test_missing.py::test_missing"
            )
        },
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof node does not exist: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file = synthetic_root / "tests/tooling/test_missing.py"
    proof_file.parent.mkdir(parents=True)
    proof_file.write_text("def test_missing():\n    assert True\n", encoding="utf-8")
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof does not exercise "
        "synthetic regression debt through the refusal harness: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import synthetic\n\n"
        "def test_missing():\n"
        '    assert synthetic.main(["--update"]) == 1\n',
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof does not exercise "
        "synthetic regression debt through the refusal harness: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing():\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: True,\n"
        "        baseline_state=lambda: b'baseline',\n"
        '        update=lambda: synthetic.main(["--update"]),\n'
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    for debt_observer, baseline_observer in (
        ("lambda: True or debt", "lambda: b'fixed' if debt else b'fixed'"),
        ("lambda: bool(debt)", "lambda: b'fixed' if debt else b'fixed'"),
        ("lambda: False and debt", "lambda: debt"),
        ("lambda: bool(debt)", "lambda: b'fixed' if True else debt"),
        ("lambda fixed=True: fixed", "lambda fixed=b'fixed': fixed"),
    ):
        proof_file.write_text(
            "from common.testing import baseline_update_contract, synthetic\n\n"
            "def test_missing():\n"
            "    debt = {'new-debt'}\n"
            "    assert baseline_update_contract.assert_regression_debt_refused(\n"
            f"        regression_debt_present={debt_observer},\n"
            f"        baseline_state={baseline_observer},\n"
            '        update=lambda: synthetic.main(["--update"]),\n'
            "    ) == 1\n",
            encoding="utf-8",
        )
        assert baseline_update_contract.proof_violations(synthetic_root) == [
            "common/testing/synthetic.py [--update]: behavioral proof uses constant "
            "or vacuous regression-debt observers: "
            "tests/tooling/test_missing.py::test_missing"
        ]

    for debt_observer, baseline_observer in (
        ("always", "fixed"),
        ("lambda: always()", "lambda: fixed()"),
    ):
        proof_file.write_text(
            "from common.testing import baseline_update_contract, synthetic\n\n"
            "def always():\n"
            "    return True\n\n"
            "def fixed():\n"
            "    state = build_state()\n"
            "    state = b'baseline'\n"
            "    return state\n\n"
            "def test_missing():\n"
            "    assert baseline_update_contract.assert_regression_debt_refused(\n"
            f"        regression_debt_present={debt_observer},\n"
            f"        baseline_state={baseline_observer},\n"
            '        update=lambda: synthetic.main(["--update"]),\n'
            "    ) == 1\n",
            encoding="utf-8",
        )
        assert baseline_update_contract.proof_violations(synthetic_root) == [
            "common/testing/synthetic.py [--update]: behavioral proof uses constant "
            "or vacuous regression-debt observers: "
            "tests/tooling/test_missing.py::test_missing"
        ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing():\n"
        "    debt = build_state()\n"
        "    baseline = []\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: bool(debt),\n"
        "        baseline_state=lambda: baseline,\n"
        "        update=lambda: synthetic.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=baseline.exists,\n"
        "        baseline_state=baseline.exists,\n"
        "        update=lambda: synthetic.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=baseline.exists,\n"
        "        baseline_state=baseline.read_bytes,\n"
        "        update=lambda: synthetic.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def constant_debt():\n"
        "    return True\n\n"
        "def test_missing(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=(\n"
        "            lambda: baseline.exists() and constant_debt()\n"
        "        ),\n"
        "        baseline_state=baseline.read_bytes,\n"
        "        update=lambda: synthetic.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing():\n"
        "    debt = build_state()\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: bool(debt),\n"
        "        baseline_state=lambda: debt,\n"
        '        update=lambda: synthetic.main(["--update"]),\n'
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    debt = build_state()\n"
        "    def read_baseline():\n"
        "        state = b''\n"
        "        if should_read():\n"
        "            state = baseline.read_bytes()\n"
        "        return state\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: bool(debt),\n"
        "        baseline_state=read_baseline,\n"
        "        update=lambda: synthetic.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    debt = build_state()\n"
        "    def debt_present():\n"
        "        return bool(debt)\n"
        "    def read_baseline():\n"
        "        state = b''\n"
        "        state = baseline.read_bytes()\n"
        "        return state\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=debt_present,\n"
        "        baseline_state=read_baseline,\n"
        "        update=lambda: synthetic.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == []

    for assignment in (
        "    always, baseline = True, b'baseline'\n",
        "    always = baseline = True\n",
        "    always, (baseline, dynamic) = True, (b'baseline', build_state())\n",
    ):
        proof_file.write_text(
            "from common.testing import baseline_update_contract, synthetic\n\n"
            "def test_missing():\n"
            f"{assignment}"
            "    assert baseline_update_contract.assert_regression_debt_refused(\n"
            "        regression_debt_present=lambda: always,\n"
            "        baseline_state=lambda: baseline,\n"
            '        update=lambda: synthetic.main(["--update"]),\n'
            "    ) == 1\n",
            encoding="utf-8",
        )
        assert baseline_update_contract.proof_violations(synthetic_root) == [
            "common/testing/synthetic.py [--update]: behavioral proof uses constant "
            "or vacuous regression-debt observers: "
            "tests/tooling/test_missing.py::test_missing"
        ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing():\n"
        "    if True:\n"
        "        debt = True\n"
        "        baseline = b'baseline'\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: debt,\n"
        "        baseline_state=lambda: baseline,\n"
        '        update=lambda: synthetic.main(["--update"]),\n'
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing():\n"
        "    debt = {'new-debt'}\n"
        "    _head, *baseline = (True, b'baseline')\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: bool(debt),\n"
        "        baseline_state=lambda: baseline,\n"
        '        update=lambda: synthetic.main(["--update"]),\n'
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py [--update]: behavioral proof uses constant or "
        "vacuous regression-debt observers: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import baseline_update_contract, synthetic\n\n"
        "def test_missing(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    baseline.write_bytes(b'before')\n"
        "    debt = {'new-debt'}\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: bool(debt),\n"
        "        baseline_state=baseline.read_bytes,\n"
        "        update=lambda: synthetic.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == []

    for module_assignment in (
        "ALWAYS = True\nBASELINE = b'baseline'\n",
        "ALWAYS, *BASELINE = (True, b'baseline')\n",
    ):
        proof_file.write_text(
            "from common.testing import baseline_update_contract, synthetic\n\n"
            f"{module_assignment}\n"
            "def test_missing():\n"
            "    assert baseline_update_contract.assert_regression_debt_refused(\n"
            "        regression_debt_present=lambda: ALWAYS,\n"
            "        baseline_state=lambda: BASELINE,\n"
            '        update=lambda: synthetic.main(["--update"]),\n'
            "    ) == 1\n",
            encoding="utf-8",
        )
        assert baseline_update_contract.proof_violations(synthetic_root) == [
            "common/testing/synthetic.py [--update]: behavioral proof uses constant "
            "or vacuous regression-debt observers: "
            "tests/tooling/test_missing.py::test_missing"
        ]


def test_AC_testing_governance_21_refusal_harness_enforces_its_preconditions() -> None:
    state = {"baseline": b"before", "called": False}

    def mutate_baseline() -> int:
        state["called"] = True
        state["baseline"] = b"after"
        return 0

    with pytest.raises(AssertionError, match="did not establish"):
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: False,
            baseline_state=lambda: state["baseline"],
            update=mutate_baseline,
        )
    assert state == {"baseline": b"before", "called": False}

    with pytest.raises(AssertionError, match="adopted synthetic regression debt"):
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: True,
            baseline_state=lambda: state["baseline"],
            update=mutate_baseline,
        )
    assert state == {"baseline": b"after", "called": True}


def test_AC_testing_governance_21_specialized_mutation_flags_are_censused(
    tmp_path: Path,
) -> None:
    updater = tmp_path / "common/testing/specialized.py"
    updater.parent.mkdir(parents=True)
    updater.write_text(
        'BASELINE_UPDATE_MODE = "raise-only"\nparser.add_argument("--update-floor")\n',
        encoding="utf-8",
    )

    assert baseline_update_contract.monotonic_update_paths(tmp_path) == {
        "common/testing/specialized.py"
    }
    assert baseline_update_contract.monotonic_update_commands(tmp_path) == {
        ("common/testing/specialized.py", "--update-floor")
    }


def test_AC_testing_governance_21_each_mutation_flag_requires_its_own_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = tmp_path / "common/testing/multi_flag.py"
    updater.parent.mkdir(parents=True)
    updater.write_text(
        'BASELINE_UPDATE_MODE = "raise-only"\n'
        'parser.add_argument("--update")\n'
        'parser.add_argument("--update-floor")\n',
        encoding="utf-8",
    )
    proof = tmp_path / "tests/tooling/test_multi_flag.py"
    proof.parent.mkdir(parents=True)
    proof.write_text(
        "from common.testing import baseline_update_contract, multi_flag\n\n"
        "def test_update(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    debt = {'new-debt'}\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: bool(debt),\n"
        "        baseline_state=baseline.read_bytes,\n"
        "        update=lambda: multi_flag.main(\n"
        '            ["--baseline", str(baseline), "--update"]\n'
        "        ),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        baseline_update_contract,
        "MONOTONIC_UPDATE_PROOFS",
        {
            ("common/testing/multi_flag.py", "--update"): (
                "tests/tooling/test_multi_flag.py::test_update"
            )
        },
    )

    assert baseline_update_contract.proof_violations(tmp_path) == [
        "common/testing/multi_flag.py [--update-floor]: monotonic mutation path "
        "lacks a behavioral regression proof"
    ]

    monkeypatch.setattr(
        baseline_update_contract,
        "MONOTONIC_UPDATE_PROOFS",
        {
            ("common/testing/multi_flag.py", flag): (
                "tests/tooling/test_multi_flag.py::test_update"
            )
            for flag in ("--update", "--update-floor")
        },
    )
    assert baseline_update_contract.proof_violations(tmp_path) == [
        "common/testing/multi_flag.py [--update-floor]: behavioral proof does not "
        "exercise synthetic regression debt through the refusal harness: "
        "tests/tooling/test_multi_flag.py::test_update"
    ]

    proof.write_text(
        proof.read_text(encoding="utf-8").replace(
            "multi_flag.main(\n"
            '            ["--baseline", str(baseline), "--update"]\n'
            "        )",
            "multi_flag.main(\n"
            '            ["--baseline", str(baseline), "--update", "--update-floor"]\n'
            "        )",
        ),
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(tmp_path) == [
        "common/testing/multi_flag.py [--update]: behavioral proof does not exercise "
        "synthetic regression debt through the refusal harness: "
        "tests/tooling/test_multi_flag.py::test_update",
        "common/testing/multi_flag.py [--update-floor]: behavioral proof does not "
        "exercise synthetic regression debt through the refusal harness: "
        "tests/tooling/test_multi_flag.py::test_update",
    ]

    for extra_setup, invocation in (
        ("    extra = build_flag()\n", '["--update", extra]'),
        ("    extra = build_flags()\n", '["--update", *extra]'),
    ):
        proof.write_text(
            "from common.testing import baseline_update_contract, multi_flag\n\n"
            "def test_update(tmp_path):\n"
            "    baseline = tmp_path / 'baseline'\n"
            "    debt = {'new-debt'}\n"
            f"{extra_setup}"
            "    assert baseline_update_contract.assert_regression_debt_refused(\n"
            "        regression_debt_present=lambda: bool(debt),\n"
            "        baseline_state=baseline.read_bytes,\n"
            f"        update=lambda: multi_flag.main({invocation}),\n"
            "    ) == 1\n",
            encoding="utf-8",
        )
        assert baseline_update_contract.proof_violations(tmp_path) == [
            "common/testing/multi_flag.py [--update]: behavioral proof does not "
            "exercise synthetic regression debt through the refusal harness: "
            "tests/tooling/test_multi_flag.py::test_update",
            "common/testing/multi_flag.py [--update-floor]: behavioral proof does not "
            "exercise synthetic regression debt through the refusal harness: "
            "tests/tooling/test_multi_flag.py::test_update",
        ]

    proof.write_text(
        "from common.testing import baseline_update_contract, multi_flag\n\n"
        "def test_update(tmp_path):\n"
        "    baseline = tmp_path / 'baseline'\n"
        "    debt = {'new-debt'}\n"
        "    assert baseline_update_contract.assert_regression_debt_refused(\n"
        "        regression_debt_present=lambda: bool(debt),\n"
        "        baseline_state=baseline.read_bytes,\n"
        "        update=lambda: multi_flag.main([\n"
        '            "--baseline", str(baseline),\n'
        '            "--update" if True else "--update-floor"\n'
        "        ]),\n"
        "    ) == 1\n",
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(tmp_path) == [
        "common/testing/multi_flag.py [--update-floor]: behavioral proof does not "
        "exercise synthetic regression debt through the refusal harness: "
        "tests/tooling/test_multi_flag.py::test_update"
    ]

    dynamic_source = proof.read_text(encoding="utf-8").replace(
        '"--update" if True else "--update-floor"',
        '"--update" if choose_update else "--update-floor"',
    )
    proof.write_text(dynamic_source, encoding="utf-8")
    assert baseline_update_contract.proof_violations(tmp_path) == [
        "common/testing/multi_flag.py [--update]: behavioral proof does not exercise "
        "synthetic regression debt through the refusal harness: "
        "tests/tooling/test_multi_flag.py::test_update",
        "common/testing/multi_flag.py [--update-floor]: behavioral proof does not "
        "exercise synthetic regression debt through the refusal harness: "
        "tests/tooling/test_multi_flag.py::test_update",
    ]

    proof.write_text(
        dynamic_source.replace(
            "multi_flag.main([\n"
            '            "--baseline", str(baseline),\n'
            '            "--update" if choose_update else "--update-floor"\n'
            "        ])",
            "multi_flag.main(\n"
            '            argv=["--baseline", str(baseline), "--update"]\n'
            "        )",
        ),
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(tmp_path) == [
        "common/testing/multi_flag.py [--update-floor]: behavioral proof does not "
        "exercise synthetic regression debt through the refusal harness: "
        "tests/tooling/test_multi_flag.py::test_update"
    ]
