"""Contract tests for the test execution matrix as code (EPIC-008 AC8.22).

The matrix (common/testing/matrix.py) is the SSOT for path→stage
classification and per-stage test selection; docs/ssot/test-execution-matrix.yaml
is its generated view and .github/workflows/preview.yml its runtime consumer
(issues #1547 / #1556).
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from common.testing import matrix

ROOT = Path(__file__).resolve().parents[2]
MATRIX_YAML = ROOT / "docs" / "ssot" / "test-execution-matrix.yaml"
PREVIEW_WORKFLOW = ROOT / ".github" / "workflows" / "preview.yml"
TESTING_README = ROOT / "common" / "testing" / "README.md"
MANIFEST = ROOT / "docs" / "ssot" / "MANIFEST.yaml"


def _preview_e2e_run_step() -> str:
    """Return the End-to-End Tests run block from preview.yml."""
    workflow = PREVIEW_WORKFLOW.read_text(encoding="utf-8")
    marker = "- name: End-to-End Tests"
    assert marker in workflow, "preview.yml End-to-End Tests step not found"
    block = workflow.split(marker, 1)[1]
    return block.split("- name:", 1)[0]


def test_AC8_22_1_generated_matrix_matches_checked_in_yaml() -> None:
    """AC8.22.1: the checked-in YAML is exactly the generated view."""
    assert (
        MATRIX_YAML.read_text(encoding="utf-8") == matrix.emit_execution_matrix_yaml()
    )
    # The CLI drift gate agrees.
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_selection.py"), "--check-matrix"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_AC8_22_1_generated_yaml_parses_identically_for_consumers() -> None:
    """AC8.22.1: the generated view yields the same rules the consumer reads."""
    data = yaml.safe_load(matrix.emit_execution_matrix_yaml())
    parsed = [
        (item["path"], item["stage"], bool(item["ci_required"]))
        for item in data["rules"]
    ]
    expected = [(r.path, r.stage, r.ci_required) for r in matrix.PATH_RULES]
    assert parsed == expected


def test_AC8_22_2_preview_workflow_derives_selection_from_matrix() -> None:
    """AC8.22.2: preview.yml consumes the CLI; no hardcoded whitelist remains."""
    step = _preview_e2e_run_step()
    assert (
        'eval "$(python tools/test_selection.py --stage pr_preview_e2e --shell)"'
        in step
    )
    assert 'pytest "${PR_PREVIEW_E2E_TESTS[@]}"' in step
    assert '-m "$PR_PREVIEW_E2E_MARKER"' in step
    assert '-n "$PR_PREVIEW_E2E_PARALLELISM"' in step
    # The selection lives in the matrix, not the workflow: no literal e2e
    # test path may reappear in the run step.
    assert "tests/e2e/" not in step


def test_AC8_22_3_preview_selection_is_audited_and_dependency_free() -> None:
    """AC8.22.3: selection = audited rows with no external needs; provider-
    dependent specs can never creep into the merge-blocking path."""
    selection = matrix.pr_preview_e2e_selection()
    selected_files = {node.split("::", 1)[0] for node in selection}

    # #1547's ask: the non-LLM vision hard gate runs pre-merge by rule.
    assert "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py" in selected_files
    # The original in-runner set is preserved.
    assert "tests/e2e/test_core_journeys.py" in selected_files
    assert "tests/e2e/test_e2e_flows.py::test_full_navigation" in selection

    for node in selection:
        file = ROOT / node.split("::", 1)[0]
        assert file.exists(), f"selected spec missing on disk: {node}"

    rows_by_file = {row.file: row for row in matrix.E2E_ROWS}
    for file in selected_files:
        row = rows_by_file[file]
        assert row.audited and not row.needs, (
            f"unaudited/dependent row selected: {file}"
        )
        # A spec that spends provider quota (llm marker) must never be
        # selected — verified against the real file, not the row metadata.
        content = (ROOT / file).read_text(encoding="utf-8")
        assert "pytest.mark.llm" not in content, (
            f"llm-marked spec in preview set: {file}"
        )


def test_AC8_22_4_every_root_e2e_spec_has_a_named_row() -> None:
    """AC8.22.4: no ownerless e2e spec — an unclassified file fails CI."""
    on_disk = {
        f"tests/e2e/{p.name}" for p in (ROOT / "tests" / "e2e").glob("test_*.py")
    }
    declared = {row.file for row in matrix.E2E_ROWS}
    assert on_disk == declared, (
        f"undeclared e2e specs: {sorted(on_disk - declared)}; "
        f"stale rows: {sorted(declared - on_disk)}"
    )


def test_AC8_22_5_shell_emission_round_trips() -> None:
    """AC8.22.5: the --shell output is valid bash assignment material."""
    emitted = matrix.emit_shell(matrix.PR_PREVIEW_E2E_STAGE)
    lines = emitted.splitlines()
    assert lines[0].startswith("PR_PREVIEW_E2E_TESTS=(") and lines[0].endswith(")")
    tests = shlex.split(lines[0][len("PR_PREVIEW_E2E_TESTS=(") : -1])
    assert tuple(tests) == matrix.pr_preview_e2e_selection()
    assert shlex.split(lines[1].split("=", 1)[1]) == [matrix.PR_PREVIEW_E2E_MARKER]
    assert lines[2] == f"PR_PREVIEW_E2E_PARALLELISM={matrix.PR_PREVIEW_E2E_PARALLELISM}"

    import pytest as _pytest

    with _pytest.raises(ValueError):
        matrix.emit_shell("nonexistent_stage")


def test_AC8_22_6_charter_and_manifest_ownership() -> None:
    """AC8.22.6: the governance charter exists and MANIFEST ownership moved."""
    readme = TESTING_README.read_text(encoding="utf-8")
    for section in (
        "## Governance charter",
        "### Execution matrix",
        "### Package declaration protocol",
        "### E2E extension layer",
        "### Fast interception",
        "### Responsibility table",
    ):
        assert section in readme, f"charter section missing: {section}"

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    concepts = manifest.get("concepts", manifest)
    entry = concepts["test_execution_matrix"]
    assert entry["owner"] == "common/testing/matrix.py"
    cross_refs = entry.get("cross_refs", [])
    assert "docs/ssot/test-execution-matrix.yaml" in cross_refs
