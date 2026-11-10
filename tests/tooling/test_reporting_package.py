from __future__ import annotations; import ast; import sys; from pathlib import Path; from common.meta.extension.check_package_contract import check_single_package, discover_packages; REPO = Path(__file__).resolve().parents[2]; REPORTING = REPO / 'apps/backend/src/reporting'; LEGACY_REPORTING = REPO / 'apps/backend/src/services/reporting'; _BACKEND_ROOT = str(REPO / 'apps' / 'backend'); sys.path.insert(0, _BACKEND_ROOT) if _BACKEND_ROOT not in sys.path else None
def _static_all(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign): targets = node.targets
        elif isinstance(node, ast.AnnAssign): targets = [node.target]
        else: continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == '__all__' and (node.value is not None): value = ast.literal_eval(node.value); return [str(item) for item in value]
    raise AssertionError(f'missing __all__ in {path}')
def test_AC_reporting_1_1_only_all_is_the_published_language(): from common.reporting.contract import CONTRACT; published = _static_all(REPORTING / '__init__.py'); assert sorted(CONTRACT.interface) == sorted(published); assert CONTRACT.name == 'reporting'; assert CONTRACT.implementations['be'] == 'apps/backend/src/reporting'
def test_AC_reporting_1_2_cutover_inventory_is_declared():
    from common.reporting.contract import CONTRACT; expected_modules = {'extension/balance_sheet.py', 'extension/income_statement.py', 'extension/cash_flow.py', 'extension/_core.py', 'extension/net_worth.py', 'extension/lineage.py'}; declared_modules = {unit.module for unit in CONTRACT.units if unit.module}; assert expected_modules.issubset(declared_modules)
    for rel in expected_modules: assert (REPORTING / rel).exists(), f'declared reporting module missing: {rel}'
    declared_names = {unit.name for unit in CONTRACT.units}; assert declared_names >= {'ReportingReadRepository', 'ReportSnapshotProjection'}
def test_AC_reporting_1_3_manual_valuation_is_not_published_reporting_surface(): from common.reporting.contract import CONTRACT; published = set(_static_all(REPORTING / '__init__.py')); assert published.isdisjoint({'manual_valuation', 'record_manual_valuation'}); reporting_py_files = {p.name for p in REPORTING.rglob('*.py')}; assert reporting_py_files.isdisjoint({'manual_valuation.py'}), 'manual_valuation.py must not fold into the reporting package (pricing owns it, #1610)'; legacy_py_files = list(LEGACY_REPORTING.rglob('*.py')) if LEGACY_REPORTING.exists() else []; assert legacy_py_files == [], f'the pricing cutover (#1610 P2) absorbed manual_valuation.py into pricing/extension/valuation.py; the legacy services/reporting/ directory must not carry tracked source again, found: {legacy_py_files}'; assert {unit.name for unit in CONTRACT.units}.isdisjoint({'ManualValuationSnapshot'})
def test_AC_reporting_1_4_package_contract_gate_passes(): packages = discover_packages(REPO); assert any((p.contract.name == 'reporting' for p in packages)), 'reporting not discovered'; ok, messages = check_single_package('reporting', REPO); reporting_errors = [m for m in messages if '[reporting]' in m]; assert not reporting_errors, f'gate violations for reporting: {reporting_errors}'; assert ok, 'check_package_contract failed for reporting:\n' + '\n'.join(messages)
