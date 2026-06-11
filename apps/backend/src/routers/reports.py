"""Financial reporting API router."""

from __future__ import annotations

import csv
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, union

from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    Direction,
    FxRate,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.models.layer2 import AtomicPosition, AtomicTransaction
from src.models.layer3 import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.models.portfolio import DividendIncome, MarketDataOverride
from src.schemas import (
    AccountLineageResponse,
    AccountTrendResponse,
    AnnualizedIncomeScheduleHolding,
    AnnualizedIncomeScheduleIncome,
    AnnualizedIncomeScheduleNetWorthTreatment,
    AnnualizedIncomeScheduleResponse,
    BalanceSheetResponse,
    BreakdownPeriod,
    BreakdownType,
    CashFlowResponse,
    CategoryBreakdownResponse,
    FrameworkPolicyResult,
    IncomeStatementResponse,
    NetWorthGranularity,
    NetWorthTimeSeriesResponse,
    PersonalReportingFrameworkId,
    PersonalReportPackageContractResponse,
    PersonalReportPackageNotesResponse,
    PersonalReportPackageReadinessResponse,
    PersonalReportPackageTraceabilityResponse,
    TrendPeriod,
)
from src.services.confidence_tier import derive_confidence_tier
from src.services.evidence_lineage import EvidenceLineageService
from src.services.framework_policy import derive_user_framework_policy_result
from src.services.fx import FxRateError, convert_amount
from src.services.market_data import ensure_market_data_fresh
from src.services.report_readiness import get_personal_report_package_readiness
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_lineage,
    get_account_trend,
    get_category_breakdown,
    get_net_worth_timeseries,
    income_bucket,
)
from src.utils import raise_bad_request, raise_not_found

router = APIRouter(prefix="/reports", tags=["reports"])
logger = get_logger(__name__)


def _target_currency_pair(currency: str | None) -> list[str]:
    target = (currency or settings.base_currency).strip().upper()
    base = settings.base_currency.strip().upper()
    if target == base:
        return []
    return [f"{target}/{base}"]


async def _ensure_report_market_data_fresh(
    db: DbSession,
    user_id: CurrentUserId,
    *,
    currency: str | None,
    end_date: date,
) -> None:
    has_report_subjects = await db.scalar(select(Account.id).where(Account.user_id == user_id).limit(1))
    await ensure_market_data_fresh(
        db,
        user_id=user_id,
        end_date=end_date,
        include_default_fx=False,
        extra_fx_pairs=_target_currency_pair(currency) if has_report_subjects is not None else [],
    )


@router.get("/currencies", response_model=list[str])
async def get_available_currencies(
    db: DbSession = None,
) -> list[str]:
    """Get list of currencies with FX data available."""
    base_stmt = select(FxRate.base_currency).distinct()
    quote_stmt = select(FxRate.quote_currency).distinct()
    combined = union(base_stmt, quote_stmt).subquery()
    result = await db.execute(select(combined.c.base_currency).order_by(combined.c.base_currency))
    currencies = [row[0] for row in result.fetchall()]

    if settings.base_currency not in currencies:
        currencies = [settings.base_currency] + currencies

    return currencies


class ExportFormat(str, Enum):
    """Supported export formats."""

    CSV = "csv"


class ReportType(str, Enum):
    """Supported report types for export."""

    BALANCE_SHEET = "balance-sheet"
    INCOME_STATEMENT = "income-statement"
    CASH_FLOW = "cash-flow"
    PACKAGE = "package"


PERSONAL_REPORT_PACKAGE_CONTRACT: dict = {
    "package_id": "personal-financial-report-package",
    "version": "1.0",
    "period_semantics": {
        "start_date": "required for period sections",
        "end_date": "required for period sections",
        "as_of_date": "required for point-in-time sections",
        "currency": "ISO-4217 code; defaults to base currency when omitted",
        "framework_id": "selected supported personal reporting framework",
        "decimal_serialization": "string",
    },
    "supported_frameworks": [
        "personal_us_gaap_like",
        "personal_hkfrs_like",
    ],
    "selected_framework_id": None,
    "framework_policy_endpoint": "/api/reports/package/framework-policy",
    "sections": [
        {
            "section_id": "balance_sheet",
            "label": "Balance Sheet",
            "owner_epic": "EPIC-005",
            "period_type": "as_of",
            "source_endpoint": "/api/reports/balance-sheet",
            "status": "ready",
            "decimal_total_fields": ["total_assets", "total_liabilities", "total_equity", "equation_delta"],
        },
        {
            "section_id": "income_statement",
            "label": "Income Statement",
            "owner_epic": "EPIC-005",
            "period_type": "period",
            "source_endpoint": "/api/reports/income-statement",
            "status": "ready",
            "decimal_total_fields": ["total_income", "total_expenses", "net_income"],
        },
        {
            "section_id": "cash_flow",
            "label": "Cash Flow",
            "owner_epic": "EPIC-005",
            "period_type": "period",
            "source_endpoint": "/api/reports/cash-flow",
            "status": "ready",
            "decimal_total_fields": [
                "operating_activities",
                "investing_activities",
                "financing_activities",
                "net_cash_flow",
                "beginning_cash",
                "ending_cash",
            ],
        },
        {
            "section_id": "investment_performance",
            "label": "Investment Performance",
            "owner_epic": "EPIC-017",
            "period_type": "period_and_as_of",
            "source_endpoint": "/api/portfolio/performance/report-schedule",
            "status": "ready",
            "decimal_total_fields": [
                "xirr",
                "time_weighted_return",
                "money_weighted_return",
                "realized_pnl",
                "unrealized_pnl",
                "dividend_income",
            ],
        },
        {
            "section_id": "annualized_income_long_term",
            "label": "Annualized Income & Long-Term Compensation",
            "owner_epic": "EPIC-011",
            "period_type": "trailing_12_months_and_as_of",
            "source_endpoint": "/api/reports/package/annualized-income-schedule",
            "status": "ready",
            "blocking_issue": None,
            "decimal_total_fields": [
                "annualized_salary",
                "annualized_bonus",
                "annualized_dividend",
                "annualized_total",
                "restricted_fair_value",
            ],
        },
        {
            "section_id": "notes",
            "label": "Notes & Disclosures",
            "owner_epic": "EPIC-005",
            "period_type": "package",
            "source_endpoint": "/api/reports/package/notes",
            "status": "ready",
            "blocking_issue": None,
            "decimal_total_fields": [],
        },
        {
            "section_id": "traceability_appendix",
            "label": "Traceability Appendix",
            "owner_epic": "EPIC-018",
            "period_type": "package",
            "source_endpoint": "/api/reports/package/traceability",
            "status": "ready",
            "blocking_issue": None,
            "decimal_total_fields": [],
        },
    ],
    "export_contract": {
        "formats": ["json", "csv"],
        "csv_columns": [
            "package_id",
            "section_id",
            "line_id",
            "label",
            "amount",
            "currency",
            "source_state",
            "selected_framework_id",
            "framework_policy_result_id",
            "framework_policy_matrix_version",
            "evidence_bundle_references",
        ],
    },
}

PERSONAL_REPORT_PACKAGE_NOTES: dict = {
    "section_id": "notes",
    "label": "Notes & Disclosures",
    "status": "ready",
    "non_compliance_statement": (
        "This personal management report is not a regulated filing, not an audit opinion, "
        "not legal advice, and not tax advice. Accounting and listed-company reporting "
        "references are used only as coverage and disclosure discipline."
    ),
    "notes": [
        {
            "note_id": "basis-of-preparation",
            "label": "Basis of Preparation",
            "owner_epic": "EPIC-005",
            "basis": "personal_management_report_package_contract",
            "source_state": "package_contract",
            "applies_to_sections": [
                "balance_sheet",
                "income_statement",
                "cash_flow",
                "investment_performance",
                "annualized_income_long_term",
            ],
            "disclosure": (
                "The package assembles personal finance statements and schedules for management use. "
                "It does not assert compliance with a statutory accounting framework."
            ),
        },
        {
            "note_id": "reporting-period-and-currency",
            "label": "Reporting Period and Currency",
            "owner_epic": "EPIC-005",
            "basis": "package_period_semantics",
            "source_state": "request_parameters",
            "applies_to_sections": [
                "balance_sheet",
                "income_statement",
                "cash_flow",
                "investment_performance",
                "annualized_income_long_term",
            ],
            "disclosure": (
                "Period sections use start and end dates; point-in-time sections use as-of dates. "
                "Currency values serialize Decimal amounts as strings."
            ),
        },
        {
            "note_id": "valuation-basis",
            "label": "Valuation Basis",
            "owner_epic": "EPIC-011",
            "basis": "manual_valuation_component_rules",
            "source_state": "manual_valuation_snapshots",
            "applies_to_sections": ["balance_sheet", "annualized_income_long_term"],
            "disclosure": (
                "Manual valuation snapshots supply property, liability, and restricted compensation "
                "values as of the selected reporting date."
            ),
        },
        {
            "note_id": "investment-market-data",
            "label": "Investment Market Data",
            "owner_epic": "EPIC-017",
            "basis": "investment_performance_schedule",
            "source_state": "brokerage_imports_and_market_data",
            "applies_to_sections": ["investment_performance", "balance_sheet"],
            "disclosure": (
                "Portfolio metrics depend on imported brokerage positions, available prices, "
                "dividend facts, and the schedule data-freshness flags."
            ),
        },
        {
            "note_id": "source-confidence-review",
            "label": "Source Confidence and Review",
            "owner_epic": "EPIC-018",
            "basis": "trusted_or_reviewed_source_state",
            "source_state": "reviewed_journal_and_statement_links",
            "applies_to_sections": ["balance_sheet", "income_statement", "cash_flow"],
            "disclosure": (
                "Report totals depend on posted or reconciled journal entries and reviewed source "
                "documents; unresolved extraction or reconciliation checks remain outside trusted totals."
            ),
        },
        {
            "note_id": "restricted-asset-treatment",
            "label": "Restricted Asset Treatment",
            "owner_epic": "EPIC-011",
            "basis": "restricted_compensation_liquidity_policy",
            "source_state": "manual_valuation_snapshots",
            "applies_to_sections": ["balance_sheet", "annualized_income_long_term"],
            "disclosure": (
                "Restricted ESOP, RSU, and stock option values are excluded from liquid net worth by "
                "default and shown separately in the long-term compensation schedule."
            ),
        },
    ],
}

PERSONAL_REPORT_PACKAGE_TRACEABILITY: dict = {
    "section_id": "traceability_appendix",
    "label": "Traceability Appendix",
    "status": "ready",
    "lines": [
        {
            "line_id": "balance_sheet.total_assets",
            "section_id": "balance_sheet",
            "label": "Total Assets",
            "amount_field": "total_assets",
            "currency_field": "currency",
            "source_state": "posted_reconciled_journal_lines_and_manual_valuations",
            "source_anchor": {
                "state": "available",
                "source_types": [
                    "bank_statement",
                    "brokerage_import",
                    "manual_valuation_snapshot",
                ],
                "identifier_fields": [
                    "statement_transaction_ids",
                    "brokerage_statement_ids",
                    "manual_valuation_snapshot_ids",
                ],
            },
            "ledger_anchor": {
                "state": "available",
                "entry_statuses": ["posted", "reconciled"],
                "identifier_fields": ["journal_entry_ids", "journal_line_ids"],
            },
            "review_state": "trusted_or_explicit_manual_input",
            "confidence_tier": "TRUSTED",
            "source_classes": ["bank_statement", "brokerage_statement", "manual_record"],
            "proof_level": "hybrid",
            "anchor_count": 0,
            "blocker_codes": [],
        },
        {
            "line_id": "income_statement.total_income",
            "section_id": "income_statement",
            "label": "Total Income",
            "amount_field": "total_income",
            "currency_field": "currency",
            "source_state": "posted_reconciled_income_journal_lines",
            "source_anchor": {
                "state": "available",
                "source_types": ["bank_statement", "manual_journal_entry"],
                "identifier_fields": ["statement_transaction_ids", "journal_entry_source_ids"],
            },
            "ledger_anchor": {
                "state": "available",
                "entry_statuses": ["posted", "reconciled"],
                "identifier_fields": ["journal_entry_ids", "journal_line_ids"],
            },
            "review_state": "trusted_or_reviewed",
            "confidence_tier": "TRUSTED",
            "source_classes": ["bank_statement", "manual_record"],
            "proof_level": "deterministic_pr",
            "anchor_count": 0,
            "blocker_codes": [],
        },
        {
            "line_id": "income_statement.total_expenses",
            "section_id": "income_statement",
            "label": "Total Expenses",
            "amount_field": "total_expenses",
            "currency_field": "currency",
            "source_state": "posted_reconciled_expense_journal_lines",
            "source_anchor": {
                "state": "available",
                "source_types": ["bank_statement", "manual_journal_entry"],
                "identifier_fields": ["statement_transaction_ids", "journal_entry_source_ids"],
            },
            "ledger_anchor": {
                "state": "available",
                "entry_statuses": ["posted", "reconciled"],
                "identifier_fields": ["journal_entry_ids", "journal_line_ids"],
            },
            "review_state": "trusted_or_reviewed",
            "confidence_tier": "TRUSTED",
            "source_classes": ["bank_statement", "manual_record"],
            "proof_level": "deterministic_pr",
            "anchor_count": 0,
            "blocker_codes": [],
        },
        {
            "line_id": "cash_flow.net_cash_flow",
            "section_id": "cash_flow",
            "label": "Net Cash Flow",
            "amount_field": "summary.net_cash_flow",
            "currency_field": "currency",
            "source_state": "cash_bank_journal_lines",
            "source_anchor": {
                "state": "available",
                "source_types": ["bank_statement", "manual_journal_entry"],
                "identifier_fields": ["statement_transaction_ids", "journal_entry_source_ids"],
            },
            "ledger_anchor": {
                "state": "available",
                "entry_statuses": ["posted", "reconciled"],
                "identifier_fields": ["journal_entry_ids", "journal_line_ids"],
            },
            "review_state": "trusted_or_reviewed",
            "confidence_tier": "TRUSTED",
            "source_classes": ["bank_statement", "csv_export", "manual_record"],
            "proof_level": "deterministic_pr",
            "anchor_count": 0,
            "blocker_codes": [],
        },
        {
            "line_id": "investment_performance.market_value",
            "section_id": "investment_performance",
            "label": "Investment Market Value",
            "amount_field": "holdings.market_value",
            "currency_field": "currency",
            "source_state": "brokerage_imports_market_data_and_ledger_cost_basis",
            "source_anchor": {
                "state": "available",
                "source_types": ["brokerage_import", "market_data_price", "journal_entry"],
                "identifier_fields": ["brokerage_statement_ids", "price_source_ids", "ledger_entry_ids"],
            },
            "ledger_anchor": {
                "state": "available",
                "entry_statuses": ["posted", "reconciled"],
                "identifier_fields": ["ledger_entry_ids", "journal_line_ids"],
            },
            "review_state": "market_data_fresh_or_disclosed_stale",
            "confidence_tier": "HIGH",
            "source_classes": ["brokerage_statement"],
            "proof_level": "hybrid",
            "anchor_count": 0,
            "blocker_codes": ["stale_market_data"],
        },
        {
            "line_id": "annualized_income_long_term.annualized_total",
            "section_id": "annualized_income_long_term",
            "label": "Annualized Total Income",
            "amount_field": "income.annualized_total",
            "currency_field": "income.currency",
            "source_state": "posted_reconciled_income_journal_lines_trailing_12_months",
            "source_anchor": {
                "state": "available",
                "source_types": ["bank_statement", "manual_journal_entry"],
                "identifier_fields": ["journal_entry_source_ids", "statement_transaction_ids"],
            },
            "ledger_anchor": {
                "state": "available",
                "entry_statuses": ["posted", "reconciled"],
                "identifier_fields": ["journal_entry_ids", "journal_line_ids"],
            },
            "review_state": "trusted_or_reviewed",
            "confidence_tier": "TRUSTED",
            "source_classes": ["bank_statement", "csv_export", "manual_record"],
            "proof_level": "deterministic_pr",
            "anchor_count": 0,
            "blocker_codes": [],
        },
        {
            "line_id": "annualized_income_long_term.restricted_fair_value_total",
            "section_id": "annualized_income_long_term",
            "label": "Restricted Fair Value Total",
            "amount_field": "restricted_fair_value_total",
            "currency_field": "restricted_fair_value_total_currency",
            "source_state": "manual_valuation_snapshots",
            "source_anchor": {
                "state": "available",
                "source_types": ["manual_valuation_snapshot"],
                "identifier_fields": ["manual_valuation_snapshot_ids"],
            },
            "ledger_anchor": {
                "state": "not_applicable",
                "entry_statuses": [],
                "identifier_fields": [],
                "unavailable_reason": "Restricted compensation is disclosed as explicit manual valuation input, not posted ledger cash.",
            },
            "review_state": "explicit_manual_input",
            "confidence_tier": "MEDIUM",
            "source_classes": ["esop_rsu_plan", "manual_record"],
            "proof_level": "manual_trusted",
            "anchor_count": 0,
            "blocker_codes": ["manual_only_source"],
        },
        {
            "line_id": "notes.non_compliance_statement",
            "section_id": "notes",
            "label": "Package Non-Compliance Statement",
            "amount_field": None,
            "currency_field": None,
            "source_state": "package_contract",
            "source_anchor": {
                "state": "available",
                "source_types": ["package_contract"],
                "identifier_fields": ["note_id"],
            },
            "ledger_anchor": {
                "state": "not_applicable",
                "entry_statuses": [],
                "identifier_fields": [],
                "unavailable_reason": "Disclosure wording is not a ledger-derived amount.",
            },
            "review_state": "not_applicable",
            "confidence_tier": "UNAVAILABLE",
            "source_classes": [],
            "proof_level": "static_contract",
            "anchor_count": 0,
            "blocker_codes": [],
        },
    ],
    "completeness_warnings": [
        {
            "code": "missing_source_anchor",
            "label": "Missing source anchor",
            "applies_to_sections": ["balance_sheet", "income_statement", "cash_flow"],
            "state": "fail_package_proof_for_trusted_totals",
            "remediation": "Expose statement transaction, document, or explicit manual-input identifiers before treating totals as trusted.",
        },
        {
            "code": "manual_only_source",
            "label": "Manual-only source coverage",
            "applies_to_sections": ["balance_sheet", "annualized_income_long_term"],
            "state": "explicit_manual_input_required",
            "remediation": "Keep manual valuation snapshot identifiers and valuation basis visible in the appendix.",
        },
        {
            "code": "stale_market_data",
            "label": "Stale market data",
            "applies_to_sections": ["investment_performance", "balance_sheet"],
            "state": "disclose_stale_or_refresh_required",
            "remediation": "Use schedule freshness flags and refresh market data when provider prices are stale.",
        },
        {
            "code": "duplicate_source_coverage",
            "label": "Duplicate source coverage",
            "applies_to_sections": ["balance_sheet", "cash_flow"],
            "state": "exclude_or_disclose_duplicate_source",
            "remediation": "Preserve duplicate detection and reconciliation state so the same source is not counted twice.",
        },
        {
            "code": "overlapping_statement_period",
            "label": "Overlapping statement period",
            "applies_to_sections": ["income_statement", "cash_flow"],
            "state": "review_required_before_trusted_total",
            "remediation": "Surface overlapping bank statement periods and keep affected totals out of trusted proof until reviewed.",
        },
    ],
}


def _identifier(prefix: str, value: object) -> str:
    return f"{prefix}:{value}"


def _dedupe_identifiers(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _dedupe_details(values: list[dict]) -> list[dict]:
    seen: set[str] = set()
    details: list[dict] = []
    for value in values:
        identifier = str(value.get("identifier") or "")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        details.append(value)
    return details


def _source_document_identifiers(source_documents: object) -> list[str]:
    if isinstance(source_documents, list):
        docs = source_documents
    elif isinstance(source_documents, dict):
        docs = source_documents.get("documents", [])
    else:
        docs = []

    identifiers: list[str] = []
    for doc in docs:
        if isinstance(doc, dict) and doc.get("doc_id"):
            identifiers.append(_identifier("brokerage_document", doc["doc_id"]))
    return identifiers


def _source_document_details(source_documents: object, *, contribution_basis: str) -> list[dict]:
    if isinstance(source_documents, list):
        docs = source_documents
    elif isinstance(source_documents, dict):
        docs = source_documents.get("documents", [])
    else:
        docs = []

    details: list[dict] = []
    for doc in docs:
        if not isinstance(doc, dict) or not doc.get("doc_id"):
            continue
        source_type = str(doc.get("doc_type") or "brokerage_statement")
        details.append(
            {
                "identifier": _identifier("brokerage_document", doc["doc_id"]),
                "source_kind": "uploaded_document",
                "source_id": str(doc["doc_id"]),
                "source_type": source_type,
                "amount": None,
                "currency": None,
                "review_state": "imported_or_reviewed_payload",
                "confidence_tier": "HIGH",
                "contribution_basis": contribution_basis,
            }
        )
    return details


def _add_anchor_identifiers(
    lines_by_id: dict[str, dict],
    line_id: str,
    anchor_name: str,
    identifiers: list[str],
) -> None:
    line = lines_by_id.get(line_id)
    if line is None:
        return
    line[anchor_name]["identifiers"] = _dedupe_identifiers([*line[anchor_name].get("identifiers", []), *identifiers])
    source_count = len(line.get("source_anchor", {}).get("identifiers", []))
    ledger_count = len(line.get("ledger_anchor", {}).get("identifiers", []))
    line["anchor_count"] = source_count + ledger_count


def _add_anchor_details(
    lines_by_id: dict[str, dict],
    line_id: str,
    anchor_name: str,
    details: list[dict],
) -> None:
    line = lines_by_id.get(line_id)
    if line is None:
        return
    anchor = line[anchor_name]
    anchor["details"] = _dedupe_details([*anchor.get("details", []), *details])
    identifiers = [str(detail["identifier"]) for detail in anchor["details"] if detail.get("identifier")]
    anchor["identifiers"] = _dedupe_identifiers([*anchor.get("identifiers", []), *identifiers])
    source_count = len(line.get("source_anchor", {}).get("identifiers", []))
    ledger_count = len(line.get("ledger_anchor", {}).get("identifiers", []))
    line["anchor_count"] = source_count + ledger_count


def _append_blocker(line: dict, blocker_code: str) -> None:
    blockers = set(line.get("blocker_codes", []))
    blockers.add(blocker_code)
    line["blocker_codes"] = sorted(blockers)


def _review_state_for_source_type(source_type: JournalEntrySourceType) -> str:
    if source_type == JournalEntrySourceType.MANUAL:
        return "explicit_manual_input"
    if source_type == JournalEntrySourceType.USER_CONFIRMED:
        return "reviewed_source"
    if source_type == JournalEntrySourceType.AUTO_MATCHED:
        return "auto_matched"
    if source_type in {JournalEntrySourceType.AUTO_PARSED, JournalEntrySourceType.BANK_STATEMENT}:
        return "unreviewed_auto_parse"
    return "system_generated"


def _ledger_anchor_detail(entry: JournalEntry, line: JournalLine, account: Account) -> dict:
    return {
        "identifier": _identifier("journal_line", line.id),
        "source_kind": "journal_line",
        "source_id": str(line.id),
        "source_type": entry.source_type.value,
        "amount": line.amount,
        "currency": line.currency,
        "review_state": _review_state_for_source_type(entry.source_type),
        "confidence_tier": derive_confidence_tier(entry.source_type),
        "contribution_basis": "ledger_line_amount",
        "journal_entry_id": str(entry.id),
        "journal_line_id": str(line.id),
        "account_id": str(account.id),
        "account_type": account.type.value,
    }


def _journal_source_anchor_detail(
    entry: JournalEntry,
    line: JournalLine,
    account: Account,
    *,
    statement_txn_ids: set[UUID],
    atomic_txn_ids: set[UUID],
) -> dict:
    source_id = entry.source_id
    confidence_tier = derive_confidence_tier(entry.source_type)
    review_state = _review_state_for_source_type(entry.source_type)
    base = {
        "amount": line.amount,
        "currency": line.currency,
        "review_state": review_state,
        "confidence_tier": confidence_tier,
        "contribution_basis": "journal_entry_source_amount",
        "journal_entry_id": str(entry.id),
        "journal_line_id": str(line.id),
        "account_id": str(account.id),
        "account_type": account.type.value,
    }

    if entry.source_type == JournalEntrySourceType.MANUAL and source_id is None:
        return {
            **base,
            "identifier": _identifier("manual_journal_entry", entry.id),
            "source_kind": "manual_journal_entry",
            "source_id": str(entry.id),
            "source_type": "manual",
        }

    if source_id is not None and source_id in statement_txn_ids:
        return {
            **base,
            "identifier": _identifier("statement_transaction", source_id),
            "source_kind": "bank_statement_transaction",
            "source_id": str(source_id),
            "source_type": "bank_statement",
        }

    if source_id is not None and source_id in atomic_txn_ids:
        return {
            **base,
            "identifier": _identifier("atomic_transaction", source_id),
            "source_kind": "atomic_transaction",
            "source_id": str(source_id),
            "source_type": "atomic_transaction",
        }

    if source_id is None:
        return {
            **base,
            "identifier": _identifier("journal_entry", entry.id),
            "source_kind": "journal_entry",
            "source_id": str(entry.id),
            "source_type": entry.source_type.value,
        }

    return {
        **base,
        "identifier": _identifier("unknown_source", source_id),
        "source_kind": "unknown_source",
        "source_id": str(source_id),
        "source_type": entry.source_type.value,
    }


async def _evidence_graph_source_anchor_details(
    db: DbSession,
    user_id: CurrentUserId,
    *,
    line: JournalLine,
    ledger_detail: dict,
) -> list[dict]:
    lineage = EvidenceLineageService()
    steps = await lineage.get_upstream(
        db,
        user_id=user_id,
        entity_type="journal_line",
        entity_id=line.id,
        node_kind="ledger_line",
    )
    details: list[dict] = []
    for step in steps:
        node = step.node
        if node.node_kind not in {"source_document", "atomic_fact"}:
            continue
        source_type = str(node.properties.get("document_type") or node.entity_type)
        details.append(
            {
                "identifier": _identifier(node.entity_type, node.entity_id),
                "source_kind": node.entity_type,
                "source_id": str(node.entity_id),
                "source_type": source_type,
                "amount": ledger_detail["amount"],
                "currency": ledger_detail["currency"],
                "review_state": ledger_detail["review_state"],
                "confidence_tier": ledger_detail["confidence_tier"],
                "contribution_basis": "evidence_graph_upstream",
                "journal_entry_id": ledger_detail["journal_entry_id"],
                "journal_line_id": ledger_detail["journal_line_id"],
                "account_id": ledger_detail["account_id"],
                "account_type": ledger_detail["account_type"],
            }
        )
    return _dedupe_details(details)


async def _personal_report_package_traceability_payload(
    *,
    start_date: date | None,
    end_date: date | None,
    as_of_date: date | None,
    db: DbSession | None,
    user_id: CurrentUserId | None,
) -> dict:
    payload = deepcopy(PERSONAL_REPORT_PACKAGE_TRACEABILITY)
    if db is None or user_id is None:
        return payload

    report_end = end_date or as_of_date or date.today()
    report_start = start_date or report_end - timedelta(days=365)
    report_as_of = as_of_date or report_end
    lines_by_id = {line["line_id"]: line for line in payload["lines"]}

    entry_source_ids_result = await db.execute(
        select(JournalEntry.source_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_id.is_not(None))
        .where(JournalEntry.entry_date >= report_start)
        .where(JournalEntry.entry_date <= report_end)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )
    entry_source_ids = {source_id for source_id in entry_source_ids_result.scalars().all() if source_id is not None}
    # Legacy bank_statement_transactions sources were decomposed into Layer-2
    # AtomicTransaction rows (EPIC-011 Stage 3); journal entry sources now resolve
    # exclusively against AtomicTransaction.
    statement_txn_ids: set[UUID] = set()
    atomic_txn_ids: set[UUID] = set()
    if entry_source_ids:
        atomic_txn_result = await db.execute(
            select(AtomicTransaction.id)
            .where(AtomicTransaction.user_id == user_id)
            .where(AtomicTransaction.id.in_(entry_source_ids))
        )
        atomic_txn_ids = set(atomic_txn_result.scalars().all())

    ledger_result = await db.execute(
        select(JournalEntry, JournalLine, Account)
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date >= report_start)
        .where(JournalEntry.entry_date <= report_end)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    ledger_identifiers: list[str] = []
    source_identifiers: list[str] = []
    income_source_identifiers: list[str] = []
    expense_source_identifiers: list[str] = []
    cash_source_identifiers: list[str] = []
    ledger_details: list[dict] = []
    source_details: list[dict] = []
    income_ledger_details: list[dict] = []
    expense_ledger_details: list[dict] = []
    cash_ledger_details: list[dict] = []
    income_source_details: list[dict] = []
    expense_source_details: list[dict] = []
    cash_source_details: list[dict] = []
    unknown_source_line_ids: set[str] = set()
    for entry, line, account in ledger_result.all():
        ledger_detail = _ledger_anchor_detail(entry, line, account)
        source_detail = _journal_source_anchor_detail(
            entry,
            line,
            account,
            statement_txn_ids=statement_txn_ids,
            atomic_txn_ids=atomic_txn_ids,
        )
        graph_source_details = await _evidence_graph_source_anchor_details(
            db,
            user_id,
            line=line,
            ledger_detail=ledger_detail,
        )
        entry_source_details = [source_detail, *graph_source_details]
        entry_source_identifiers = [
            str(detail["identifier"]) for detail in entry_source_details if detail.get("identifier")
        ]
        ledger_details.append(ledger_detail)
        source_details.extend(entry_source_details)
        ledger_identifiers.extend(
            [
                _identifier("journal_entry", entry.id),
                _identifier("journal_line", line.id),
            ]
        )
        source_identifiers.extend(entry_source_identifiers)
        is_unknown_source = source_detail["source_kind"] == "unknown_source"
        if account.type == AccountType.INCOME:
            income_source_identifiers.extend(entry_source_identifiers)
            income_source_details.extend(entry_source_details)
            income_ledger_details.append(ledger_detail)
            if is_unknown_source:
                unknown_source_line_ids.update(
                    {
                        "income_statement.total_income",
                        "annualized_income_long_term.annualized_total",
                    }
                )
        elif account.type == AccountType.EXPENSE:
            expense_source_identifiers.extend(entry_source_identifiers)
            expense_source_details.extend(entry_source_details)
            expense_ledger_details.append(ledger_detail)
            if is_unknown_source:
                unknown_source_line_ids.add("income_statement.total_expenses")
        elif account.type == AccountType.ASSET:
            cash_source_identifiers.extend(entry_source_identifiers)
            cash_source_details.extend(entry_source_details)
            cash_ledger_details.append(ledger_detail)
            if is_unknown_source:
                unknown_source_line_ids.update(
                    {
                        "balance_sheet.total_assets",
                        "cash_flow.net_cash_flow",
                    }
                )

    manual_result = await db.execute(
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.as_of_date <= report_as_of)
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )
    manual_snapshots = list(manual_result.scalars().all())
    manual_identifiers = [_identifier("manual_valuation_snapshot", snapshot.id) for snapshot in manual_snapshots]
    manual_details = [
        {
            "identifier": _identifier("manual_valuation_snapshot", snapshot.id),
            "source_kind": "manual_valuation_snapshot",
            "source_id": str(snapshot.id),
            "source_type": snapshot.component_type.value,
            "amount": snapshot.value,
            "currency": snapshot.currency,
            "review_state": "explicit_manual_input",
            "confidence_tier": "MEDIUM",
            "contribution_basis": "manual_valuation_snapshot_amount",
        }
        for snapshot in manual_snapshots
    ]
    restricted_manual_identifiers = [
        _identifier("manual_valuation_snapshot", snapshot.id)
        for snapshot in manual_snapshots
        if snapshot.liquidity_class == ManualValuationLiquidityClass.RESTRICTED
    ]
    restricted_manual_details = [
        detail
        for detail, snapshot in zip(manual_details, manual_snapshots, strict=False)
        if snapshot.liquidity_class == ManualValuationLiquidityClass.RESTRICTED
    ]

    atomic_result = await db.execute(
        select(AtomicPosition)
        .where(AtomicPosition.user_id == user_id)
        .where(AtomicPosition.snapshot_date <= report_as_of)
        .order_by(AtomicPosition.snapshot_date.desc(), AtomicPosition.created_at.desc())
    )
    atomic_positions = list(atomic_result.scalars().all())
    atomic_identifiers = [_identifier("atomic_position", position.id) for position in atomic_positions]
    atomic_details = [
        {
            "identifier": _identifier("atomic_position", position.id),
            "source_kind": "atomic_position",
            "source_id": str(position.id),
            "source_type": "brokerage_statement",
            "amount": position.market_value,
            "currency": position.currency,
            "review_state": "imported_or_reviewed_payload",
            "confidence_tier": "HIGH",
            "contribution_basis": "position_market_value",
        }
        for position in atomic_positions
    ]
    brokerage_document_identifiers = [
        identifier
        for position in atomic_positions
        for identifier in _source_document_identifiers(position.source_documents)
    ]
    brokerage_document_details = [
        detail
        for position in atomic_positions
        for detail in _source_document_details(
            position.source_documents,
            contribution_basis="position_source_document",
        )
    ]

    dividend_result = await db.execute(
        select(DividendIncome)
        .where(DividendIncome.user_id == user_id)
        .where(DividendIncome.payment_date >= report_start)
        .where(DividendIncome.payment_date <= report_end)
    )
    dividends = list(dividend_result.scalars().all())
    dividend_identifiers = [_identifier("dividend_income", dividend.id) for dividend in dividends]
    dividend_details = [
        {
            "identifier": _identifier("dividend_income", dividend.id),
            "source_kind": "dividend_income",
            "source_id": str(dividend.id),
            "source_type": "brokerage_statement",
            "amount": dividend.amount,
            "currency": dividend.currency,
            "review_state": "imported_or_reviewed_payload",
            "confidence_tier": "HIGH",
            "contribution_basis": "dividend_income_amount",
        }
        for dividend in dividends
    ]

    price_result = await db.execute(
        select(MarketDataOverride)
        .where(MarketDataOverride.user_id == user_id)
        .where(MarketDataOverride.price_date <= report_as_of)
        .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
    )
    market_prices = list(price_result.scalars().all())
    market_price_identifiers = [_identifier("market_price", price.id) for price in market_prices]
    market_price_details = [
        {
            "identifier": _identifier("market_price", price.id),
            "source_kind": "market_price",
            "source_id": str(price.id),
            "source_type": price.source.value,
            "amount": price.price,
            "currency": price.currency,
            "review_state": "manual_override" if price.source.value == "manual" else "provider_price",
            "confidence_tier": "HIGH",
            "contribution_basis": "market_price",
        }
        for price in market_prices
    ]

    _add_anchor_identifiers(
        lines_by_id,
        "balance_sheet.total_assets",
        "source_anchor",
        [*source_identifiers, *manual_identifiers, *atomic_identifiers, *brokerage_document_identifiers],
    )
    _add_anchor_identifiers(lines_by_id, "balance_sheet.total_assets", "ledger_anchor", ledger_identifiers)
    _add_anchor_details(
        lines_by_id,
        "balance_sheet.total_assets",
        "source_anchor",
        [*source_details, *manual_details, *atomic_details, *brokerage_document_details],
    )
    _add_anchor_details(lines_by_id, "balance_sheet.total_assets", "ledger_anchor", ledger_details)

    for line_id, identifiers, source_detail_values, ledger_detail_values in [
        (
            "income_statement.total_income",
            income_source_identifiers or source_identifiers,
            income_source_details or source_details,
            income_ledger_details or ledger_details,
        ),
        (
            "annualized_income_long_term.annualized_total",
            income_source_identifiers or source_identifiers,
            income_source_details or source_details,
            income_ledger_details or ledger_details,
        ),
        (
            "income_statement.total_expenses",
            expense_source_identifiers or source_identifiers,
            expense_source_details or source_details,
            expense_ledger_details or ledger_details,
        ),
        (
            "cash_flow.net_cash_flow",
            cash_source_identifiers or source_identifiers,
            cash_source_details or source_details,
            cash_ledger_details or ledger_details,
        ),
    ]:
        _add_anchor_identifiers(lines_by_id, line_id, "source_anchor", identifiers)
        _add_anchor_identifiers(lines_by_id, line_id, "ledger_anchor", ledger_identifiers)
        _add_anchor_details(lines_by_id, line_id, "source_anchor", source_detail_values)
        _add_anchor_details(lines_by_id, line_id, "ledger_anchor", ledger_detail_values)

    investment_source_identifiers = [
        *atomic_identifiers,
        *brokerage_document_identifiers,
        *market_price_identifiers,
        *dividend_identifiers,
    ]
    investment_source_details = [
        *atomic_details,
        *brokerage_document_details,
        *market_price_details,
        *dividend_details,
    ]
    _add_anchor_identifiers(
        lines_by_id,
        "investment_performance.market_value",
        "source_anchor",
        investment_source_identifiers,
    )
    _add_anchor_identifiers(lines_by_id, "investment_performance.market_value", "ledger_anchor", ledger_identifiers)
    _add_anchor_details(
        lines_by_id,
        "investment_performance.market_value",
        "source_anchor",
        investment_source_details,
    )
    _add_anchor_details(lines_by_id, "investment_performance.market_value", "ledger_anchor", ledger_details)

    _add_anchor_identifiers(
        lines_by_id,
        "annualized_income_long_term.restricted_fair_value_total",
        "source_anchor",
        restricted_manual_identifiers or manual_identifiers,
    )
    _add_anchor_details(
        lines_by_id,
        "annualized_income_long_term.restricted_fair_value_total",
        "source_anchor",
        restricted_manual_details or manual_details,
    )
    _add_anchor_identifiers(
        lines_by_id,
        "notes.non_compliance_statement",
        "source_anchor",
        ["package_contract:personal-financial-report-package"],
    )
    _add_anchor_details(
        lines_by_id,
        "notes.non_compliance_statement",
        "source_anchor",
        [
            {
                "identifier": "package_contract:personal-financial-report-package",
                "source_kind": "package_contract",
                "source_id": "personal-financial-report-package",
                "source_type": "static_contract",
                "amount": None,
                "currency": None,
                "review_state": "not_applicable",
                "confidence_tier": "UNAVAILABLE",
                "contribution_basis": "static_disclosure_contract",
            }
        ],
    )
    if unknown_source_line_ids:
        for line_id in unknown_source_line_ids:
            _append_blocker(lines_by_id[line_id], "unknown_source_anchor")
    return payload


@router.get("/package/contract", response_model=PersonalReportPackageContractResponse)
def personal_report_package_contract(
    framework_id: PersonalReportingFrameworkId | None = None,
) -> PersonalReportPackageContractResponse:
    """Return the stable package-level API/export contract."""
    payload = deepcopy(PERSONAL_REPORT_PACKAGE_CONTRACT)
    payload["selected_framework_id"] = framework_id.value if framework_id is not None else None
    return PersonalReportPackageContractResponse(**payload)


@router.get("/package/readiness", response_model=PersonalReportPackageReadinessResponse)
async def personal_report_package_readiness(
    framework_id: PersonalReportingFrameworkId | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    as_of_date: date | None = None,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> PersonalReportPackageReadinessResponse:
    """Return deterministic readiness and blocker state for the personal package."""
    payload = await get_personal_report_package_readiness(
        db,
        user_id,
        framework_id=framework_id,
        report_period_start=start_date,
        report_period_end=end_date,
        as_of_date=as_of_date,
    )
    return PersonalReportPackageReadinessResponse(**payload)


@router.get("/package/framework-policy", response_model=FrameworkPolicyResult)
async def personal_report_package_framework_policy(
    framework_id: PersonalReportingFrameworkId = PersonalReportingFrameworkId.US_GAAP_LIKE,
    start_date: date | None = None,
    end_date: date | None = None,
    as_of_date: date | None = None,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> FrameworkPolicyResult:
    """Return the selected framework policy result consumed by package assembly."""
    report_as_of = as_of_date or end_date or date.today()
    report_end = end_date or report_as_of
    report_start = start_date or report_end - timedelta(days=365)
    return await derive_user_framework_policy_result(
        db,
        user_id,
        framework_id=framework_id,
        report_period_start=report_start,
        report_period_end=report_end,
        as_of_date=report_as_of,
    )


@router.get("/package/notes", response_model=PersonalReportPackageNotesResponse)
def personal_report_package_notes() -> PersonalReportPackageNotesResponse:
    """Return package-level notes and disclosures."""
    return PersonalReportPackageNotesResponse(**PERSONAL_REPORT_PACKAGE_NOTES)


@router.get("/package/traceability", response_model=PersonalReportPackageTraceabilityResponse)
async def personal_report_package_traceability(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    as_of_date: date | None = Query(default=None),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> PersonalReportPackageTraceabilityResponse:
    """Return the package-level source-ledger-report traceability appendix."""
    payload = await _personal_report_package_traceability_payload(
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        db=db,
        user_id=user_id,
    )
    return PersonalReportPackageTraceabilityResponse(**payload)


@router.get("/package/annualized-income-schedule", response_model=AnnualizedIncomeScheduleResponse)
async def annualized_income_schedule(
    as_of_date: date | None = Query(default=None),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> AnnualizedIncomeScheduleResponse:
    """Return report-ready annualized income and restricted compensation schedule."""
    report_date = as_of_date or date.today()
    start_date = report_date - timedelta(days=365)
    income_result = await db.execute(
        select(JournalLine, Account)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date > start_date)
        .where(JournalEntry.entry_date <= report_date)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(Account.type == AccountType.INCOME)
    )

    totals = {
        "salary": Decimal("0.00"),
        "bonus": Decimal("0.00"),
        "dividend": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    currency = settings.base_currency.strip().upper()
    for line, account in income_result.all():
        signed_amount = line.amount if line.direction == Direction.CREDIT else -line.amount
        source_currency = (line.currency or account.currency or currency).strip().upper()
        try:
            signed_amount = await convert_amount(
                db,
                amount=signed_amount,
                currency=source_currency,
                target_currency=currency,
                rate_date=report_date,
                average_start=start_date,
                average_end=report_date,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise_bad_request(str(exc), cause=exc)
        bucket = income_bucket(account.name)
        if bucket:
            totals[bucket] += signed_amount
        totals["total"] += signed_amount

    restricted_types = (
        ManualValuationComponentType.ESOP,
        ManualValuationComponentType.RSU,
        ManualValuationComponentType.STOCK_OPTIONS,
    )
    restricted_result = await db.execute(
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.as_of_date <= report_date)
        .where(ManualValuationSnapshot.component_type.in_(restricted_types))
        .where(ManualValuationSnapshot.liquidity_class == ManualValuationLiquidityClass.RESTRICTED)
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )

    latest_holdings: dict[tuple[ManualValuationComponentType, str, str], ManualValuationSnapshot] = {}
    for snapshot in restricted_result.scalars().all():
        key = (snapshot.component_type, snapshot.source, snapshot.currency)
        latest_holdings.setdefault(key, snapshot)

    holdings: list[AnnualizedIncomeScheduleHolding] = []
    restricted_total = Decimal("0.00")
    for snapshot in latest_holdings.values():
        holdings.append(
            AnnualizedIncomeScheduleHolding(
                ticker=snapshot.source,
                compensation_type=snapshot.component_type.value,
                fair_value=snapshot.value.quantize(Decimal("0.01")),
                currency=snapshot.currency,
                valuation_basis="manual_valuation_snapshot",
                vesting_schedule=snapshot.notes,
                unlock_date=snapshot.reminder_date,
                liquidity_class=snapshot.liquidity_class.value,
                net_worth_treatment="excluded_from_liquid_net_worth_by_default",
            )
        )
        try:
            restricted_total += await convert_amount(
                db,
                amount=snapshot.value,
                currency=snapshot.currency,
                target_currency=currency,
                rate_date=report_date,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise_bad_request(str(exc), cause=exc)
    restricted_total = restricted_total.quantize(Decimal("0.01"))

    return AnnualizedIncomeScheduleResponse(
        section_id="annualized_income_long_term",
        label="Annualized Income & Long-Term Compensation",
        as_of_date=report_date,
        trailing_period_start=start_date,
        trailing_period_end=report_date,
        trailing_period_days=365,
        income=AnnualizedIncomeScheduleIncome(
            annualized_salary=totals["salary"].quantize(Decimal("0.01")),
            annualized_bonus=totals["bonus"].quantize(Decimal("0.01")),
            annualized_dividend=totals["dividend"].quantize(Decimal("0.01")),
            annualized_total=totals["total"].quantize(Decimal("0.01")),
            currency=currency,
            calculation_basis="posted_or_reconciled_income_journal_lines_trailing_12_months",
        ),
        restricted_holdings=holdings,
        restricted_fair_value_total=restricted_total,
        restricted_fair_value_total_currency=currency,
        net_worth_treatment=AnnualizedIncomeScheduleNetWorthTreatment(
            liquid_net_worth_default="exclude_restricted_holdings",
            restricted_wealth_basis="manual_valuation_snapshot_fair_value",
            include_restricted_query="/api/reports/balance-sheet?include_restricted=true",
            exclude_restricted_query="/api/reports/balance-sheet?include_restricted=false",
        ),
        notes=[
            "Personal management report only; not tax advice.",
            "Restricted holdings are excluded from liquid net worth by default.",
        ],
    )


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
async def balance_sheet(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=False),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> BalanceSheetResponse:
    """Get balance sheet as of date."""
    try:
        report_date = as_of_date or date.today()
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
        report = await generate_balance_sheet(
            db,
            user_id,
            as_of_date=report_date,
            currency=currency,
            include_restricted=include_restricted,
        )
    except ReportError as exc:
        logger.warning(
            "Balance sheet generation failed",
            as_of_date=str(as_of_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return BalanceSheetResponse(**report)


@router.get("/account-lineage", response_model=AccountLineageResponse)
async def account_lineage(
    account_id: UUID = Query(...),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> AccountLineageResponse:
    """List the journal lines contributing to one account's report balance.

    Powers Balance Sheet / Income Statement amount drill-down: each returned
    line carries a ``journal_line`` evidence anchor that the UI hands to
    ``GET /api/evidence/lineage`` to reach statement transactions and source
    documents.
    """
    report_date = as_of_date or date.today()
    try:
        report = await get_account_lineage(
            db,
            user_id,
            account_id,
            as_of_date=report_date,
            start_date=start_date,
            currency=currency,
        )
    except ReportError as exc:
        raise_not_found(f"Account {account_id}", cause=exc)
    return AccountLineageResponse(**report)


@router.get("/income-statement", response_model=IncomeStatementResponse)
async def income_statement(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    tags: list[str] | None = Query(default=None, alias="tags"),
    account_type: AccountType | None = Query(default=None, alias="account_type"),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> IncomeStatementResponse:
    """Get income statement for a period with optional filtering."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
        report = await generate_income_statement(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            tags=tags,
            account_type=account_type,
        )
    except ReportError as exc:
        logger.warning(
            "Income statement generation failed",
            start_date=str(start_date),
            end_date=str(end_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return IncomeStatementResponse(**report)


@router.get("/cash-flow", response_model=CashFlowResponse)
async def cash_flow(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> CashFlowResponse:
    """Get cash flow statement for a period."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
        report = await generate_cash_flow(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Cash flow generation failed",
            start_date=str(start_date),
            end_date=str(end_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return CashFlowResponse(**report)


@router.get("/trend", response_model=AccountTrendResponse)
async def account_trend(
    account_id: UUID = Query(...),
    period: TrendPeriod = Query(default=TrendPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> AccountTrendResponse:
    """Get account trend data."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=date.today())
        report = await get_account_trend(
            db,
            user_id,
            account_id=account_id,
            period=period.value,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Account trend generation failed",
            account_id=str(account_id),
            period=period.value,
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return AccountTrendResponse(**report)


@router.get("/net-worth/timeseries", response_model=NetWorthTimeSeriesResponse)
async def net_worth_timeseries(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    granularity: NetWorthGranularity = Query(default=NetWorthGranularity.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> NetWorthTimeSeriesResponse:
    """Get daily or monthly net worth time-series."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=to_date)
        report = await get_net_worth_timeseries(
            db,
            user_id,
            start_date=from_date,
            end_date=to_date,
            granularity=granularity.value,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Net worth time-series generation failed",
            from_date=str(from_date),
            to_date=str(to_date),
            granularity=granularity.value,
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return NetWorthTimeSeriesResponse(**report)


@router.get("/breakdown", response_model=CategoryBreakdownResponse)
async def category_breakdown(
    breakdown_type: BreakdownType = Query(..., alias="type"),
    period: BreakdownPeriod = Query(default=BreakdownPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> CategoryBreakdownResponse:
    """Get income or expense category breakdown."""
    account_type = AccountType.INCOME if breakdown_type == BreakdownType.INCOME else AccountType.EXPENSE
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=date.today())
        report = await get_category_breakdown(
            db,
            user_id,
            breakdown_type=account_type,
            period=period.value,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Category breakdown generation failed",
            breakdown_type=breakdown_type.value,
            period=period.value,
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return CategoryBreakdownResponse(**report)


@router.get("/export")
async def export_report(
    report_type: ReportType = Query(...),
    format: ExportFormat = Query(default=ExportFormat.CSV),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=False),
    framework_id: PersonalReportingFrameworkId | None = Query(default=None),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> StreamingResponse:
    """Export reports in CSV format."""
    output = StringIO()
    writer = csv.writer(output)

    try:
        if report_type == ReportType.BALANCE_SHEET:
            report_date = as_of_date or date.today()
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
            report = await generate_balance_sheet(
                db,
                user_id,
                as_of_date=report_date,
                currency=currency,
                include_restricted=include_restricted,
            )
            writer.writerow(["section", "account", "amount", "currency"])
            for section, lines in (
                ("Assets", report["assets"]),
                ("Liabilities", report["liabilities"]),
                ("Equity", report["equity"]),
            ):
                for line in lines:
                    writer.writerow([section, line["name"], line["amount"], report["currency"]])
            writer.writerow(["Total Assets", "", report["total_assets"], report["currency"]])
            writer.writerow(["Total Liabilities", "", report["total_liabilities"], report["currency"]])
            writer.writerow(["Total Equity", "", report["total_equity"], report["currency"]])
            filename = f"balance-sheet-{report['as_of_date']}.csv"
        elif report_type == ReportType.INCOME_STATEMENT:
            if not start_date or not end_date:
                raise_bad_request("start_date and end_date are required for income statement export")
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
            report = await generate_income_statement(
                db,
                user_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
            writer.writerow(["section", "account", "amount", "currency"])
            for section, lines in (("Income", report["income"]), ("Expenses", report["expenses"])):
                for line in lines:
                    writer.writerow([section, line["name"], line["amount"], report["currency"]])
            writer.writerow(["Total Income", "", report["total_income"], report["currency"]])
            writer.writerow(["Total Expenses", "", report["total_expenses"], report["currency"]])
            writer.writerow(["Net Income", "", report["net_income"], report["currency"]])
            filename = f"income-statement-{start_date}-to-{end_date}.csv"
        elif report_type == ReportType.CASH_FLOW:
            if not start_date or not end_date:
                raise_bad_request("start_date and end_date are required for cash flow export")
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
            report = await generate_cash_flow(
                db,
                user_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
            writer.writerow(["section", "account", "amount", "currency", "description"])
            for section, lines in (
                ("Operating", report["operating"]),
                ("Investing", report["investing"]),
                ("Financing", report["financing"]),
            ):
                for line in lines:
                    writer.writerow(
                        [
                            section,
                            line["subcategory"],
                            line["amount"],
                            report["currency"],
                            line.get("description") or "",
                        ]
                    )
            summary = report["summary"]
            writer.writerow(["Operating Activities", "", summary["operating_activities"], report["currency"], ""])
            writer.writerow(["Investing Activities", "", summary["investing_activities"], report["currency"], ""])
            writer.writerow(["Financing Activities", "", summary["financing_activities"], report["currency"], ""])
            writer.writerow(["Net Cash Flow", "", summary["net_cash_flow"], report["currency"], ""])
            writer.writerow(["Beginning Cash", "", summary["beginning_cash"], report["currency"], ""])
            writer.writerow(["Ending Cash", "", summary["ending_cash"], report["currency"], ""])
            filename = f"cash-flow-{start_date}-to-{end_date}.csv"
        elif report_type == ReportType.PACKAGE:
            selected_framework = framework_id or PersonalReportingFrameworkId.US_GAAP_LIKE
            contract = personal_report_package_contract(selected_framework)
            policy = await personal_report_package_framework_policy(
                framework_id=selected_framework,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                db=db,
                user_id=user_id,
            )
            traceability = await personal_report_package_traceability(
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                db=db,
                user_id=user_id,
            )
            writer.writerow(contract.export_contract.csv_columns)
            evidence_references = sorted(
                {
                    f"{anchor.anchor_type}:{anchor.source_id}"
                    for decision in policy.decisions
                    for anchor in decision.evidence_anchors
                }
                | {f"{anchor.anchor_type}:{anchor.source_id}" for gap in policy.gaps for anchor in gap.evidence_anchors}
            )
            evidence_bundle_references = "|".join(evidence_references)
            for line in traceability.lines:
                writer.writerow(
                    [
                        contract.package_id,
                        line.section_id,
                        line.line_id,
                        line.label,
                        "",
                        currency or settings.base_currency,
                        line.source_state,
                        selected_framework.value,
                        policy.result_id,
                        policy.matrix_version,
                        evidence_bundle_references,
                    ]
                )
            filename = f"personal-report-package-{selected_framework.value}.csv"
        else:  # pragma: no cover - FastAPI enum validation rejects unsupported values first.
            raise_bad_request("Unsupported report type")
    except ReportError as exc:
        logger.warning(
            "Report export failed",
            report_type=report_type.value,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)

    await db.commit()
    content = output.getvalue()
    output.close()
    return StreamingResponse(
        StringIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{report_type}/snapshots")
async def list_report_snapshots(
    report_type: str,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> list[dict]:
    """List available report snapshots for a given report type.

    AC18.4.2: ReportSnapshot (Layer 4) is queryable via API.
    """
    from sqlalchemy import select as sa_select

    from src.models.layer4 import ReportSnapshot

    stmt = (
        sa_select(ReportSnapshot)
        .where(ReportSnapshot.report_type == report_type)
        .where(ReportSnapshot.user_id == user_id)
        .order_by(ReportSnapshot.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    snapshots = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "report_type": s.report_type.value if hasattr(s.report_type, "value") else str(s.report_type),
            "as_of_date": s.as_of_date.isoformat() if s.as_of_date else None,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "rule_version_id": str(s.rule_version_id),
            "is_latest": s.is_latest,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]
