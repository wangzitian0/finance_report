"""Behavioral locks for the S4 gate-contract slice of #1867."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.meta.extension import check_draft_packages
from common.testing import baseline_update_contract, gate_cli, gate_main_contract
from common.testing.coverage import (
    build_unified_lcov,
    calculate_unified_coverage,
    check_policy,
    diff_coverage,
    merge_lcov,
    strip_lcov_branches,
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
    assert baseline_update_contract.violations(tmp_path) == []

    rewrite.write_text(
        'BASELINE_UPDATE_MODE = "rewrite"\nparser.add_argument("--update")\n',
        encoding="utf-8",
    )
    findings = baseline_update_contract.violations(tmp_path)
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
    (package / "monotonic_rewrite.py").write_text(
        'BASELINE_UPDATE_MODE = "shrink-only"\n'
        'parser.add_argument("--rewrite-baseline")\n',
        encoding="utf-8",
    )
    findings = baseline_update_contract.violations(tmp_path)
    assert len(findings) == 4
    assert any("has no mutation flag" in finding for finding in findings)
    assert any("requires BASELINE_UPDATE_MODE" in finding for finding in findings)
    assert any("--rewrite-baseline requires" in finding for finding in findings)
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
