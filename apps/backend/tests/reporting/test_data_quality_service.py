from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, StatementSummary
from src.extraction.orm.layer1 import DocumentStatus, DocumentType, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.identity import User
from src.ledger import AccountType
from src.reconciliation.data.stats import ReconciliationStats
from src.reporting import QualityGrade
from src.reporting.base.diagnostics import EquationDiagnosticCategory, EquationDiagnosticResult
from src.reporting.extension.data_quality_service import _shift_months, compute_personal_data_quality
from src.request_context import RequestContext
from tests.reporting._report_fixtures import post_pair, seed_accounts


def _stmt(
    user_id,
    account_id,
    file_hash: str,
    p_start: date,
    p_end: date,
    ob: str,
    cb: str,
    *,
    status=BankStatementStatus.APPROVED,
    institution="DBS",
    last4=None,
    doc_id=None,
) -> StatementSummary:
    return StatementSummary(
        id=uuid4(),
        user_id=user_id,
        account_id=account_id,
        uploaded_document_id=doc_id,
        file_hash=file_hash,
        institution=institution,
        account_last4=last4,
        currency="SGD",
        period_start=p_start,
        period_end=p_end,
        opening_balance=Decimal(ob),
        closing_balance=Decimal(cb),
        status=status,
    )


def test_shift_months_calculation() -> None:
    assert _shift_months(2026, 1, -1) == (2025, 12)
    assert _shift_months(2026, 12, 1) == (2027, 1)


async def test_compute_personal_data_quality_clean_and_defaults_to_base_currency(
    db: AsyncSession, test_user: User
) -> None:
    from src.config_app import set_base_currency
    from src.routers.reports import get_data_quality_health

    empty_res = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 1), currency="SGD")
    assert empty_res.score < 80
    assert empty_res.grade == QualityGrade.C_ATTENTION_NEEDED
    assert empty_res.temporal_continuity_invariant.is_healthy is False
    assert empty_res.lineage_anchors_invariant.is_healthy is False
    assert any(a.action_type == "UPLOAD_STATEMENT" and a.action_url == "/upload" for a in empty_res.action_items)

    [acc] = await seed_accounts(db, test_user.id, ("DBS Checking", AccountType.ASSET))
    doc = UploadedDocument(
        user_id=test_user.id,
        file_path="statements/dbs_2026_09.pdf",
        original_filename="dbs_2026_09.pdf",
        file_hash="clean_2026_09",
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.COMPLETED,
    )
    db.add(doc)
    await db.flush()
    db.add(
        _stmt(test_user.id, acc.id, "clean_2026_09", date(2026, 9, 1), date(2026, 9, 30), "1000", "1200", doc_id=doc.id)
    )
    await db.flush()

    res = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 1), currency="SGD")
    assert (res.score, res.grade, res.currency, res.as_of_date, len(res.timeline), res.action_items) == (
        100,
        QualityGrade.A_AUDIT_READY,
        "SGD",
        date(2026, 10, 1),
        12,
        [],
    )
    assert all(
        inv.is_healthy
        for inv in (
            res.equation_invariant,
            res.temporal_continuity_invariant,
            res.reconciliation_purity_invariant,
            res.lineage_anchors_invariant,
        )
    )

    with pytest.raises(ValueError, match="base_currency is required"):
        await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 1), currency=None)
    await set_base_currency(db, "USD", user_id=test_user.id)
    assert (
        await get_data_quality_health(as_of_date=date(2026, 10, 1), currency=None, ctx=RequestContext(db, test_user.id))
    ).currency == "USD"
    assert (
        await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 1), base_currency="USD")
    ).currency == "USD"


@patch("src.reporting.extension.data_quality_service.run_balance_sheet_diagnostics")
async def test_compute_personal_data_quality_imbalanced_and_multi_gap(
    mock_diag: AsyncMock, db: AsyncSession, test_user: User
) -> None:
    mock_diag.return_value = EquationDiagnosticResult(
        is_balanced=False,
        equation_delta=Decimal("150.00"),
        primary_category=EquationDiagnosticCategory.UNKNOWN_DISCREPANCY,
        confidence=0.5,
        suggested_action="Review manual journal entries.",
    )
    res = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 1), currency="SGD")
    assert (
        res.equation_invariant.is_healthy is False
        and res.equation_invariant.delta == Decimal("150.00")
        and res.score <= 60
    )
    assert res.grade in (QualityGrade.C_ATTENTION_NEEDED, QualityGrade.D_OUT_OF_BALANCE)
    p0 = [a for a in res.action_items if a.priority == "P0"]
    assert len(p0) == 1 and (p0[0].action_type, p0[0].score_boost) == ("RESOLVE_EQUATION", 40)

    mock_diag.return_value = EquationDiagnosticResult(
        is_balanced=False,
        equation_delta=Decimal("500.00"),
        primary_category=EquationDiagnosticCategory.UNKNOWN_DISCREPANCY,
        confidence=0.5,
        suggested_action="Resolve imbalance",
    )
    [acc] = await seed_accounts(db, test_user.id, ("DBS Checking", AccountType.ASSET))
    db.add_all(
        [
            _stmt(test_user.id, acc.id, "unlinked_1", date(2026, 1, 1), date(2026, 1, 31), "1000", "1200"),
            _stmt(test_user.id, acc.id, "unlinked_2", date(2026, 4, 1), date(2026, 4, 30), "1350", "1500"),
        ]
    )
    await db.flush()
    res_gap = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 4, 30), currency="SGD")
    assert (
        res_gap.score < 60
        and res_gap.grade == QualityGrade.D_OUT_OF_BALANCE
        and not res_gap.lineage_anchors_invariant.is_healthy
        and not res_gap.temporal_continuity_invariant.is_healthy
    )


async def test_compute_personal_data_quality_temporal_gap_and_pending_and_no_stmt_ledger(
    db: AsyncSession, test_user: User
) -> None:
    [acc, sal] = await seed_accounts(
        db, test_user.id, ("DBS Checking", AccountType.ASSET), ("Salary", AccountType.INCOME)
    )
    db.add_all(
        [
            _stmt(test_user.id, acc.id, "h_2026_01", date(2026, 1, 1), date(2026, 1, 31), "1000", "1200"),
            _stmt(test_user.id, acc.id, "h_2026_03", date(2026, 3, 1), date(2026, 3, 31), "1350", "1500"),
            _stmt(
                test_user.id,
                None,
                "h_pend",
                date(2026, 5, 1),
                date(2026, 5, 31),
                "500",
                "600",
                status=BankStatementStatus.PARSED,
                institution="OCBC",
            ),
        ]
    )
    await db.flush()
    res = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 3, 31), currency="SGD")
    feb = next(b for b in res.timeline if b.month == "2026-02")
    assert (
        feb.has_gap is True and feb.status == "GAP_DETECTED" and res.temporal_continuity_invariant.is_healthy is False
    )
    assert "2026-02" in next(a for a in res.action_items if a.action_type == "UPLOAD_STATEMENT").title

    res_may = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 5, 31), currency="SGD")
    assert next(b for b in res_may.timeline if b.month == "2026-05").status == "PENDING_PROCESSING"
    rev = [a for a in res_may.action_items if a.action_type == "REVIEW_STATEMENT"]
    assert len(rev) == 1 and "Review 1 Pending Statement" in rev[0].title and rev[0].action_url == "/upload"


async def test_compute_personal_data_quality_ledger_entries_without_statements_is_not_100(
    db: AsyncSession, test_user: User
) -> None:
    acc, sal = await seed_accounts(db, test_user.id, ("DBS Cash", AccountType.ASSET), ("Salary", AccountType.INCOME))
    await post_pair(db, test_user.id, date(2026, 9, 15), "Salary without statement", acc, sal, "5000.00")
    res_no_stmt = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 1), currency="SGD")
    assert res_no_stmt.score < 80 and res_no_stmt.grade != QualityGrade.A_AUDIT_READY
    assert not any(
        i.is_healthy
        for i in (
            res_no_stmt.temporal_continuity_invariant,
            res_no_stmt.reconciliation_purity_invariant,
            res_no_stmt.lineage_anchors_invariant,
        )
    )
    assert any(a.action_type == "UPLOAD_STATEMENT" for a in res_no_stmt.action_items)


@pytest.mark.parametrize(
    ("stats", "expected_score", "expected_delta", "action_id", "action_url", "title_substr"),
    [
        (
            ReconciliationStats(
                total_transactions=12,
                matched_transactions=8,
                unmatched_transactions=4,
                pending_review=0,
                auto_accepted=0,
                match_rate=0.66,
            ),
            73,
            Decimal("4"),
            "reconcile_unmatched_transactions",
            "/reconciliation?tab=unmatched",
            None,
        ),
        (
            ReconciliationStats(
                total_transactions=20,
                matched_transactions=15,
                unmatched_transactions=2,
                pending_review=3,
                auto_accepted=0,
                match_rate=0.75,
            ),
            None,
            Decimal("3"),
            None,
            None,
            "Confirm 3 Reconciliation Match",
        ),
        (
            ReconciliationStats(
                total_transactions=12,
                matched_transactions=6,
                unmatched_transactions=6,
                pending_review=0,
                auto_accepted=6,
                match_rate=0.5,
            ),
            70,
            Decimal("6"),
            None,
            None,
            None,
        ),
    ],
)
@patch("src.reporting.extension.data_quality_service.get_reconciliation_stats")
async def test_compute_personal_data_quality_reconciliation_stats(
    mock_recon: AsyncMock,
    db: AsyncSession,
    test_user: User,
    stats: ReconciliationStats,
    expected_score: int | None,
    expected_delta: Decimal,
    action_id: str | None,
    action_url: str | None,
    title_substr: str | None,
) -> None:
    mock_recon.return_value = stats
    res = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 1), currency="SGD")
    assert (res.reconciliation_purity_invariant.is_healthy, res.reconciliation_purity_invariant.delta) == (
        False,
        expected_delta,
    )
    if expected_score is not None:
        assert res.score == expected_score
    if action_id:
        assert [a.action_url for a in res.action_items if a.id == action_id] == [action_url]
    if title_substr:
        assert title_substr in next(a for a in res.action_items if a.action_type == "RECONCILE_TRANSACTIONS").title


async def test_AC_reporting_2726_3_and_2822_1_timeline_anchor_and_pending_stage1(
    db: AsyncSession, test_user: User
) -> None:
    [acc] = await seed_accounts(db, test_user.id, ("DBS Checking", AccountType.ASSET))
    db.add_all(
        [
            _stmt(test_user.id, acc.id, "h_2025_01", date(2025, 1, 1), date(2025, 1, 31), "10000", "12000"),
            _stmt(test_user.id, acc.id, "h_2025_03", date(2025, 3, 1), date(2025, 3, 31), "13500", "15000"),
        ]
    )
    await db.flush()
    res = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 27), currency="SGD")
    assert (
        len(res.timeline),
        res.timeline[0].month,
        res.timeline[-1].month,
        res.timeline[-1].status,
        res.timeline[-3].status,
    ) == (12, "2024-04", "2025-03", "HEALTHY", "HEALTHY")
    assert (
        next(b for b in res.timeline if b.month == "2025-02").status == "GAP_DETECTED"
        and "2025-02" in res.temporal_continuity_invariant.detail
    )

    doc = UploadedDocument(
        id=uuid4(),
        user_id=test_user.id,
        file_path="statements/oct.csv",
        file_hash="h_oct_2822",
        original_filename="oct.csv",
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.COMPLETED,
    )
    db.add(doc)
    await db.flush()
    db.add(
        _stmt(
            test_user.id,
            acc.id,
            "h_oct_2822",
            date(2026, 10, 1),
            date(2026, 10, 31),
            "1000",
            "1500",
            status=BankStatementStatus.PARSED,
            doc_id=doc.id,
        )
    )
    db.add(
        AtomicTransaction(
            id=uuid4(),
            user_id=test_user.id,
            txn_date=date(2026, 10, 5),
            amount=Decimal("500.00"),
            direction="IN",
            description="Pending inflow",
            currency="SGD",
            dedup_hash="dedup_oct_2822",
            source_documents=[{"doc_id": str(doc.id)}],
        )
    )
    await db.flush()
    res_pend = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 10, 31), currency="SGD")
    assert (res_pend.reconciliation_purity_invariant.is_healthy, res_pend.reconciliation_purity_invariant.delta) == (
        True,
        Decimal("0"),
    )
    act_types = [a.action_type for a in res_pend.action_items]
    assert "REVIEW_STATEMENT" in act_types and "RECONCILE_TRANSACTIONS" not in act_types


async def test_AC_reporting_2832_2_zero_change_gap_verified_and_material_gaps_ranked_by_delta(
    db: AsyncSession, test_user: User
) -> None:
    dormant, small, large = await seed_accounts(
        db,
        test_user.id,
        ("OCBC Dormant", AccountType.ASSET),
        ("UOB Cash", AccountType.ASSET),
        ("DBS Multiplier", AccountType.ASSET),
    )
    db.add_all(
        [
            _stmt(
                test_user.id,
                dormant.id,
                "d_jan",
                date(2026, 1, 1),
                date(2026, 1, 31),
                "5000",
                "5000",
                institution="OCBC",
                last4="1111",
            ),
            _stmt(
                test_user.id,
                dormant.id,
                "d_mar",
                date(2026, 3, 1),
                date(2026, 3, 31),
                "5000",
                "5000",
                institution="OCBC",
                last4="1111",
            ),
        ]
    )
    await db.flush()
    res_zero = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 3, 31), currency="SGD")
    assert (
        next(b for b in res_zero.timeline if b.month == "2026-02").status == "HEALTHY"
        and res_zero.temporal_continuity_invariant.is_healthy is True
        and not any(a.action_type == "UPLOAD_STATEMENT" for a in res_zero.action_items)
    )

    db.add_all(
        [
            _stmt(
                test_user.id,
                small.id,
                "u_jan",
                date(2026, 1, 1),
                date(2026, 1, 31),
                "2000",
                "2000",
                institution="UOB",
                last4="2222",
            ),
            _stmt(
                test_user.id,
                small.id,
                "u_mar",
                date(2026, 3, 1),
                date(2026, 3, 31),
                "2400",
                "2500",
                institution="UOB",
                last4="2222",
            ),
            _stmt(
                test_user.id,
                large.id,
                "dbs_jan",
                date(2026, 1, 1),
                date(2026, 1, 31),
                "10000",
                "10000",
                institution="DBS",
                last4="3333",
            ),
            _stmt(
                test_user.id,
                large.id,
                "dbs_mar",
                date(2026, 3, 1),
                date(2026, 3, 31),
                "14600",
                "15000",
                institution="DBS",
                last4="3333",
            ),
        ]
    )
    await db.flush()
    uploads = [
        a
        for a in (
            await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 3, 31), currency="SGD")
        ).action_items
        if a.action_type == "UPLOAD_STATEMENT"
    ]
    assert (
        len(uploads) == 2
        and "DBS Multiplier (*3333)" in uploads[0].title
        and "+4600.00 SGD" in uploads[0].description
        and "92%" in uploads[0].description
    )
    assert (
        "UOB Cash (*2222)" in uploads[1].title
        and "+400.00 SGD" in uploads[1].description
        and "8%" in uploads[1].description
    )


async def test_AC_reporting_2832_3_tiny_plug_and_missing_boundary_balances_branches(
    db: AsyncSession, test_user: User
) -> None:
    [citi] = await seed_accounts(db, test_user.id, ("Citibank", AccountType.ASSET))
    db.add_all(
        [
            _stmt(
                test_user.id,
                citi.id,
                "c_jan",
                date(2026, 1, 1),
                date(2026, 1, 31),
                "10000.00",
                "10000.00",
                institution="Citibank",
                last4="9999",
            ),
            _stmt(
                test_user.id,
                citi.id,
                "c_mar",
                date(2026, 3, 1),
                date(2026, 3, 31),
                "10000.50",
                "10000.50",
                institution="Citibank",
                last4="9999",
            ),
        ]
    )
    await db.flush()
    res_tiny = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 3, 31), currency="SGD")
    assert "minor cross-period rounding absorbed" in res_tiny.temporal_continuity_invariant.summary

    db.add_all(
        [
            _stmt(
                test_user.id,
                citi.id,
                "c_late",
                date(2026, 3, 31),
                date(2026, 3, 31),
                "12500.50",
                "12500.50",
                institution="Citibank",
                last4="9999",
            ),
            _stmt(
                test_user.id,
                citi.id,
                "c_ret",
                date(2025, 10, 1),
                date(2025, 10, 31),
                "9000",
                "9000",
                status=BankStatementStatus.RETIRED,
                institution="Citibank",
                last4="9999",
            ),
            _stmt(
                test_user.id,
                citi.id,
                "c_rej",
                date(2025, 11, 1),
                date(2025, 11, 30),
                "9000",
                "9000",
                status=BankStatementStatus.REJECTED,
                institution="Citibank",
                last4="9999",
            ),
        ]
    )
    await db.flush()
    res_f = await compute_personal_data_quality(db, test_user.id, as_of_date=date(2026, 3, 31), currency="SGD")
    assert res_f.temporal_continuity_invariant.is_healthy is False
    for m in ("2025-10", "2025-11", "2025-12"):
        b = next(x for x in res_f.timeline if x.month == m)
        assert (b.statement_count, b.status) == (0, "NO_DATA")
