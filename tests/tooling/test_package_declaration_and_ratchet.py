'EPIC-008'; from __future__ import annotations; from pathlib import Path; import pytest; from common.testing import matrix; ROOT = Path(__file__).resolve().parents[2]
def test_AC8_24_1_seed_packages_declare_owned_test_roots() -> None:
    'AC-testing.declarations.1 AC8.24.1'; ownership = matrix.package_test_ownership(); assert set(ownership.values()) == set(matrix.PACKAGE_TEST_DECLARATIONS)
    for root in ownership: assert (ROOT / root).exists(), f'declared test root missing on disk: {root}'
    yaml_text = (ROOT / 'common' / 'testing' / 'data' / 'test-execution-matrix.yaml').read_text(encoding='utf-8'); assert 'ownership:' in yaml_text; assert all((f'  - path: {root}\n    package: {pkg}' in yaml_text for root, pkg in ownership.items()))
def test_AC8_24_1_duplicate_declaration_is_rejected(monkeypatch) -> None:
    'AC8.24.1'; import importlib; ledger_contract = importlib.import_module('common.ledger.contract'); monkeypatch.setattr(ledger_contract, 'TEST_ROOTS', ('apps/backend/tests/infra/test_main.py',))
    with pytest.raises(ValueError, match='declared by both'): matrix.package_test_ownership()
def test_AC8_24_2_e2e_stages_run_their_environment_precondition_first() -> None:
    'AC-testing.declarations.2 AC8.24.2'; with_precondition = [c for c in matrix.WORKFLOW_PYTEST_CONTRACTS if c.precondition]; assert {c.stage for c in with_precondition} == {'staging_core_e2e'}
    for contract in with_precondition: text = (ROOT / contract.workflow).read_text(encoding='utf-8'); assert contract.precondition in text, f'{contract.stage}: precondition {contract.precondition!r} not found in {contract.workflow}'; assert text.index(contract.precondition) < text.index(contract.anchor), f'{contract.stage}: precondition must run before the pytest invocation in {contract.workflow}'
