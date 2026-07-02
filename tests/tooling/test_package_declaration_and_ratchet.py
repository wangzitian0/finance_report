"""Package test-root declarations + mirror-assertion ratchet (EPIC-008
AC8.24, issue #1558)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.testing import matrix, mirror_ratchet

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_24_1_seed_packages_declare_owned_test_roots() -> None:
    """AC8.24.1: the seed packages' contract.py TEST_ROOTS aggregate into the
    matrix ownership view; every declared root exists; the generated YAML
    carries the view (so a dropped declaration fails the drift gate)."""
    ownership = matrix.package_test_ownership()
    assert set(ownership.values()) == set(matrix.PACKAGE_TEST_DECLARATIONS)
    for root in ownership:
        assert (ROOT / root).exists(), f"declared test root missing on disk: {root}"

    yaml_text = (ROOT / "docs" / "ssot" / "test-execution-matrix.yaml").read_text(
        encoding="utf-8"
    )
    assert "ownership:" in yaml_text
    for root, pkg in ownership.items():
        assert f"  - path: {root}\n    package: {pkg}" in yaml_text


def test_AC8_24_1_duplicate_declaration_is_rejected(monkeypatch) -> None:
    """AC8.24.1: two packages declaring the same root is an aggregation error."""
    import common.ledger.contract as ledger_contract

    monkeypatch.setattr(
        ledger_contract, "TEST_ROOTS", ("apps/backend/tests/infra/test_main.py",)
    )
    with pytest.raises(ValueError, match="declared by both"):
        matrix.package_test_ownership()


def test_AC8_24_2_e2e_stages_run_their_environment_precondition_first() -> None:
    """AC8.24.2: contracts declaring a precondition (runtime's smoke gate)
    must run it BEFORE the pytest invocation in the same workflow — a red
    precondition is an environment failure, so the tests never start."""
    with_precondition = [c for c in matrix.WORKFLOW_PYTEST_CONTRACTS if c.precondition]
    assert {c.stage for c in with_precondition} == {
        matrix.PR_PREVIEW_E2E_STAGE,
        "staging_core_e2e",
    }
    for contract in with_precondition:
        text = (ROOT / contract.workflow).read_text(encoding="utf-8")
        assert contract.precondition in text, (
            f"{contract.stage}: precondition {contract.precondition!r} not found "
            f"in {contract.workflow}"
        )
        assert text.index(contract.precondition) < text.index(contract.anchor), (
            f"{contract.stage}: precondition must run before the pytest "
            f"invocation in {contract.workflow}"
        )


def test_AC8_24_3_mirror_assertion_ratchet_is_locked_and_only_goes_down(
    monkeypatch, tmp_path
) -> None:
    """AC8.24.3: the committed baseline holds, growth fails, --update refuses
    to raise the baseline."""
    assert mirror_ratchet.main([]) == 0

    # Simulate growth: a synthetic tooling dir with one extra mirror assert.
    fake_dir = tmp_path / "tooling"
    fake_dir.mkdir()
    (fake_dir / "test_fake.py").write_text(
        'def test_x():\n    assert "literal" in open("f").read()\n',
        encoding="utf-8",
    )
    fake_baseline = tmp_path / "baseline.json"
    fake_baseline.write_text(json.dumps({"total": 0}), encoding="utf-8")
    monkeypatch.setattr(mirror_ratchet, "TOOLING_DIR", fake_dir)
    monkeypatch.setattr(mirror_ratchet, "BASELINE_PATH", fake_baseline)
    assert mirror_ratchet.main([]) == 1
    assert mirror_ratchet.main(["--update"]) == 1  # refuses to raise
    assert json.loads(fake_baseline.read_text())["total"] == 0

    # Paydown may lower it.
    fake_baseline.write_text(json.dumps({"total": 5}), encoding="utf-8")
    assert mirror_ratchet.main(["--update"]) == 0
    assert json.loads(fake_baseline.read_text())["total"] == 1
