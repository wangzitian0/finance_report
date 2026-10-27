"""Dependency graph policy: the computed index and its single reuse by the package gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.meta import PackageContract, dependency_index
from common.meta.extension import check_package_contract as package_gate

ROOT = Path(__file__).resolve().parents[2]


def _contract(
    name: str,
    *,
    klass: str,
    depends_on: list[str],
) -> PackageContract:
    return PackageContract(
        name=name,
        klass=klass,  # type: ignore[arg-type]
        tier="CODE-ONLY",
        depends_on=depends_on,
        interface=[],
        events=[],
        invariants=[],
        roadmap=[],
        implementations={"be": None, "fe": None},
    )


def test_AC_meta_dependency_governance_1_projection_has_typed_edges_and_transitive_consumers() -> (
    None
):
    """AC-meta.dependency-governance.1: one pure graph exposes full consumers."""

    provider = _contract("provider", klass="meta", depends_on=[])
    middle = _contract("middle", klass="infra", depends_on=["provider"])
    consumer = _contract("consumer", klass="domain", depends_on=["middle"])

    index = dependency_index([consumer, provider, middle])

    assert index == {
        "edges": [
            {
                "consumer": "consumer",
                "provider": "middle",
                "kind": "compile",
                "detail": "PackageContract.depends_on",
            },
            {
                "consumer": "middle",
                "provider": "provider",
                "kind": "compile",
                "detail": "PackageContract.depends_on",
            },
        ],
        "direct_consumers": {
            "consumer": [],
            "middle": ["consumer"],
            "provider": ["middle"],
        },
        "transitive_consumers": {
            "consumer": [],
            "middle": ["consumer"],
            "provider": ["consumer", "middle"],
        },
    }
    assert dependency_index([middle, consumer, provider]) == index

    with pytest.raises(ValueError, match="unknown package"):
        dependency_index([_contract("broken", klass="domain", depends_on=["missing"])])
    with pytest.raises(ValueError, match="duplicate package"):
        dependency_index([provider, provider])
    with pytest.raises(ValueError, match="duplicate dependency"):
        dependency_index(
            [
                provider,
                _contract(
                    "duplicate",
                    klass="domain",
                    depends_on=["provider", "provider"],
                ),
            ]
        )
    with pytest.raises(ValueError, match="cannot depend on itself"):
        dependency_index([_contract("selfish", klass="domain", depends_on=["selfish"])])
    with pytest.raises(ValueError, match="dependency cycle"):
        dependency_index(
            [
                _contract("first", klass="infra", depends_on=["second"]),
                _contract("second", klass="infra", depends_on=["first"]),
            ]
        )


def test_AC_meta_dependency_governance_1_package_gate_reuses_graph_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-meta.dependency-governance.1: gate and projection share one engine."""

    contracts = [
        _contract("provider", klass="meta", depends_on=[]),
        _contract("consumer", klass="infra", depends_on=["provider"]),
    ]
    discovered = [
        package_gate.DiscoveredPackage(
            name=contract.name,
            spec_dir=ROOT / "common" / contract.name,
            impl_dir=None,
            contract=contract,
        )
        for contract in contracts
    ]
    seen: list[PackageContract] = []

    def build_once(values: list[PackageContract]) -> None:
        seen.extend(values)

    monkeypatch.setattr(package_gate, "build_dependency_graph", build_once)

    assert package_gate._check_no_dependency_cycle(discovered) == []
    assert seen == contracts
