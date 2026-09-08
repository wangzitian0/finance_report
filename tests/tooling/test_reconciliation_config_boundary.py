"""Configuration dependency direction and retirement proofs for #2023."""

import ast
from pathlib import Path

from common.testing.ac_proof import ac_proof

PACKAGE = Path(__file__).resolve().parents[2] / "apps/backend/src/reconciliation"
OWNERS = {
    "load_reconciliation_config": "extension/config.py",
    "_candidate_source_rank": "extension/entry_reads.py",
    "_candidate_is_better": "extension/entry_reads.py",
    "entry_total_amount": "extension/entry_reads.py",
    "entry_bank_side_amount": "extension/entry_reads.py",
    "is_entry_balanced": "extension/entry_reads.py",
}


@ac_proof(
    proof_id="reconciliation_configuration_ownership",
    ac_ids=["AC-reconciliation.config-boundary.1"],
    ci_tier="pr_ci",
)
def test_configuration_ownership_is_explicit():
    """AC-reconciliation.config-boundary.1: no I/O or ledger logic in config values."""
    tree = ast.parse((PACKAGE / "base/config.py").read_text())
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Import, ast.FunctionDef, ast.AsyncFunctionDef))
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            assert node.func.id in {"dataclass", "Decimal", "ReconciliationConfig"}
        if isinstance(node, ast.ImportFrom):
            assert node.module in {"__future__", "dataclasses", "decimal", "src.audit"}
            if node.module == "src.audit":
                assert {name.name for name in node.names} <= {
                    "RECONCILIATION_AUTO_ACCEPT_SCORE",
                    "RECONCILIATION_REVIEW_SCORE",
                }
    found = {name: [] for name in OWNERS}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name in found:
                found[node.name].append(path.relative_to(PACKAGE).as_posix())
            if isinstance(node, ast.ImportFrom) and node.module in {
                "src.reconciliation.base",
                "src.reconciliation.base.config",
            }:
                assert not (set(OWNERS) & {name.name for name in node.names}), path
    assert found == {name: [path] for name, path in OWNERS.items()}
