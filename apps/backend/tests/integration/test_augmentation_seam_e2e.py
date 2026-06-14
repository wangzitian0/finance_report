"""Augmentation-layer seam → report integrity (EPIC-008 AC8.16, #992 / #990).

The strong reporting E2Es (`test_reporting_e2e`, `test_full_year_statement_to_report_e2e`)
pin the *core accounting arithmetic*. They do **not** walk the newer augmentation
layer — confidence-tagged extracted/reconciled inputs and append-only manual-valuation
versioning — which is exactly where the recent audit bugs lived (#968 superseded
valuation leaked into holdings; a missing `.distinct()` inflated provenance).

This test stands up the *combined* state production actually has — a low-confidence
extracted ledger input AND a corrected (superseded) valuation present at once — and
asserts the report is right on every axis simultaneously:

1. the ledger numbers are correct and the equation holds,
2. the low-confidence input is **not laundered**: its line carries the worst tier (Axiom B),
3. the **superseded** valuation is excluded from net-worth components (the #968 class),
4. the manual valuation does **not** silently contaminate the ledger balance sheet.

Existing tests cover (2) and (3) each in isolation; none exercises them composed,
which is where seam bugs hide.
"""

from datetime import date
from decimal import Decimal

from src.models import Account, AccountType, JournalEntrySourceType
from src.models.layer3 import ManualValuationComponentType
from src.services.accounting import create_journal_entry, post_journal_entry
from src.services.assets import AssetService
from src.services.reporting import generate_balance_sheet


async def _account(db, user_id, *, name, account_type, currency="SGD"):
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def _posted(db, user_id, *, entry_date, memo, lines, source_type):
    entry = await create_journal_entry(
        db=db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines,
        source_type=source_type,
    )
    await post_journal_entry(db, entry.id, user_id)


async def test_AC8_16_1_augmentation_seam_excludes_superseded_and_surfaces_confidence(db, test_user):
    """AC8.16.1: low-confidence extracted inputs and a corrected valuation reach the
    report without leaking a superseded row or laundering a low-confidence input."""
    user_id = test_user.id
    as_of = date(2026, 5, 31)
    service = AssetService()

    cash = await _account(db, user_id, name="Cash", account_type=AccountType.ASSET)
    equity = await _account(db, user_id, name="Opening Equity", account_type=AccountType.EQUITY)
    salary = await _account(db, user_id, name="Salary", account_type=AccountType.INCOME)

    # Reconcile/extract path: a TRUSTED manual entry and a LOW-confidence auto_parsed
    # (simulated extraction→reconcile) entry both land on Cash → worst input tier is LOW.
    await _posted(
        db,
        user_id,
        entry_date=date(2026, 5, 1),
        memo="Opening capital",
        lines=[
            {"account_id": cash.id, "direction": "DEBIT", "amount": Decimal("1000.00"), "currency": "SGD"},
            {"account_id": equity.id, "direction": "CREDIT", "amount": Decimal("1000.00"), "currency": "SGD"},
        ],
        source_type=JournalEntrySourceType.MANUAL,
    )
    await _posted(
        db,
        user_id,
        entry_date=date(2026, 5, 10),
        memo="Auto-parsed deposit",
        lines=[
            {"account_id": cash.id, "direction": "DEBIT", "amount": Decimal("500.00"), "currency": "SGD"},
            {"account_id": salary.id, "direction": "CREDIT", "amount": Decimal("500.00"), "currency": "SGD"},
        ],
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )

    # Valuation-correction path: create a property valuation, then correct it (appends a
    # new version that supersedes the first — Axiom A append-only).
    vkey = dict(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=as_of,
        currency="SGD",
        source="manual appraisal",
    )
    await service.create_valuation_snapshot(db, user_id=user_id, value=Decimal("1000000.00"), **vkey)
    await service.create_valuation_snapshot(db, user_id=user_id, value=Decimal("1100000.00"), **vkey)  # supersedes
    await db.commit()

    # --- Report seam assertions ---
    balance_sheet = await generate_balance_sheet(db, user_id, as_of_date=as_of, currency="SGD")
    asset_lines = {line["name"]: line for line in balance_sheet["assets"]}

    # (1) ledger numbers correct + equation holds (assets 1500 = equity 1000 + net income 500)
    assert balance_sheet["total_assets"] == Decimal("1500.00")
    assert balance_sheet["equation_delta"] == Decimal("0.00")
    assert balance_sheet["is_balanced"] is True

    # (2) the low-confidence extracted input is not laundered to trusted
    assert asset_lines["Cash"]["confidence_tier"] == "LOW"

    # (4) the manual property valuation must not silently inflate the ledger balance sheet
    assert "Cash" in asset_lines and Decimal(str(asset_lines["Cash"]["amount"])) == Decimal("1500.00")

    # (3) the superseded valuation is excluded from net-worth components (#968 class)
    components = await service.get_latest_valuation_components(db, user_id, as_of_date=as_of)
    assert components.total_assets == Decimal("1100000.00")
