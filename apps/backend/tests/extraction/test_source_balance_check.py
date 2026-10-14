"""AC-extraction.closing-balance-source.1: check an extracted closing balance against the document text (#2394).

On staging, the model sometimes stored the closing balance that it computed from the rows
(4837.50) and not the closing balance that the PDF printed (4837.55). The balance chain then
tied out and the statement was approved. The text layer of a PDF holds the printed numbers.
The check below fails when the stored closing balance is not one of those numbers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.extraction import BankStatementStatus, Stage1Status
from src.extraction.base.source_balance_check import (
    SourceBalanceVerdict,
    check_closing_balance_against_text,
    text_money_values,
)
from src.extraction.extension.statement_posting import (
    try_auto_approve_high_confidence_statement,
)
from src.extraction.orm.statement_summary import StatementSummary
from tests.api._statement_router_fixtures import (
    add_txn,
    build_statement,
    create_statement_account,
)
from tests.statement_ingestion import posting_dependencies

OPENING = Decimal("2000.00")
AMOUNTS = [Decimal("3000.00"), Decimal("1.50"), Decimal("85.40"), Decimal("23.60"), Decimal("55.00")]
PRINTED_STATEMENT = """Stage One Routing Bank
Account 5551-234-7702
Statement period 2026-05-01 to 2026-05-31
Opening Balance 2000.00
2026-05-02 Salary Acme Pte Ltd 3000.00
2026-05-03 Interest 1.50
2026-05-10 Grocery Market -85.40
2026-05-12 Phone Plan -23.60
2026-05-20 Coffee House -55.00
Total Credits 3001.50
Total Debits 164.00
Closing Balance 4837.55
Closing Balance 4837.55
"""


def _verdict(text: str | None, closing: str | None, **overrides) -> SourceBalanceVerdict:
    arguments = {"opening": OPENING, "amounts": AMOUNTS}
    arguments.update(overrides)
    return check_closing_balance_against_text(text, closing=None if closing is None else Decimal(closing), **arguments)


def test_AC_extraction_closing_balance_source_1_computed_closing_is_flagged():
    """The #2394 shape: the text prints 4837.55 and the model stored the computed 4837.50."""
    assert _verdict(PRINTED_STATEMENT, "4837.50") is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT


def test_AC_extraction_closing_balance_source_1_printed_closing_is_verified():
    assert _verdict(PRINTED_STATEMENT, "4837.55") is SourceBalanceVerdict.VERIFIED


def test_AC_extraction_closing_balance_source_1_matches_whole_numbers_only():
    """837.55 is a suffix of 4837.55. A substring test would verify it. A token test must not."""
    assert _verdict(PRINTED_STATEMENT, "837.55") is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT


@pytest.mark.parametrize(
    ("printed", "closing"),
    [
        ("Closing Balance 4,837.55", "4837.55"),
        ("Closing Balance 4.837,55", "4837.55"),
        ("Closing Balance 4 837.55", "4837.55"),
        ("Closing Balance 4 837,55", "4837.55"),
        ("Closing Balance SGD4837.55", "4837.55"),
        ("Closing Balance (4,837.55)", "-4837.55"),
        ("Closing Balance 4837.55-", "-4837.55"),
        ("Closing Balance 4837.55 CR", "4837.55"),
    ],
)
def test_AC_extraction_closing_balance_source_1_reads_common_number_layouts(printed, closing):
    text = PRINTED_STATEMENT.replace("Closing Balance 4837.55\nClosing Balance 4837.55\n", printed + "\n")
    assert "4837.55" not in text.replace(printed, "")
    assert _verdict(text, closing) is SourceBalanceVerdict.VERIFIED


def test_AC_extraction_closing_balance_source_1_amounts_match_by_absolute_value():
    negative_amounts = [-amount if amount < Decimal("100") else amount for amount in AMOUNTS]
    assert _verdict(PRINTED_STATEMENT, "4837.55", amounts=negative_amounts) is SourceBalanceVerdict.VERIFIED


@pytest.mark.parametrize("text", [None, "", "   \n", "Welcome to your monthly statement. Thank you."])
def test_AC_extraction_closing_balance_source_1_missing_text_layer_is_unusable(text):
    assert _verdict(text, "4837.50") is SourceBalanceVerdict.TEXT_UNUSABLE


def test_AC_extraction_closing_balance_source_1_text_without_the_amounts_is_unusable():
    """A text layer that lacks the row amounts says nothing about the closing balance."""
    text = "Opening Balance 2000.00\nSalary 3000.00\nClosing Balance 4837.55\n"
    assert _verdict(text, "4837.50") is SourceBalanceVerdict.TEXT_UNUSABLE


def test_AC_extraction_closing_balance_source_1_text_without_the_opening_balance_is_unusable():
    text = PRINTED_STATEMENT.replace("Opening Balance 2000.00\n", "")
    assert _verdict(text, "4837.50") is SourceBalanceVerdict.TEXT_UNUSABLE


def test_AC_extraction_closing_balance_source_1_no_closing_balance_is_unusable():
    assert _verdict(PRINTED_STATEMENT, None) is SourceBalanceVerdict.TEXT_UNUSABLE


def test_AC_extraction_closing_balance_source_1_no_amounts_is_unusable():
    assert _verdict(PRINTED_STATEMENT, "4837.50", amounts=[]) is SourceBalanceVerdict.TEXT_UNUSABLE


def test_AC_extraction_closing_balance_source_1_one_unread_amount_in_five_keeps_the_text_usable():
    """The text layer must hold at least four of five row amounts. Four of five is enough."""
    text = PRINTED_STATEMENT.replace("55.00", "fifty-five")
    assert _verdict(text, "4837.50") is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT


def test_AC_extraction_closing_balance_source_1_two_unread_amounts_in_five_make_the_text_unusable():
    text = PRINTED_STATEMENT.replace("55.00", "fifty-five").replace("23.60", "twenty-three")
    assert _verdict(text, "4837.50") is SourceBalanceVerdict.TEXT_UNUSABLE


def test_AC_extraction_closing_balance_source_1_money_values_include_grouped_and_plain_numbers():
    values = text_money_values("a 1,234.50 b 99.5 c 7 d 1.234,56 e 12 345.60")
    assert {Decimal("1234.50"), Decimal("99.5"), Decimal("7"), Decimal("1234.56"), Decimal("12345.60")} <= values


def _statement_text_with_closing_line(printed: str) -> str:
    return PRINTED_STATEMENT.replace("Closing Balance 4837.55\nClosing Balance 4837.55\n", printed + "\n")


@pytest.mark.parametrize(
    ("printed", "closing"),
    [
        ("Closing Balance 1,03,450.00", "103450.00"),  # Indian grouping: 3 digits, then pairs
        ("Closing Balance 12,34,567.89", "1234567.89"),
        ("Closing Balance 4\u2009837.55", "4837.55"),  # thin space as the group separator
        ("Closing Balance 4\u2019837.55", "4837.55"),  # typographic apostrophe, as in Swiss layouts
    ],
)
def test_AC_extraction_closing_balance_source_3_reads_more_group_separators(printed, closing):
    """AC-extraction.closing-balance-source.3: a printed closing balance in these layouts is not flagged."""
    text = _statement_text_with_closing_line(printed)
    assert _verdict(text, closing) is SourceBalanceVerdict.VERIFIED


@pytest.mark.parametrize(
    ("printed", "closing"),
    [
        ("Closing Balance 1,03,450.00", "103450.01"),
        ("Closing Balance 4\u2009837.55", "4837.50"),
        ("Closing Balance 4\u2019837.55", "837.55"),
    ],
)
def test_AC_extraction_closing_balance_source_3_new_layouts_still_flag_a_wrong_closing_balance(printed, closing):
    """AC-extraction.closing-balance-source.3: a wider reader must not verify a number that the text lacks."""
    text = _statement_text_with_closing_line(printed)
    assert _verdict(text, closing) is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT


@pytest.mark.parametrize("printed", ["Closing Balance NIL", "Closing Balance -", "Closing Balance 0.00"])
def test_AC_extraction_closing_balance_source_3_a_zero_closing_balance_cannot_be_checked(printed):
    """AC-extraction.closing-balance-source.3: a zero balance prints as a word or a dash. The text says nothing."""
    text = _statement_text_with_closing_line(printed)
    assert _verdict(text, "0.00") is SourceBalanceVerdict.TEXT_UNUSABLE


def test_AC_extraction_closing_balance_source_3_a_part_of_a_spaced_number_can_still_verify():
    """AC-extraction.closing-balance-source.3: known limit of the superset design, kept on purpose.

    A run such as "4 837.55" yields 4837.55 and also its parts, because "85.40 4837.55" holds two numbers.
    The check therefore fails open for a closing balance that equals a part of a spaced number. The other
    direction, a false flag on a good statement, costs more automation than this limit costs safety.
    """
    text = _statement_text_with_closing_line("Closing Balance 4\u2009837.55")
    assert _verdict(text, "837.55") is SourceBalanceVerdict.VERIFIED


async def test_auto_approve_balance_mismatch_clears_balance_validated_flag(db, test_user):
    """AC-extraction.stage1-routing.1: auto-approve clears balance_validated flag when closing balance mismatches (#2397)."""
    custody_account = await create_statement_account(db, test_user.id, "DBS Validation Test Account")
    statement = build_statement(test_user.id, "hash_balance_mismatch_clears_flag", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.balance_validated = True
    statement.account_id = custody_account.id
    statement.opening_balance = Decimal("2000.00")
    statement.closing_balance = Decimal("4837.55")
    statement.currency = "SGD"
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 10),
        description="Payment received",
        amount=Decimal("2837.50"),
        direction="IN",
    )
    await db.commit()

    created_count = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )

    assert created_count == 0
    refreshed = await db.get(StatementSummary, statement.id)
    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.PARSED
    assert refreshed.stage1_status == Stage1Status.PENDING_REVIEW
    assert refreshed.balance_validated is False
    assert refreshed.validation_error == "Balance mismatch: delta=0.05 exceeds tolerance 0.001"
