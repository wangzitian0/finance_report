from __future__ import annotations; from dataclasses import dataclass; import pytest; from common.meta.base.dependency_graph import DependencyEdge, DependencyKind, build_dependency_graph
@dataclass(frozen=True)
class _Decl:
    name: str
    depends_on: tuple[str, ...]
def test_AC_meta_dependency_governance_1_graph_builds_edges_and_rejects_cycles() -> None:
    'AC-meta.dependency-governance.1'
    provider = _Decl('provider', ()); middle = _Decl('middle', ('provider',)); consumer = _Decl('consumer', ('middle',))
    graph = build_dependency_graph([consumer, provider, middle])
    assert graph.edges == (
        DependencyEdge('consumer', 'middle', DependencyKind.COMPILE, 'PackageContract.depends_on'),
        DependencyEdge('middle', 'provider', DependencyKind.COMPILE, 'PackageContract.depends_on'),
    )
    with pytest.raises(ValueError, match='unknown package'): build_dependency_graph([_Decl('broken', ('missing',))])
    with pytest.raises(ValueError, match='duplicate package'): build_dependency_graph([provider, provider])
    with pytest.raises(ValueError, match='duplicate dependency'): build_dependency_graph([provider, _Decl('duplicate', ('provider', 'provider'))])
    with pytest.raises(ValueError, match='cannot depend on itself'): build_dependency_graph([_Decl('selfish', ('selfish',))])
    with pytest.raises(ValueError, match='dependency cycle'): build_dependency_graph([_Decl('first', ('second',)), _Decl('second', ('first',))])
