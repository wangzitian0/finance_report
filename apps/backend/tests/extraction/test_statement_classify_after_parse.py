from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.config import settings
from src.extraction import BankStatementStatus, StatementIngestionStatus
from src.extraction.extension import statement_classification_run, transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.transaction_classification import CategoryProposal
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from tests.extraction._statement_run_helpers import (
    EXTENDED_ANSWERS as ANSWERS,
    Proposer,
    _use_case,
    add_coffee_rule,
    approve_statement,
    classify_outcome,
    confirm_csv_envelope,
    ingest_csv_statement,
    install_proposer,
    make_parse_job,
    make_rows,
    posted_accounts_for_coffee,
    read_classify_state,
    seed_classify_statement,
    spy_classify_outcomes,
    user_classification_rows,
    verify_each_row_gets_own_date_policy,
    verify_failed_run_leaves_rows_to_review,
    verify_provider_no_call_at_approve,
    verify_shared_rows_answered_once,
    verify_source_bytes_released_before_model,
    verify_state_after_parse_classify_approve,
    verify_unresolved_currency_and_covered_rows,
)
from tests.factories import StatementSummaryFactory
from tests.statement_ingestion import classify_statement, run_for

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _automatic_path(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


def _proposer(**kwargs) -> Proposer:
    return Proposer(answers=ANSWERS, timeout_gate=True, **kwargs)


async def test_AC_extraction_statement_classify_1_parse_classifies_and_approve_makes_zero_model_calls(
    client, db, test_user, monkeypatch
):
    proposer, rows = install_proposer(monkeypatch, _proposer()), make_rows(12)
    statement_id = await ingest_csv_statement(db, test_user.id, "jan.csv", rows)
    assert (await db.get(StatementSummary, statement_id)).status is BankStatementStatus.PARSED and (
        proposer.rows_asked,
        len(await user_classification_rows(db, test_user.id)),
    ) == (12, 12)
    await confirm_csv_envelope(client, db, test_user.id, statement_id, rows)
    response = await approve_statement(client, statement_id)
    assert (
        response.status_code,
        response.json()["journal_entries_created"],
        proposer.rows_asked,
        len(proposer.calls),
    ) == (200, 12, 12, 1)


async def test_AC_extraction_statement_classify_1_the_provider_gets_no_call_at_approve(
    client, db, test_user, monkeypatch
):
    await verify_provider_no_call_at_approve(client, db, test_user, monkeypatch)


async def test_AC_extraction_statement_classify_1_a_pdf_payload_is_classified_after_parse_too(
    db, test_user, monkeypatch
):
    proposer, rows = install_proposer(monkeypatch, _proposer()), make_rows(3)
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "DBS",
            "currency": "SGD",
            "transactions": [
                {
                    "date": r["date"].isoformat(),
                    "description": r["description"],
                    "amount": str(r["amount"]),
                    "direction": r["direction"].value,
                    "currency": "SGD",
                }
                for r in rows
            ],
        }
    )
    content = b"%PDF-1.7 classify after parse"
    file_hash = hashlib.sha256(content).hexdigest()
    stmt = StatementSummaryFactory.build(
        id=uuid4(), user_id=test_user.id, status=BankStatementStatus.PARSING, file_hash=file_hash, institution="DBS"
    )
    db.add(stmt)
    await db.commit()
    outcome = await _use_case(db, service).execute(
        make_parse_job(stmt.id, test_user.id, "jan.pdf", file_hash, await run_for(db, stmt.id)), content=content
    )
    assert (
        outcome.status,
        (await db.get(StatementSummary, stmt.id)).status,
        proposer.rows_asked,
        len(await user_classification_rows(db, test_user.id)),
    ) == (StatementIngestionStatus.COMPLETED, BankStatementStatus.PARSED, 3, 3)


async def test_AC_extraction_statement_classify_6_the_source_bytes_are_released_before_the_model_is_asked(
    db, test_user, monkeypatch
):
    await verify_source_bytes_released_before_model(db, test_user, monkeypatch)


@pytest.mark.parametrize(
    ("failure", "label"), [("provider-error", "partial"), ("unexpected-error", "failed"), ("driver-timeout", "failed")]
)
async def test_AC_extraction_statement_classify_2_a_failed_run_leaves_the_rows_to_the_economic_review(
    client, db, test_user, monkeypatch, failure, label
):
    await verify_failed_run_leaves_rows_to_review(client, db, test_user, monkeypatch, failure, label)


async def test_AC_extraction_statement_classify_3_a_second_run_asks_no_row_that_has_an_answer(
    db, test_user, monkeypatch
):
    outcomes, proposer = spy_classify_outcomes(monkeypatch), install_proposer(monkeypatch, _proposer())
    seeded = await seed_classify_statement(db, test_user.id, make_rows(6), name="seeded.pdf")
    assert (
        await classify_outcome(db, seeded.id),
        await classify_outcome(db, seeded.id),
        outcomes,
        proposer.rows_asked,
        len(await user_classification_rows(db, test_user.id)),
    ) == ("classified", "nothing_to_classify", ["classified", "nothing_to_classify"], 6, 6)


async def test_AC_extraction_statement_classify_3_two_statements_that_share_rows_answer_each_row_once(
    db, test_user, monkeypatch
):
    await verify_shared_rows_answered_once(db, test_user, monkeypatch)


@pytest.mark.parametrize("setting", ["enable_ai_classification", "auto_accept_ai_suggestions"])
async def test_AC_extraction_statement_classify_3_a_setting_turned_off_after_the_run_does_not_undo_its_rows(
    client, db, test_user, monkeypatch, setting
):
    proposer = install_proposer(monkeypatch, _proposer())
    seeded = await seed_classify_statement(
        db, test_user.id, make_rows(6, kinds=["Salary", "Coffee", "Fee", "Mystery", "Odd", "Grab"]), name="seeded.pdf"
    )
    await classify_statement(db, seeded.id)
    stored = await user_classification_rows(db, test_user.id)
    assert (proposer.rows_asked, len(stored), {r.status.value for r in stored}) == (6, 6, {"applied"})
    monkeypatch.setattr(settings, setting, False)
    response = await approve_statement(client, seeded.id)
    assert (
        response.status_code == 409
        and "Economic review required" in response.json()["detail"]
        and (proposer.rows_asked, len(await user_classification_rows(db, test_user.id))) == (6, 6)
    )


async def test_AC_extraction_statement_classify_3_a_row_above_the_gate_posts_when_the_model_is_turned_off_later(
    client, db, test_user, monkeypatch
):
    proposer = install_proposer(monkeypatch, _proposer())
    seeded = await seed_classify_statement(db, test_user.id, make_rows(6), name="seeded.pdf")
    await classify_statement(db, seeded.id)
    assert (
        proposer.rows_asked == 6
        and min(r.confidence_score for r in await user_classification_rows(db, test_user.id)) >= 90
    )
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    response = await approve_statement(client, seeded.id)
    assert (response.status_code, response.json()["journal_entries_created"], proposer.rows_asked) == (200, 6, 6)


async def test_AC_extraction_statement_classify_3_a_run_without_a_usable_answer_writes_no_rule_row(
    db, test_user, monkeypatch
):
    monkeypatch.setattr(
        transaction_classification,
        "propose_categories",
        AsyncMock(
            side_effect=lambda txns, _p: [
                CategoryProposal(category="FOOD_AND_DRINK", confidence=95, reason="outside") for _ in txns
            ]
        ),
    )
    seeded = await seed_classify_statement(db, test_user.id, make_rows(3), name="seeded.pdf")
    assert (
        await classify_outcome(db, seeded.id) == "partial"
        and await db.scalar(
            select(func.count())
            .select_from(ClassificationRule)
            .where(
                ClassificationRule.user_id == test_user.id,
                ClassificationRule.rule_name == transaction_classification.POLICY_RULE_NAME,
            )
        )
        == 0
    )


async def test_AC_extraction_statement_classify_4_each_row_gets_the_policy_of_its_own_date(db, test_user, monkeypatch):
    await verify_each_row_gets_own_date_policy(db, test_user, monkeypatch)


@pytest.mark.parametrize("rerun_after_rule", [False, True])
async def test_AC_extraction_statement_classify_4_rule_applied_only_on_next_run(
    client, db, test_user, monkeypatch, rerun_after_rule
):
    proposer, seeded = (
        install_proposer(monkeypatch, _proposer()),
        await seed_classify_statement(db, test_user.id, make_rows(5), name="seeded.pdf"),
    )
    await classify_statement(db, seeded.id)
    rule_account_id = await add_coffee_rule(db, test_user.id)
    if rerun_after_rule:
        await classify_statement(db, seeded.id)
    response = await approve_statement(client, seeded.id)
    assert (response.status_code, response.json()["journal_entries_created"], proposer.rows_asked) == (200, 5, 5) and (
        rule_account_id in await posted_accounts_for_coffee(db, test_user.id)
    ) is rerun_after_rule


async def test_AC_extraction_statement_classify_4_unresolved_currency_and_covered_rows_are_left_alone(
    client, db, test_user, monkeypatch
):
    await verify_unresolved_currency_and_covered_rows(client, db, test_user, monkeypatch)


@pytest.mark.parametrize(
    ("state", "label"), [("approved", "skipped_state"), ("rejected", "skipped_state"), ("ai-off", "skipped_disabled")]
)
async def test_AC_extraction_statement_classify_4_the_run_leaves_a_statement_that_is_not_parsed_or_has_the_model_off(
    db, test_user, monkeypatch, state, label
):
    proposer, seeded = (
        install_proposer(monkeypatch, _proposer()),
        await seed_classify_statement(db, test_user.id, make_rows(4), name="seeded.pdf"),
    )
    if state == "approved":
        bank = Account(
            user_id=test_user.id, name="Bank of an approved statement", type=AccountType.ASSET, currency="SGD"
        )
        db.add(bank)
        await db.flush()
        seeded.statement.account_id, seeded.statement.status = bank.id, BankStatementStatus.APPROVED
    elif state == "rejected":
        seeded.statement.status = BankStatementStatus.REJECTED
    else:
        monkeypatch.setattr(settings, "enable_ai_classification", False)
    await db.commit()
    assert (
        await classify_outcome(db, seeded.id),
        proposer.calls,
        await user_classification_rows(db, test_user.id),
    ) == (label, [], [])


async def test_AC_extraction_statement_classify_4_a_statement_without_rows_or_with_unresolvable_rows_is_left_alone(
    db, test_user, monkeypatch
):
    proposer = install_proposer(monkeypatch, _proposer())
    empty, seeded = (
        await seed_classify_statement(db, test_user.id, [], name="empty.pdf"),
        await seed_classify_statement(db, test_user.id, make_rows(3), name="seeded.pdf"),
    )
    assert await classify_outcome(db, empty.id) == "nothing_to_classify"
    monkeypatch.setattr(
        statement_classification_run,
        "resolve_statement_transactions",
        AsyncMock(side_effect=ValueError("Current source transaction identity requires review")),
    )
    assert (await classify_outcome(db, seeded.id), proposer.calls) == ("skipped_state", [])


async def test_AC_extraction_statement_classify_5_state_after_parse_classify_approve(
    client, db, test_user, monkeypatch
):
    await verify_state_after_parse_classify_approve(client, db, test_user, monkeypatch)


async def test_AC_extraction_statement_classify_5_review_path_requires_review_for_low_confidence(
    client, db, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    proposer, rows = (
        install_proposer(monkeypatch, _proposer()),
        make_rows(6, kinds=["Salary", "Coffee", "Fee", "Mystery", "Transfer", "Grab"]),
    )
    sid = await ingest_csv_statement(db, test_user.id, "classify_review_path.csv", rows)
    await confirm_csv_envelope(client, db, test_user.id, sid, rows)
    assert (await approve_statement(client, sid)).status_code == 409
    state = await read_classify_state(client, db, test_user.id)
    assert ({r.status for r in state["classifications"]}, len(state["classifications"]), proposer.rows_asked) == (
        {"applied", "draft"},
        5,
        6,
    )


async def test_AC_extraction_2813_3_propose_batch_pins_deterministic_decode(db, test_user, monkeypatch):
    from src.extraction.extension.transaction_classification import POLICY_VERSIONS, _propose_batch

    captured: dict = {}

    async def _stream():
        yield '[{"index": 0, "category": "DINING", "confidence": 92, "reason": "coffee"}]'

    monkeypatch.setattr("src.llm.stream_ai_json", lambda **kw: (captured.update(kw), _stream())[1])
    dummy = AtomicTransaction(
        id=uuid4(),
        user_id=test_user.id,
        txn_date=date(2026, 1, 2),
        amount=Decimal("12.50"),
        direction="OUT",
        description="Coffee 000",
        currency="SGD",
        dedup_hash="a" * 64,
        source_documents=[],
    )
    proposals = await _propose_batch([dummy], POLICY_VERSIONS[-1], test_user.id)
    assert (
        proposals[0] is not None
        and proposals[0].category == "DINING"
        and (captured.get("temperature"), captured.get("do_sample"), captured.get("max_tokens"))
        == (0.0, False, settings.ai_json_max_tokens)
        and "thinking" in captured
    )
