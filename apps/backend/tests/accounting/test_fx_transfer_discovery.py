"""AC4.14.11 / AC4.14.12 — ledger auto-discovery of cross-currency transfer legs.

#1123 AC2 (live consumption). These tests exercise
``src.reconciliation.extension.fx_transfer_discovery.discover_fx_conversions`` against a seeded DB
session: a real cross-currency internal transfer booked only as RAW asset-account
journal lines (no pre-recorded ``fx_conversions`` row) must be auto-discovered and
materialised as an in-memory :class:`FxConversion` linking both legs — but only
when the match is **unambiguous**.
"""

from datetime import date
from decimal import Decimal

from common.testing.ac_proof import ac_proof
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.reconciliation.extension.fx_transfer_discovery import discover_fx_conversions

_RATE_SGD_PER_USD = Decimal("1.360000")
_TXN_DATE = date(2025, 6, 15)
_AS_OF = date(2025, 6, 30)
_START = date(2025, 6, 1)


async def _account(db, user_id, *, name, currency, account_type=AccountType.ASSET) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _post_entry(db, user_id, *, debit_account, credit_account, amount, currency) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=_TXN_DATE,
        memo="seed",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    line_fx_rate = None if currency.upper() == "SGD" else _RATE_SGD_PER_USD
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit_account.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency=currency,
                fx_rate=line_fx_rate,
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit_account.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency=currency,
                fx_rate=line_fx_rate,
            ),
        ]
    )
    await db.flush()
    return entry


async def _fixed_rate_resolver(base: str, quote: str, on_date: date) -> Decimal | None:
    """Mirror ``get_exchange_rate(base, quote)`` = units of quote per unit of base.

    1 USD = 1.36 SGD, so resolver("USD", "SGD") = 1.36 and resolver("SGD", "USD")
    = 1/1.36. Discovery calls this with ``base=in_currency, quote=out_currency``.
    """
    base, quote = base.upper(), quote.upper()
    if base == "USD" and quote == "SGD":
        return _RATE_SGD_PER_USD
    if base == "SGD" and quote == "USD":
        return Decimal("1") / _RATE_SGD_PER_USD
    if base == quote:
        return Decimal("1")
    return None


@ac_proof(
    "fx-discovery-pairs-unambiguous-legs",
    ac_ids=["AC4.14.11"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
async def test_AC2_discover_pairs_unambiguous_cross_currency_legs_from_ledger(db: AsyncSession, test_user, ac_evidence):
    """AC4.14.11: an out-leg in SGD + an in-leg in USD on own asset accounts pair.

    1360 SGD leaves the SGD asset (CREDIT) and 1000 USD arrives in the USD asset
    (DEBIT) on the same day; implied rate 1360/1000 = 1.36 == market 1.36, so the
    legs are auto-discovered as one conversion with no recorded fx_conversions row.
    """
    sgd_bank = await _account(db, test_user.id, name="SGD Bank", currency="SGD")
    usd_bank = await _account(db, test_user.id, name="USD Bank", currency="USD")
    # Counterpart (mis-booked) income/expense accounts so the entries balance.
    transfer_out = await _account(
        db, test_user.id, name="Transfer Out", currency="SGD", account_type=AccountType.EXPENSE
    )
    transfer_in = await _account(db, test_user.id, name="Transfer In", currency="USD", account_type=AccountType.INCOME)

    out_entry = await _post_entry(
        db,
        test_user.id,
        debit_account=transfer_out,
        credit_account=sgd_bank,
        amount=Decimal("1360.00"),
        currency="SGD",
    )
    in_entry = await _post_entry(
        db,
        test_user.id,
        debit_account=usd_bank,
        credit_account=transfer_in,
        amount=Decimal("1000.00"),
        currency="USD",
    )
    await db.commit()

    discovered = await discover_fx_conversions(db, test_user.id, _AS_OF, _fixed_rate_resolver, start_date=_START)

    assert len(discovered) == 1, "exactly one unambiguous conversion expected"
    conv = discovered[0].conversion
    assert conv.from_account_id == sgd_bank.id
    assert conv.to_account_id == usd_bank.id
    assert conv.amount_from == Decimal("1360.00")
    assert conv.currency_from == "SGD"
    assert conv.amount_to == Decimal("1000.00")
    assert conv.currency_to == "USD"
    assert conv.from_journal_entry_id == out_entry.id
    assert conv.to_journal_entry_id == in_entry.id
    assert discovered[0].pair.implied_rate == Decimal("1.36")

    ac_evidence(
        ac_id="AC4.14.11",
        score=1.0,
        metric="cross_currency_transfer_legs_discovered_from_raw_ledger",
        provenance="deterministic",
        comment="Auto-discovered an unambiguous OUT/IN cross-currency pair from raw asset lines (#1123 AC2).",
    )


@ac_proof(
    "fx-discovery-skips-ambiguous-legs",
    ac_ids=["AC4.14.12"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
async def test_AC2_discover_skips_ambiguous_candidate_legs(db: AsyncSession, test_user, ac_evidence):
    """AC4.14.12: when one OUT leg could pair with two identical IN legs, none pair.

    Two distinct USD asset accounts each receive an identical 1000 USD on the same
    day, and a single 1360 SGD leg leaves. The OUT leg matches BOTH in-legs, so the
    conservative discovery refuses to guess and returns nothing.
    """
    sgd_bank = await _account(db, test_user.id, name="SGD Bank", currency="SGD")
    usd_bank_a = await _account(db, test_user.id, name="USD Bank A", currency="USD")
    usd_bank_b = await _account(db, test_user.id, name="USD Bank B", currency="USD")
    transfer_out = await _account(
        db, test_user.id, name="Transfer Out", currency="SGD", account_type=AccountType.EXPENSE
    )
    transfer_in = await _account(db, test_user.id, name="Transfer In", currency="USD", account_type=AccountType.INCOME)

    await _post_entry(
        db,
        test_user.id,
        debit_account=transfer_out,
        credit_account=sgd_bank,
        amount=Decimal("1360.00"),
        currency="SGD",
    )
    await _post_entry(
        db,
        test_user.id,
        debit_account=usd_bank_a,
        credit_account=transfer_in,
        amount=Decimal("1000.00"),
        currency="USD",
    )
    await _post_entry(
        db,
        test_user.id,
        debit_account=usd_bank_b,
        credit_account=transfer_in,
        amount=Decimal("1000.00"),
        currency="USD",
    )
    await db.commit()

    discovered = await discover_fx_conversions(db, test_user.id, _AS_OF, _fixed_rate_resolver, start_date=_START)

    assert discovered == [], "ambiguous candidate legs must not be paired"

    ac_evidence(
        ac_id="AC4.14.12",
        score=1.0,
        metric="ambiguous_transfer_legs_not_paired",
        provenance="deterministic",
        comment="Conservative discovery refuses to net an OUT leg matching multiple IN legs (#1123 AC2).",
    )
