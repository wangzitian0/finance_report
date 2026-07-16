"""Pure journal-balance validators — the ledger's posting invariants as code.

These operate on already-loaded ``JournalLine`` / ``JournalEntry`` objects with
**no I/O**, so they live in ``base/`` (the pure, downward-only core). The async,
DB-touching ownership check lives in the ``extension/`` adapter.

``validate_journal_balance`` / ``validate_fx_rates`` /
``validate_journal_posting_invariants`` are the three pure invariants:

* balance — debit base-currency total == credit base-currency total (tolerance
  ``0.01``), measured after FX conversion, not on raw nominal amounts;
* fx — a non-base-currency line must carry an ``fx_rate``;
* posting — the full set of invariants an entry must satisfy before it can become
  ``posted`` (balance + fx + account ownership/system/active checks).

``AccountingError`` / ``ValidationError`` are the ledger's validation error types
(``ValidationError`` is the one external callers ``except`` on).
"""

from __future__ import annotations

from decimal import Decimal

import src.config
from src.audit import JournalEntrySourceType
from src.audit.money import Currency, Money
from src.ledger.orm.journal import Direction, JournalEntry, JournalLine


class AccountingError(Exception):
    """Base exception for accounting errors."""


class ValidationError(AccountingError):
    """Validation error for accounting operations."""


def _effective_base_currency(base_currency: str | None) -> str:
    """Normalize explicit base currency, retaining legacy caller compatibility."""
    return Currency.of(base_currency or src.config.settings.base_currency).code


def validate_fx_rates(lines: list[JournalLine], *, base_currency: str | None = None) -> None:
    """
    Validate FX rate requirements for multi-currency lines.

    Requires fx_rate when line currency differs from base currency.
    """
    base_currency = _effective_base_currency(base_currency)
    for line in lines:
        line_currency = (line.currency or base_currency).upper()
        if line_currency != base_currency and line.fx_rate is None:
            raise ValidationError(f"fx_rate required for currency {line_currency} (base {base_currency})")


def _line_base_amount(line: JournalLine, *, base_currency: str | None = None) -> Money:
    """Return the line value converted to the caller's base currency, as Money."""
    base = Currency.of(_effective_base_currency(base_currency))
    # Resolve an omitted in-memory currency against the explicit validation
    # context, not JournalLine.money's legacy process-config fallback.
    line_money = Money(line.amount, line.currency or base.code)
    if line_money.currency == base:
        return line_money
    if line.fx_rate is None:
        raise ValidationError(f"fx_rate required for currency {line_money.currency.code} (base {base.code})")
    return Money(line.amount * line.fx_rate, base.code)


def validate_journal_balance(lines: list[JournalLine], *, base_currency: str | None = None) -> None:
    """
    Validate that journal entry lines are balanced (debit = credit).

    Args:
        lines: List of journal lines to validate

    Raises:
        ValidationError: If debits and credits don't balance
    """
    if len(lines) < 2:
        raise ValidationError("Journal entry must have at least 2 lines")

    # All per-line amounts are in base currency here, so Money.sum is single-currency;
    # a cross-currency mix would raise instead of silently summing.
    normalized_base = _effective_base_currency(base_currency)
    total_debit = Money.sum(
        (_line_base_amount(line, base_currency=normalized_base) for line in lines if line.direction == Direction.DEBIT),
        currency=normalized_base,
    )
    total_credit = Money.sum(
        (
            _line_base_amount(line, base_currency=normalized_base)
            for line in lines
            if line.direction == Direction.CREDIT
        ),
        currency=normalized_base,
    )

    if abs((total_debit - total_credit).amount) > Decimal("0.01"):
        raise ValidationError(f"Journal entry not balanced: debit={total_debit.amount}, credit={total_credit.amount}")


def validate_journal_posting_invariants(entry: JournalEntry, *, base_currency: str | None = None) -> None:
    """Validate the invariants required before an entry can become posted."""
    validate_journal_balance(entry.lines, base_currency=base_currency)
    validate_fx_rates(entry.lines, base_currency=base_currency)

    for line in entry.lines:
        account = line.account
        if account is None:
            raise ValidationError(f"Account {line.account_id} not found")
        if account.user_id != entry.user_id:
            raise ValidationError("Account does not belong to user")
        if account.is_system and entry.source_type != JournalEntrySourceType.SYSTEM:
            raise ValidationError(
                "System accounts can only be used by system-generated entries. "
                "Manual entries cannot debit/credit system accounts."
            )
        if not account.is_active:
            raise ValidationError(f"Account {account.name} is not active")
