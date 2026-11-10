import ast; import sys; from pathlib import Path; from common.meta.extension.check_package_contract import check_single_package, discover_packages; REPO = Path(__file__).resolve().parents[2]; COUNTER = REPO / 'apps/backend/src/counter'; _BACKEND_ROOT = str(REPO / 'apps' / 'backend'); sys.path.insert(0, _BACKEND_ROOT) if _BACKEND_ROOT not in sys.path else None
def _imported_modules(path: Path) -> set[str]: mods: set[str] = set(); [mods.add(node.module) if isinstance(node, ast.ImportFrom) and node.module else mods.update((a.name for a in node.names)) if isinstance(node, ast.Import) else None for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))]; return mods
def test_AC_counter_1_1_counter_converges_by_layer():
    assert (COUNTER / 'base/types/key.py').exists(); assert (COUNTER / 'base/types/count.py').exists(); assert (COUNTER / 'base/types/events.py').exists(); assert (COUNTER / 'base/ops/increment.py').exists(); assert (COUNTER / 'base/ops/query.py').exists(); assert (COUNTER / 'base/repository.py').exists(); assert (COUNTER / 'extension/sql.py').exists(); assert (COUNTER / 'extension/facade/write.py').exists(); assert not (COUNTER / 'extension/api').exists(); assert not (COUNTER / 'types').exists() and (not (COUNTER / 'store').exists()); exports = (COUNTER / '__init__.py').read_text(encoding='utf-8')
    for name in ('CounterKey', 'Count', 'Incremented', 'increment', 'get_count'): assert name in exports, f'counter must export {name}'
def test_AC_counter_1_2_base_layer_is_pure():
    offenders: dict[str, set[str]] = {}
    for path in sorted((COUNTER / 'base').rglob('*.py')):
        bad = {m for m in _imported_modules(path) if m.startswith('src.counter.extension') or 'sqlalchemy' in m or m == 'src.database'}
        if bad: offenders[str(path.relative_to(COUNTER))] = bad
    assert not offenders, f'counter base/ reaches into extension/ORM: {offenders}'
def test_AC_counter_1_1_only_all_is_the_published_language(): import src.counter as counter_pkg; from common.counter.contract import CONTRACT; assert sorted(CONTRACT.interface) == sorted(counter_pkg.__all__); assert CONTRACT.name == 'counter'; assert CONTRACT.klass == 'middleware'; assert CONTRACT.implementations['be'] == 'apps/backend/src/counter'
def test_AC_counter_1_4_package_contract_gate_passes_for_counter(): names = {p.name for p in discover_packages(REPO)}; assert 'counter' in names, f'counter not discovered; found {names}'; ok, messages = check_single_package('counter', REPO); assert ok, 'package contract gate failed:\n' + '\n'.join(messages)
