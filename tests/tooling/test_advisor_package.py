'AC-advisor.txn.1'; from __future__ import annotations; import ast; from pathlib import Path; ROOT = Path(__file__).resolve().parents[2]; FORBIDDEN_PREFIXES = ('src.services', 'src.prompts', 'src.routers', 'src.models.chat')
def _advisor_impl_dir() -> Path: from common.advisor.contract import CONTRACT; be_impl = CONTRACT.implementations.get('be'); assert be_impl, "AC-advisor.txn.1: contract.implementations['be'] is not set — the advisor package has no physical implementation to hold its boundary."; impl = ROOT / be_impl; services_root = ROOT / 'apps' / 'backend' / 'src' / 'services'; assert not impl.resolve().is_relative_to(services_root.resolve()), f"AC-advisor.txn.1: implementations['be']={be_impl!r} still points into the app remainder (services/) — the physical move has not happened."; return impl
def test_AC_advisor_txn_1_impl_exists_at_contracted_path() -> None: 'AC-advisor.txn.1'; impl = _advisor_impl_dir(); assert (impl / '__init__.py').exists(), f'{impl} has no __init__.py'
def test_AC_advisor_txn_1_reads_only_published_interfaces() -> None:
    'AC-advisor.txn.1'; impl = _advisor_impl_dir(); offenders: list[str] = []
    for py in sorted(impl.rglob('*.py')):
        tree = ast.parse(py.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module: modules = [node.module]
            elif isinstance(node, ast.Import): modules = [alias.name for alias in node.names]
            [offenders.append(f'{py.relative_to(ROOT)}: imports {module}') if any((module == prefix or module.startswith(f'{prefix}.') for prefix in FORBIDDEN_PREFIXES)) else None for module in modules]
    assert offenders == [], 'AC-advisor.txn.1: advisor reads must go through published package roots or the registered app_reads ports, never internal service paths:\n' + '\n'.join(offenders); 'AC-advisor.txn.1'; 'AC-advisor.txn.1'; from common.meta.extension.check_package_contract import check_single_package; _m1_ok, _m1_errors = check_single_package('advisor', ROOT); _m1_advisor_errors = [_m1_e for _m1_e in _m1_errors if _m1_e.startswith('[advisor]')]; assert _m1_advisor_errors == [], '\n'.join(_m1_advisor_errors); assert _m1_ok, '\n'.join(_m1_errors)
