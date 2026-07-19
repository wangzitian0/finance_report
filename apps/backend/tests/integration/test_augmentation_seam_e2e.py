"""Augmentation-layer seam → report integrity (EPIC-008 AC8.16, #992 / #990).

The strong reporting E2Es (`test_reporting_e2e`, `test_full_year_statement_to_report_e2e`)
pin the *core accounting arithmetic*. They do **not** walk the newer augmentation
layer — confidence-tagged extracted/reconciled inputs and append-only manual-valuation
versioning — which is exactly where the recent audit bugs lived (#968 superseded
valuation leaked into holdings; a missing `.distinct()` inflated provenance).

This test stands up the *combined* state production actually has — a source-labelled
extracted ledger input AND a corrected (superseded) valuation present at once — and
asserts the report is right on every axis simultaneously:

1. the ledger numbers are correct and the equation still holds with the valuation folded in,
2. source confidence is not misrepresented as report assurance: the statement does not
   export a synthetic confidence tier,
3. the **corrected** valuation reaches the balance sheet while the **superseded** one is
   excluded (the total carries 1,100,000, not 2,100,000) — the #968 class, proven at the
   balance-sheet level and again in net-worth components,
4. the ledger Cash line itself is unchanged by the valuation (it stays 1,500).

Existing tests cover the authority fold and (3) in isolation; none exercises them composed,
which is where seam bugs hide.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from common.testing.ac_proof import ac_proof
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction.orm.layer3 import ManualValuationComponentType
from src.identity import User
from src.ledger import Account, AccountType, post_journal_entry
from src.pricing import ValuationService
from src.reporting import generate_balance_sheet
from tests.ledger._ledger_helpers import create_anchored_test_journal_entry as create_journal_entry


async def _account(
    db: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    account_type: AccountType,
    currency: str = "SGD",
) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def _posted(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date,
    memo: str,
    lines: list[dict[str, object]],
    source_type: JournalEntrySourceType,
) -> None:
    entry = await create_journal_entry(
        db=db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines,
        source_type=source_type,
    )
    await post_journal_entry(db, entry.id, user_id)


@ac_proof(
    "report-input-selection-excludes-superseded-pr",
    ac_ids=["AC-reporting.augmentation.1"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record", "bank_statement"],
    issue="#1103 / #990 / #992",
)
async def test_AC8_16_1_augmentation_seam_excludes_superseded_without_source_assurance(
    db: AsyncSession, test_user: User, ac_evidence
) -> None:
    """AC-reporting.augmentation.1: source-labelled inputs and a corrected valuation reach the
    report without leaking a superseded row or presenting source metadata as assurance."""
    user_id = test_user.id
    as_of = date(2026, 5, 31)
    service = ValuationService()

    cash = await _account(db, user_id, name="Cash", account_type=AccountType.ASSET)
    equity = await _account(db, user_id, name="Opening Equity", account_type=AccountType.EQUITY)
    salary = await _account(db, user_id, name="Salary", account_type=AccountType.INCOME)

    # Reconcile/extract path: a manual entry and an auto-parsed entry both land on Cash.
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

    # (1) the ledger AND the corrected manual valuation both reach the report, and the
    # SUPERSEDED valuation is excluded: total carries ledger cash 1500 + the corrected
    # property 1,100,000 = 1,101,500. A superseded leak (the #968 class) would make this
    # 2,101,500; a missing valuation would make it 1,500.
    assert balance_sheet["total_assets"] == Decimal("1101500.00")
    # the equation still holds: the valuation is offset by the net-worth adjustment.
    assert balance_sheet["equation_delta"] == Decimal("0.00")
    assert balance_sheet["is_balanced"] is True

    # (2) source confidence is not converted into report assurance. Package trust is
    # represented by TraceRecord decisions, not a per-line confidence display.
    assert "confidence_tier" not in asset_lines["Cash"]
    assert Decimal(str(asset_lines["Cash"]["amount"])) == Decimal("1500.00")

    # (3) the superseded valuation is also excluded from net-worth components (#968 class)
    components = await service.get_latest_valuation_components(db, user_id, as_of_date=as_of)
    assert components.total_assets == Decimal("1100000.00")

    # Behavioral evidence: the corrected-only net-worth total (1.1M, not 2.1M) is the
    # deterministic proof that the seam excludes the superseded row.
    ac_evidence(
        ac_id="AC-reporting.augmentation.1",
        score=1.0,
        metric="superseded_excluded_corrected_total_match",
        comment="net-worth components == 1,100,000 (corrected only); a superseded leak would be 2,100,000",
        provenance="deterministic",
    )
