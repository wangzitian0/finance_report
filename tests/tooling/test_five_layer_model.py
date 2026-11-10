from __future__ import annotations; import subprocess; import sys; from pathlib import Path; import pytest; from pydantic import ValidationError; from common.meta import PackageContract; from common.meta.base.layering import LAYER_RANK, PACKAGE_LAYER; from common.meta.extension.check_package_contract import discover_packages; REPO = Path(__file__).resolve().parents[2]
def _contract(name: str, **overrides: object) -> PackageContract: kwargs: dict[str, object] = {'name': name, 'tier': 'CODE-ONLY', 'depends_on': [], 'interface': [], 'events': [], 'invariants': [], 'roadmap': [], 'units': []}; kwargs.update(overrides); return PackageContract(**kwargs)
def test_layer_rank_is_the_five_layer_order() -> None: 'AC-meta.layer.1'; assert LAYER_RANK == {'meta': 0, 'infra': 1, 'middleware': 2, 'domain': 3, 'app': 4}; 'AC-meta.layer.1'; 'AC-meta.layer.1'; assert _contract('synthetic-new', klass='infra').klass == 'infra'; 'AC-meta.layer.2'; 'AC-meta.layer.2'; _m2_missing = [_m2_p.name for _m2_p in discover_packages(REPO) if _m2_p.name not in PACKAGE_LAYER]; assert _m2_missing == [], f'packages with no central placement: {_m2_missing}'; 'AC-meta.layer.2'; 'AC-meta.layer.2'; assert _contract('ledger').klass == 'domain'; assert _contract('runtime').klass == 'infra'; assert _contract('counter').klass == 'middleware'; assert _contract('meta').klass == 'meta'
@pytest.mark.parametrize('legacy', ['kernel', 'platform', 'core'])
def test_old_klass_vocabulary_is_rejected(legacy: str) -> None:
    'AC-meta.layer.1'
    with pytest.raises(ValidationError): _contract('synthetic-legacy', klass=legacy)
def test_declared_klass_must_match_central_map() -> None:
    'AC-meta.layer.2'
    with pytest.raises(ValidationError): _contract('ledger', klass='infra')
    'AC-meta.layer.2'; 'AC-meta.layer.2'
    with pytest.raises(ValidationError): _contract('synthetic-unmapped')
def test_no_depends_on_edge_points_to_a_higher_layer() -> None:
    'AC-meta.layer.3'; offenders: list[str] = []
    for pkg in discover_packages(REPO):
        my_rank = LAYER_RANK[pkg.contract.klass]
        for dep in pkg.contract.depends_on: dep_layer = PACKAGE_LAYER.get(dep); offenders.append(f'{pkg.name} ({pkg.contract.klass}) -> {dep} ({dep_layer})') if dep_layer is not None and LAYER_RANK[dep_layer] > my_rank else None
    assert offenders == [], f'upward depends_on edges: {offenders}'; 'AC-meta.layer.3'; 'AC-meta.layer.3'; _m5_meta, = [_m5_p for _m5_p in discover_packages(REPO) if _m5_p.name == 'meta']; assert _m5_meta.contract.depends_on == []; 'AC-meta.layer.3'; 'AC-meta.layer.3'; _m6_testing, = [_m6_p for _m6_p in discover_packages(REPO) if _m6_p.name == 'testing']; assert 'money' not in _m6_testing.contract.depends_on
@pytest.mark.parametrize('module', ['common.meta.base.layering', 'common.meta.base.authority_matrix'])
def test_layer_vocabulary_imports_without_pydantic(module: str) -> None: 'AC-meta.layer.4'; code = f"import sys; sys.modules['pydantic'] = None; import {module}"; proc = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True, text=True); assert proc.returncode == 0, proc.stderr
def test_readme_links_the_generated_five_layer_topology() -> None: 'AC-meta.layer.5'; text = (REPO / 'common/meta/readme.md').read_text(encoding='utf-8'); assert 'dependency_index' in text; assert 'PACKAGE_LAYER' in text; assert '```mermaid' not in text
