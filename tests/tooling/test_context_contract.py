"""Bounded-context declaration schema locks for #1897."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from common.meta.base.package_contract import (
    ContextRelation,
    ContextScope,
    PackageContract,
)
from common.meta.extension import check_context_contract

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_AC_meta_context_governance_1_context_scope_rejects_empty_purpose() -> None:
    with pytest.raises(ValueError, match="purpose"):
        ContextScope(purpose="", in_scope=["ledger"], out_of_scope=["reporting"])


def test_context_relation_requires_reason_and_distinct_packages() -> None:
    with pytest.raises(ValueError, match="reason"):
        ContextRelation(
            provider="ledger",
            consumer="reporting",
            mode="published-language",
            reason="",
        )
    with pytest.raises(ValueError, match="different"):
        ContextRelation(
            provider="ledger", consumer="ledger", mode="event", reason="test"
        )


def test_package_context_relationships_are_owned_by_the_consumer() -> None:
    contract = PackageContract(
        name="context-fixture",
        klass="domain",
        depends_on=["ledger"],
        interface=[],
        events=[],
        invariants=[],
        roadmap=[],
        status="draft",
        context=ContextScope(
            purpose="Exercise context-contract validation.",
            in_scope=["fixture semantics"],
            out_of_scope=["production behavior"],
        ),
        relationships=[
            ContextRelation(
                provider="ledger",
                consumer="context-fixture",
                mode="published-language",
                reason="The fixture consumes the ledger's public language.",
            )
        ],
    )
    assert contract.relationships[0].provider == "ledger"

    with pytest.raises(ValueError, match="owned by their consumer"):
        PackageContract(
            name="context-fixture",
            klass="domain",
            depends_on=["ledger"],
            interface=[],
            events=[],
            invariants=[],
            roadmap=[],
            status="draft",
            context=contract.context,
            relationships=[
                ContextRelation(
                    provider="ledger",
                    consumer="reporting",
                    mode="event",
                    reason="Synthetic foreign consumer.",
                )
            ],
        )


def test_context_relationships_require_context_and_declared_provider() -> None:
    relationship = ContextRelation(
        provider="ledger",
        consumer="context-fixture",
        mode="published-language",
        reason="Synthetic contract edge.",
    )
    with pytest.raises(ValueError, match="require a context declaration"):
        PackageContract(
            name="context-fixture",
            klass="domain",
            depends_on=["ledger"],
            interface=[],
            events=[],
            invariants=[],
            roadmap=[],
            status="draft",
            relationships=[relationship],
        )

    with pytest.raises(ValueError, match="declared dependencies"):
        PackageContract(
            name="context-fixture",
            klass="domain",
            depends_on=[],
            interface=[],
            events=[],
            invariants=[],
            roadmap=[],
            status="draft",
            context=ContextScope(
                purpose="Exercise provider validation.",
                in_scope=["fixture semantics"],
                out_of_scope=["production behavior"],
            ),
            relationships=[relationship],
        )


def test_context_contract_baseline_is_exact_on_real_repository() -> None:
    """AC-meta.context-governance.1: context declaration debt only shrinks."""
    assert (
        check_context_contract.violations(
            REPO_ROOT, REPO_ROOT / "common/meta/data/context-contract-baseline.json"
        )
        == []
    )


def test_context_contract_rejects_unclassified_dependency_after_adoption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "common").mkdir()
    contract = PackageContract(
        name="context-fixture",
        klass="domain",
        depends_on=["ledger"],
        interface=[],
        events=[],
        invariants=[],
        roadmap=[],
        status="draft",
        context=ContextScope(
            purpose="Exercise context-contract discovery.",
            in_scope=["fixture semantics"],
            out_of_scope=["production behavior"],
        ),
    )
    monkeypatch.setattr(
        check_context_contract,
        "discover_packages",
        lambda _root: [SimpleNamespace(contract=contract)],
    )
    assert check_context_contract.discover_findings(tmp_path) == [
        "unclassified-relationship::context-fixture::ledger"
    ]
