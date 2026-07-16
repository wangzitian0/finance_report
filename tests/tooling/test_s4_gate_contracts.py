"""Behavioral locks for the S4 gate-contract slice of #1867."""

from __future__ import annotations

import importlib
import json
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


def test_AC_testing_governance_17_main_contract_ratchet_rejects_new_debt(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.17: legacy paths shrink and new violations stay red."""

    legacy = tmp_path / "common" / "testing" / "legacy.py"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("def main() -> None:\n    return None\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "legacy_main_contract": ["common/testing/legacy.py"],
                "legacy_gate_cli": [],
            }
        ),
        encoding="utf-8",
    )

    args = ["--repo-root", str(tmp_path), "--baseline", str(baseline)]
    assert gate_main_contract.main(args) == 0

    added = tmp_path / "tools" / "added.py"
    added.parent.mkdir()
    added.write_text("def main() -> None:\n    return None\n", encoding="utf-8")
    before = baseline.read_text(encoding="utf-8")
    assert gate_main_contract.main(args) == 1
    assert gate_main_contract.main([*args, "--update"]) == 1
    assert baseline.read_text(encoding="utf-8") == before

    added.unlink()
    legacy.unlink()
    conforming = tmp_path / "tools" / "conforming.py"
    conforming.write_text(
        "from collections.abc import Sequence\n"
        "def main(argv: Sequence[str] | None = None) -> int:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    assert gate_main_contract.main([*args, "--update"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8")) == {
        "legacy_gate_cli": [],
        "legacy_main_contract": [],
    }

    check_module = tmp_path / "common" / "testing" / "check_new_gate.py"
    check_module.write_text(conforming.read_text(encoding="utf-8"), encoding="utf-8")
    assert gate_main_contract.main(args) == 1

    check_module.unlink()
    baseline.write_text(
        json.dumps(
            {
                "legacy_main_contract": ["tools/resolved.py"],
                "legacy_gate_cli": [],
            }
        ),
        encoding="utf-8",
    )
    assert gate_main_contract.main(args) == 1


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
            regression_debt_present=lambda: check_ac_tier_baseline.current_untagged(
                tmp_path
            )
            > check_ac_tier_baseline.load_baseline(tier_baseline),
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
            regression_debt_present=lambda: set(
                check_app_boundary.discover_and_compute_edges(app_root)
            )
            > check_app_boundary.load_baseline(app_baseline),
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
            regression_debt_present=lambda: json.loads(
                current_scores.read_text(encoding="utf-8")
            )["acs"]["AC-score.1"]["score"]
            < 0.8,
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

    main_root = tmp_path / "main-contract"
    legacy_main = main_root / "common/testing/legacy.py"
    legacy_main.parent.mkdir(parents=True)
    legacy_main.write_text("def main() -> None:\n    return None\n", encoding="utf-8")
    added_main = main_root / "tools/added.py"
    added_main.parent.mkdir()
    added_main.write_text("def main() -> None:\n    return None\n", encoding="utf-8")
    main_baseline = tmp_path / "main-baseline.json"
    main_baseline.write_text(
        json.dumps(
            {
                "legacy_main_contract": ["common/testing/legacy.py"],
                "legacy_gate_cli": [],
            }
        ),
        encoding="utf-8",
    )
    assert (
        baseline_update_contract.assert_regression_debt_refused(
            regression_debt_present=lambda: added_main.exists()
            and "tools/added.py"
            not in json.loads(main_baseline.read_text(encoding="utf-8"))[
                "legacy_main_contract"
            ],
            baseline_state=main_baseline.read_bytes,
            update=lambda: gate_main_contract.main(
                [
                    "--repo-root",
                    str(main_root),
                    "--baseline",
                    str(main_baseline),
                    "--update",
                ]
            ),
        )
        == 1
    )

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
            regression_debt_present=lambda: len(
                (tools_dir / "added.py").read_text(encoding="utf-8").splitlines()
            )
            > 40,
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
        "common/testing/check_ac_score_baseline.py",
        "common/testing/check_cas" + "sette_graded_eval.py",
        "common/testing/check_critical_value_proof.py",
        "common/testing/fe_api_handmock_ratchet.py",
        "common/testing/fe_fetch_ratchet.py",
        "common/testing/gate_main_contract.py",
        "common/testing/mirror_ratchet.py",
        "common/testing/tool_shim_contract.py",
    }
    assert set(baseline_update_contract.MONOTONIC_UPDATE_PROOFS) == update_paths
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
        "common/testing/synthetic.py: monotonic --update path lacks a behavioral "
        "regression proof"
    ]

    monkeypatch.setattr(
        baseline_update_contract,
        "MONOTONIC_UPDATE_PROOFS",
        {"common/testing/synthetic.py": "tests/tooling/test_missing.py::test_missing"},
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py: behavioral proof node does not exist: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file = synthetic_root / "tests/tooling/test_missing.py"
    proof_file.parent.mkdir(parents=True)
    proof_file.write_text("def test_missing():\n    assert True\n", encoding="utf-8")
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py: behavioral proof does not exercise synthetic "
        "regression debt through the refusal harness: "
        "tests/tooling/test_missing.py::test_missing"
    ]

    proof_file.write_text(
        "from common.testing import synthetic\n\n"
        "def test_missing():\n"
        '    assert synthetic.main(["--update"]) == 1\n',
        encoding="utf-8",
    )
    assert baseline_update_contract.proof_violations(synthetic_root) == [
        "common/testing/synthetic.py: behavioral proof does not exercise "
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
    assert baseline_update_contract.proof_violations(synthetic_root) == []


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
