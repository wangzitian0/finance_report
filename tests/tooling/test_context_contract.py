"""Bounded-context declaration schema locks for #1897."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.meta.base.package_contract import (
    ContextRelation,
    ContextScope,
    PackageContract,
)
from common.meta.extension import check_context_contract
from common.meta.package_contract import ContextRelation as FacadeContextRelation
from common.meta.package_contract import ContextScope as FacadeContextScope

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_AC_meta_context_governance_1_context_scope_rejects_empty_purpose() -> None:
    with pytest.raises(ValueError, match="purpose"):
        ContextScope(purpose="", in_scope=["ledger"], out_of_scope=["reporting"])

    with pytest.raises(ValueError, match="in_scope"):
        ContextScope(
            purpose="Exercise scope validation.",
            in_scope=[],
            out_of_scope=["reporting"],
        )

    with pytest.raises(ValueError, match="must not overlap"):
        ContextScope(
            purpose="Exercise scope validation.",
            in_scope=["ledger"],
            out_of_scope=["ledger"],
        )


def test_context_declarations_use_the_stable_package_contract_facade() -> None:
    assert FacadeContextScope is ContextScope
    assert FacadeContextRelation is ContextRelation


def test_context_declarations_use_the_stable_package_contract_facade() -> None:
    assert FacadeContextScope is ContextScope
    assert FacadeContextRelation is ContextRelation


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


def test_context_contract_rejects_invalid_baseline_and_missing_common_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invalid_baseline = tmp_path / "baseline.json"
    invalid_baseline.write_text('{"not": "a list"}', encoding="utf-8")
    assert check_context_contract.violations(tmp_path, invalid_baseline) == [
        "cannot read context-contract baseline: baseline must be a JSON string list"
    ]

    baseline = tmp_path / "valid-baseline.json"
    baseline.write_text("[]", encoding="utf-8")
    assert check_context_contract.violations(tmp_path, baseline) == [
        "cannot discover context contracts: missing common package directory "
        f"{tmp_path / 'common'}"
    ]

    (tmp_path / "common").mkdir()
    monkeypatch.setattr(
        check_context_contract,
        "discover_findings",
        lambda _root: (_ for _ in ()).throw(ValueError("synthetic discovery failure")),
    )
    assert check_context_contract.violations(tmp_path, baseline) == [
        "cannot discover context contracts: synthetic discovery failure"
    ]


def test_context_contract_cli_paths_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert check_context_contract._run_command(["--repo-root", str(REPO_ROOT)]) == 0

    monkeypatch.setattr(check_context_contract, "violations", lambda *_args: ["debt"])
    assert check_context_contract._run_command(["--repo-root", str(REPO_ROOT)]) == 1

    monkeypatch.setattr(check_context_contract, "_run_command", lambda _argv: 2)
    assert check_context_contract.main([]) == 2

    monkeypatch.setattr(
        check_context_contract,
        "_run_command",
        lambda _argv: (_ for _ in ()).throw(SystemExit("invalid arguments")),
    )
    assert check_context_contract.main([]) == 1


def test_context_contract_module_and_tool_entry_points_execute() -> None:
    module_path = REPO_ROOT / "common/meta/extension/check_context_contract.py"
    tool_path = REPO_ROOT / "tools/check_context_contract.py"
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(module_path), run_name="__main__")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(tool_path), run_name="__main__")
