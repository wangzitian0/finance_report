"""reporting package — package-model structural invariants for Stage-4 cutover."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
REPORTING = REPO / "apps/backend/src/services/reporting"

_BACKEND_ROOT = str(REPO / "apps" / "backend")
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _static_all(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__all__" and node.value is not None:
                value = ast.literal_eval(node.value)
                return [str(item) for item in value]
    raise AssertionError(f"missing __all__ in {path}")


def test_AC_reporting_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    from common.reporting.contract import CONTRACT

    published = _static_all(REPORTING / "__init__.py")
    assert sorted(CONTRACT.interface) == sorted(published)
    assert CONTRACT.name == "reporting"
    assert CONTRACT.implementations["be"] == "apps/backend/src/services/reporting"


def test_AC_reporting_1_2_cutover_inventory_is_declared():
    """Invariant reporting-cutover-inventory-declared: key reporting lanes are declared in units."""
    from common.reporting.contract import CONTRACT

    expected_modules = {
        "balance_sheet.py",
        "income_statement.py",
        "cash_flow.py",
        "_core.py",
        "net_worth.py",
        "lineage.py",
    }
    declared_modules = {unit.module for unit in CONTRACT.units if unit.module}
    assert expected_modules.issubset(declared_modules)

    for rel in expected_modules:
        assert (REPORTING / rel).exists(), f"declared reporting module missing: {rel}"

    declared_names = {unit.name for unit in CONTRACT.units}
    assert declared_names >= {"ReportingReadRepository", "ReportSnapshotProjection"}


def test_AC_reporting_1_3_manual_valuation_is_not_published_reporting_surface():
    """Invariant manual-valuation-excluded-from-reporting-language: reporting does not publish manual valuation APIs."""
    from common.reporting.contract import CONTRACT

    published = set(_static_all(REPORTING / "__init__.py"))
    assert published.isdisjoint({"manual_valuation", "record_manual_valuation"})
    reporting_py_files = {p.name for p in REPORTING.glob("*.py")}
    assert reporting_py_files >= {"manual_valuation.py"}, (
        "current inventory still includes manual_valuation.py until pricing cutover removes it"
    )
    assert {unit.name for unit in CONTRACT.units}.isdisjoint({"ManualValuationSnapshot"})


def test_AC_reporting_1_4_package_contract_gate_passes():
    """Invariant passes-own-governance-gate: the gate validates reporting with no violations."""
    packages = discover_packages(REPO)
    assert any(p.contract.name == "reporting" for p in packages), "reporting not discovered"
    ok, messages = run(REPO)
    reporting_errors = [m for m in messages if "[reporting]" in m]
    assert not reporting_errors, f"gate violations for reporting: {reporting_errors}"
    assert ok, "check_package_contract failed overall"
