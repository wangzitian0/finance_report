from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.extraction import BankStatementStatus, Stage1Status
from src.extraction.base.source_balance_check import SourceBalanceVerdict, check_closing_balance_against_text, text_money_values
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.orm.statement_summary import StatementSummary
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account
from tests.statement_ingestion import posting_dependencies

OPENING = Decimal("2000.00")
AMOUNTS = [Decimal("3000.00"), Decimal("1.50"), Decimal("85.40"), Decimal("23.60"), Decimal("55.00")]
PRINTED_STATEMENT = (
    "Stage One Routing Bank\nAccount 5551-234-7702\nStatement period 2026-05-01 to 2026-05-31\n"
    "Opening Balance 2000.00\n2026-05-02 Salary Acme Pte Ltd 3000.00\n2026-05-03 Interest 1.50\n"
    "2026-05-10 Grocery Market -85.40\n2026-05-12 Phone Plan -23.60\n2026-05-20 Coffee House -55.00\n"
    "Total Credits 3001.50\nTotal Debits 164.00\nClosing Balance 4837.55\nClosing Balance 4837.55\n"
)


def _verdict(text: str | None, closing: str | None, **overrides) -> SourceBalanceVerdict:
    return check_closing_balance_against_text(text, closing=None if closing is None else Decimal(closing), opening=overrides.pop("opening", OPENING), amounts=overrides.pop("amounts", AMOUNTS), **overrides)


def _with_closing(printed: str) -> str:
    return PRINTED_STATEMENT.replace("Closing Balance 4837.55\nClosing Balance 4837.55\n", printed + "\n")


def test_AC_extraction_closing_balance_source_1_computed_closing_is_flagged():
    neg_amounts = [-a if a < Decimal("100") else a for a in AMOUNTS]
    assert (
        _verdict(PRINTED_STATEMENT, "4837.50"),
        _verdict(PRINTED_STATEMENT, "4837.55"),
        _verdict(PRINTED_STATEMENT, "837.55"),
        _verdict(PRINTED_STATEMENT, "4837.55", amounts=neg_amounts),
        _verdict("Opening Balance 2000.00\nSalary 3000.00\nClosing Balance 4837.55\n", "4837.50"),
        _verdict(PRINTED_STATEMENT.replace("Opening Balance 2000.00\n", ""), "4837.50"),
        _verdict(PRINTED_STATEMENT, None),
        _verdict(PRINTED_STATEMENT, "4837.50", amounts=[]),
        _verdict(PRINTED_STATEMENT.replace("55.00", "fifty-five"), "4837.50"),
        _verdict(PRINTED_STATEMENT.replace("55.00", "fifty-five").replace("23.60", "twenty-three"), "4837.50"),
        _verdict(_with_closing("Closing Balance 4\u2009837.55"), "837.55"),
    ) == (
        SourceBalanceVerdict.CLOSING_NOT_IN_TEXT, SourceBalanceVerdict.VERIFIED, SourceBalanceVerdict.CLOSING_NOT_IN_TEXT,
        SourceBalanceVerdict.VERIFIED, SourceBalanceVerdict.TEXT_UNUSABLE, SourceBalanceVerdict.TEXT_UNUSABLE,
        SourceBalanceVerdict.TEXT_UNUSABLE, SourceBalanceVerdict.TEXT_UNUSABLE, SourceBalanceVerdict.CLOSING_NOT_IN_TEXT,
        SourceBalanceVerdict.TEXT_UNUSABLE, SourceBalanceVerdict.VERIFIED,
    )
    assert {Decimal("1234.50"), Decimal("99.5"), Decimal("7"), Decimal("1234.56"), Decimal("12345.60")} <= text_money_values("a 1,234.50 b 99.5 c 7 d 1.234,56 e 12 345.60")


@pytest.mark.parametrize(
    ("printed", "closing", "expected"),
    [
        ("Closing Balance 4,837.55", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 4.837,55", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 4 837.55", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 4\u202f837,55", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance SGD4837.55", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance (4,837.55)", "-4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 4837.55-", "-4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 4837.55 CR", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 1,03,450.00", "103450.00", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 12,34,567.89", "1234567.89", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 4\u2009837.55", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 4’837.55", "4837.55", SourceBalanceVerdict.VERIFIED),
        ("Closing Balance 1,03,450.00", "103450.01", SourceBalanceVerdict.CLOSING_NOT_IN_TEXT),
        ("Closing Balance 4\u2009837.55", "4837.50", SourceBalanceVerdict.CLOSING_NOT_IN_TEXT),
        ("Closing Balance 4’837.55", "837.55", SourceBalanceVerdict.CLOSING_NOT_IN_TEXT),
        ("Closing Balance NIL", "0.00", SourceBalanceVerdict.TEXT_UNUSABLE),
        ("Closing Balance -", "0.00", SourceBalanceVerdict.TEXT_UNUSABLE),
        ("Closing Balance 0.00", "0.00", SourceBalanceVerdict.TEXT_UNUSABLE),
    ],
)
def test_AC_extraction_closing_balance_source_layouts(printed, closing, expected):
    assert _verdict(_with_closing(printed), closing) is expected


@pytest.mark.parametrize("text", [None, "", "   \n", "Welcome to your monthly statement. Thank you."])
def test_AC_extraction_closing_balance_source_1_missing_text_layer_is_unusable(text):
    assert _verdict(text, "4837.50") is SourceBalanceVerdict.TEXT_UNUSABLE


async def test_auto_approve_balance_mismatch_clears_balance_validated_flag(db, test_user):
    custody_account = await create_statement_account(db, test_user.id, "DBS Validation Test Account")
    statement = build_statement(test_user.id, "hash_balance_mismatch_clears_flag", 90)
    statement.status, statement.balance_validated, statement.account_id, statement.opening_balance, statement.closing_balance, statement.currency = (
        BankStatementStatus.APPROVED, True, custody_account.id, Decimal("2000.00"), Decimal("4837.55"), "SGD"
    )
    db.add(statement)
    await db.flush()
    await add_txn(db, statement, txn_date=date(2025, 1, 10), description="Payment received", amount=Decimal("2837.50"), direction="IN")
    await db.commit()
    created = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id, dependencies=posting_dependencies())
    refreshed = await db.get(StatementSummary, statement.id)
    assert refreshed is not None and (created, refreshed.status, refreshed.stage1_status, refreshed.balance_validated, refreshed.validation_error) == (
        0, BankStatementStatus.PARSED, Stage1Status.PENDING_REVIEW, False, "Balance mismatch: delta=0.05 exceeds tolerance 0.001"
    )
