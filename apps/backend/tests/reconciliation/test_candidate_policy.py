"""AC-reconciliation.candidate-policy.1: generated, provider-free policy oracles."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from common.testing.ac_proof import ac_proof

import src.orm_registry  # noqa: F401 -- configure in-memory ORM fixture relationships
from src.audit import JournalEntrySourceType
from src.reconciliation.base.config import DEFAULT_CONFIG
from src.reconciliation.extension import reconciliation_audit as audit
from src.reconciliation.extension.matching import MatchingContext
from src.reconciliation.extension.phases.many_to_one import run_many_to_one_phase
from src.reconciliation.extension.phases.normal_matching import run_normal_matching_phase


@pytest.mark.asyncio
@ac_proof(
    "candidate-policy-live-audit",
    ac_ids=["AC-reconciliation.candidate-policy.1"],
    ci_tier="pr_ci",
    oracle_kind="behavioral",
)
@pytest.mark.parametrize(
    "description,tied,amounts",
    [
        ("Transfer payment", False, ["10.00"]),
        ("Monthly bill", True, ["10.00", "10.00"]),
        ("Monthly bill", False, ["4.00", "6.00"]),
        ("Monthly bill", False, ["2.00", "3.00", "5.00"]),
    ],
)
async def test_live_and_audit_choose_the_same_evidence(description: str, tied: bool, amounts: list[str]) -> None:
    """AC-reconciliation.candidate-policy.1: real rules, not patched candidate scores."""
    txn = audit._txn("policy-fixture", date(2026, 1, 1), description, "10.00", "OUT")
    accounts = audit._scenario_accounts(txn.user_id)
    entries = [
        audit._entry(
            txn.user_id,
            f"entry-{index}",
            txn.txn_date,
            description,
            amount,
            bank_account=accounts["bank"],
            other_account=accounts["expense"],
            direction="OUT",
        )
        for index, amount in enumerate(amounts)
    ]
    entries[0].source_type = JournalEntrySourceType.AUTO_PARSED
    entries[-1].source_type = JournalEntrySourceType.MANUAL
    expected_ids = sorted(str(entry.id) for entry in (entries[-1:] if tied else entries))
    scenario = audit.AuditScenario(
        "policy-fixture",
        "Generated policy oracle",
        (txn,),
        tuple(entries),
        (audit.AuditExpectation(txn.reference, audit.AUTO_ACCEPT, tuple(expected_ids)),),
    )
    observed = audit._evaluate_scenario(scenario, DEFAULT_CONFIG)[0]
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [])))
    repository = SimpleNamespace(claim_transaction=AsyncMock(return_value=None), add_match=AsyncMock())
    context = MatchingContext(
        DEFAULT_CONFIG,
        "SGD",
        {str(entry.id): entry for entry in entries},
        lambda _: entries,
        AsyncMock(return_value=0.0),
    )
    matches = await run_normal_matching_phase(
        db,
        transactions=[txn],
        matched_txn_ids=set(),
        context=context,
        repository=repository,
        user_id=txn.user_id,
    )
    assert len(matches) == 1
    assert sorted(matches[0].journal_entry_ids) == expected_ids
    assert observed["actual_journal_entry_ids"] == expected_ids
    assert observed["score"] == matches[0].match_score
    assert observed["score_breakdown"] == matches[0].score_breakdown


@pytest.mark.asyncio
async def test_batch_policy_preserves_membership_and_source_rank() -> None:
    """AC-reconciliation.candidate-policy.1: no currency/direction group leakage."""
    transactions = [
        audit._txn(f"batch-{index}", date(2026, 1, 1), "Batch settlement", "5.00", "OUT") for index in range(4)
    ]
    transactions[2].currency = "USD"
    transactions[2].amount = Decimal("9999.00")
    transactions[3].direction = "IN"
    transactions[3].amount = Decimal("9999.00")
    txn = transactions[0]
    accounts = audit._scenario_accounts(txn.user_id)
    entries = [
        audit._entry(
            txn.user_id,
            f"batch-entry-{index}",
            txn.txn_date,
            txn.description,
            "10.00",
            bank_account=accounts["bank"],
            other_account=accounts["expense"],
            direction="OUT",
        )
        for index in range(2)
    ]
    entries[0].source_type = JournalEntrySourceType.AUTO_PARSED
    entries[1].source_type = JournalEntrySourceType.MANUAL
    expected_ids = [str(entries[1].id)]
    scenario = audit.AuditScenario(
        "batch-policy",
        "Generated batch policy oracle",
        tuple(transactions),
        tuple(entries),
        tuple(
            audit.AuditExpectation(
                item.reference,
                audit.AUTO_ACCEPT if index < 2 else audit.UNMATCHED,
                tuple(expected_ids) if index < 2 else (),
            )
            for index, item in enumerate(transactions)
        ),
    )
    observed = audit._evaluate_scenario(scenario, DEFAULT_CONFIG)
    repository = SimpleNamespace(claim_transaction=AsyncMock(return_value=None), add_match=AsyncMock())
    context = MatchingContext(
        DEFAULT_CONFIG,
        "SGD",
        {str(entry.id): entry for entry in entries},
        lambda _: entries,
        AsyncMock(return_value=0.0),
    )
    matches = await run_many_to_one_phase(
        AsyncMock(),
        transactions=transactions,
        matched_txn_ids=set(),
        context=context,
        repository=repository,
        user_id=txn.user_id,
    )
    assert {match.atomic_txn_id for match in matches} == {item.id for item in transactions[:2]}
    assert all(row["passed"] for row in observed)
    for row, match in zip(observed[:2], matches, strict=True):
        assert row["actual_journal_entry_ids"] == match.journal_entry_ids == expected_ids
        assert row["score"] == match.match_score
        assert row["score_breakdown"] == match.score_breakdown
