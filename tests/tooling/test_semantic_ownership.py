"""Semantic owner projection locks for #1897."""

from __future__ import annotations

from types import SimpleNamespace

from common.meta.base.package_contract import Kind, Unit
from common.meta.extension.check_semantic_ownership import duplicate_claims, main


def test_AC_meta_context_governance_2_duplicate_semantic_owner_fails() -> None:
    """AC-meta.context-governance.2: a canonical semantic claim has one owner."""
    packages = [
        SimpleNamespace(
            name="first",
            contract=SimpleNamespace(units=[Unit(name="Position", kind=Kind.ENTITY)]),
        ),
        SimpleNamespace(
            name="second",
            contract=SimpleNamespace(units=[Unit(name="Position", kind=Kind.ENTITY)]),
        ),
    ]
    assert duplicate_claims(packages) == [
        "duplicate semantic owner: entity::Position::first,second"
    ]


def test_same_spelling_needs_explicit_distinct_semantic_keys() -> None:
    packages = [
        SimpleNamespace(
            name="measurement",
            contract=SimpleNamespace(
                units=[
                    Unit(
                        name="Unit",
                        kind=Kind.VALUE_OBJECT,
                        semantic_key="measurement-unit",
                    )
                ]
            ),
        ),
        SimpleNamespace(
            name="governance",
            contract=SimpleNamespace(
                units=[
                    Unit(
                        name="Unit",
                        kind=Kind.VALUE_OBJECT,
                        semantic_key="package-unit",
                    )
                ]
            ),
        ),
    ]
    assert duplicate_claims(packages) == []


def test_semantic_ownership_is_exact_on_real_repository() -> None:
    assert main() == 0
