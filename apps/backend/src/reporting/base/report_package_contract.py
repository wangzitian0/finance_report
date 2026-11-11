"""Static contract/notes/traceability data for the personal report package."""

from __future__ import annotations

from typing import Any


def _sec(
    section_id: str,
    label: str,
    owner_epic: str,
    period_type: str,
    fields: list[str],
    *,
    has_blocking: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "section_id": section_id,
        "label": label,
        "owner_epic": owner_epic,
        "period_type": period_type,
        "status": "ready",
    }
    if has_blocking:
        row["blocking_issue"] = None
    row["decimal_total_fields"] = fields
    return row


def _note(
    note_id: str,
    label: str,
    owner_epic: str,
    basis: str,
    source_state: str,
    applies_to_sections: list[str],
    disclosure: str,
) -> dict[str, Any]:
    return {
        "note_id": note_id,
        "label": label,
        "owner_epic": owner_epic,
        "basis": basis,
        "source_state": source_state,
        "applies_to_sections": applies_to_sections,
        "disclosure": disclosure,
    }


def _line(
    line_id: str,
    section_id: str,
    label: str,
    amount_field: str | None,
    currency_field: str | None,
    source_state: str,
    source_types: list[str],
    source_id_fields: list[str],
    *,
    ledger_id_fields: list[str] | None = None,
    unavailable_reason: str | None = None,
    blocker_codes: list[str] | None = None,
) -> dict[str, Any]:
    ledger_anchor: dict[str, Any] = (
        {
            "state": "not_applicable",
            "entry_statuses": [],
            "identifier_fields": [],
            "unavailable_reason": unavailable_reason,
        }
        if unavailable_reason is not None
        else {
            "state": "available",
            "entry_statuses": ["posted", "reconciled"],
            "identifier_fields": ledger_id_fields or ["journal_entry_ids", "journal_line_ids"],
        }
    )
    return {
        "line_id": line_id,
        "section_id": section_id,
        "label": label,
        "amount_field": amount_field,
        "currency_field": currency_field,
        "source_state": source_state,
        "source_anchor": {
            "state": "available",
            "source_types": source_types,
            "identifier_fields": source_id_fields,
        },
        "ledger_anchor": ledger_anchor,
        "anchor_count": 0,
        "blocker_codes": blocker_codes or [],
    }


def _warn(code: str, label: str, sections: list[str], state: str, remediation: str) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "applies_to_sections": sections,
        "state": state,
        "remediation": remediation,
    }


_ALL_FIN_SECTIONS = [
    "balance_sheet",
    "income_statement",
    "cash_flow",
    "investment_performance",
    "annualized_income_long_term",
]
_BANK_MANUAL = ["bank_statement", "manual_journal_entry"]
_TXN_SRC_IDS = ["statement_transaction_ids", "journal_entry_source_ids"]

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
    "supported_frameworks": ["personal_us_gaap_like", "personal_hkfrs_like"],
    "selected_framework_id": None,
    "sections": [
        _sec(
            "balance_sheet",
            "Balance Sheet",
            "EPIC-005",
            "as_of",
            ["total_assets", "total_liabilities", "total_equity", "equation_delta"],
        ),
        _sec(
            "income_statement",
            "Income Statement",
            "EPIC-005",
            "period",
            ["total_income", "total_expenses", "net_income"],
        ),
        _sec(
            "cash_flow",
            "Cash Flow",
            "EPIC-005",
            "period",
            [
                "operating_activities",
                "investing_activities",
                "financing_activities",
                "net_cash_flow",
                "beginning_cash",
                "ending_cash",
            ],
        ),
        _sec(
            "investment_performance",
            "Investment Performance",
            "EPIC-017",
            "period_and_as_of",
            [
                "xirr",
                "time_weighted_return",
                "money_weighted_return",
                "realized_pnl",
                "unrealized_pnl",
                "dividend_income",
            ],
        ),
        _sec(
            "annualized_income_long_term",
            "Annualized Income & Long-Term Compensation",
            "EPIC-011",
            "trailing_12_months_and_as_of",
            [
                "annualized_salary",
                "annualized_bonus",
                "annualized_dividend",
                "annualized_total",
                "restricted_fair_value",
            ],
            has_blocking=True,
        ),
        _sec("notes", "Notes & Disclosures", "EPIC-005", "package", [], has_blocking=True),
        _sec("traceability_appendix", "Traceability Appendix", "EPIC-018", "package", [], has_blocking=True),
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
            "input_decision_references",
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
        _note(
            "basis-of-preparation",
            "Basis of Preparation",
            "EPIC-005",
            "personal_management_report_package_contract",
            "package_contract",
            _ALL_FIN_SECTIONS,
            "The package assembles personal finance statements and schedules for management use. "
            "It does not assert compliance with a statutory accounting framework.",
        ),
        _note(
            "reporting-period-and-currency",
            "Reporting Period and Currency",
            "EPIC-005",
            "package_period_semantics",
            "request_parameters",
            _ALL_FIN_SECTIONS,
            "Period sections use start and end dates; point-in-time sections use as-of dates. "
            "Currency values serialize Decimal amounts as strings.",
        ),
        _note(
            "valuation-basis",
            "Valuation Basis",
            "EPIC-011",
            "manual_valuation_component_rules",
            "manual_valuation_snapshots",
            ["balance_sheet", "annualized_income_long_term"],
            "Manual valuation snapshots supply property, liability, and restricted compensation "
            "values as of the selected reporting date.",
        ),
        _note(
            "investment-market-data",
            "Investment Market Data",
            "EPIC-017",
            "investment_performance_schedule",
            "brokerage_imports_and_market_data",
            ["investment_performance", "balance_sheet"],
            "Portfolio metrics depend on imported brokerage positions, available prices, "
            "dividend facts, and the schedule data-freshness flags.",
        ),
        _note(
            "source-confidence-review",
            "Source Confidence and Review",
            "EPIC-018",
            "trusted_or_reviewed_source_state",
            "reviewed_journal_and_statement_links",
            ["balance_sheet", "income_statement", "cash_flow"],
            "Report totals depend on posted or reconciled journal entries and reviewed source "
            "documents; unresolved extraction or reconciliation checks remain outside trusted totals.",
        ),
        _note(
            "restricted-asset-treatment",
            "Restricted Asset Treatment",
            "EPIC-011",
            "restricted_compensation_liquidity_policy",
            "manual_valuation_snapshots",
            ["balance_sheet", "annualized_income_long_term"],
            "Restricted ESOP, RSU, and stock option values are excluded from liquid net worth by "
            "default and shown separately in the long-term compensation schedule.",
        ),
    ],
}

PERSONAL_REPORT_PACKAGE_TRACEABILITY: dict = {
    "section_id": "traceability_appendix",
    "label": "Traceability Appendix",
    "status": "ready",
    "lines": [
        _line(
            "balance_sheet.total_assets",
            "balance_sheet",
            "Total Assets",
            "total_assets",
            "currency",
            "posted_reconciled_journal_lines_and_manual_valuations",
            ["bank_statement", "brokerage_import", "manual_valuation_snapshot"],
            ["statement_transaction_ids", "brokerage_statement_ids", "manual_valuation_snapshot_ids"],
        ),
        _line(
            "income_statement.total_income",
            "income_statement",
            "Total Income",
            "total_income",
            "currency",
            "posted_reconciled_income_journal_lines",
            _BANK_MANUAL,
            _TXN_SRC_IDS,
        ),
        _line(
            "income_statement.total_expenses",
            "income_statement",
            "Total Expenses",
            "total_expenses",
            "currency",
            "posted_reconciled_expense_journal_lines",
            _BANK_MANUAL,
            _TXN_SRC_IDS,
        ),
        _line(
            "cash_flow.net_cash_flow",
            "cash_flow",
            "Net Cash Flow",
            "summary.net_cash_flow",
            "currency",
            "cash_bank_journal_lines",
            _BANK_MANUAL,
            _TXN_SRC_IDS,
        ),
        _line(
            "investment_performance.market_value",
            "investment_performance",
            "Investment Market Value",
            "holdings.market_value",
            "currency",
            "brokerage_imports_market_data_and_ledger_cost_basis",
            ["brokerage_import", "market_data_price", "journal_entry"],
            ["brokerage_statement_ids", "price_source_ids", "ledger_entry_ids"],
            ledger_id_fields=["ledger_entry_ids", "journal_line_ids"],
            blocker_codes=["stale_market_data"],
        ),
        _line(
            "annualized_income_long_term.annualized_total",
            "annualized_income_long_term",
            "Annualized Total Income",
            "income.annualized_total",
            "income.currency",
            "posted_reconciled_income_journal_lines_trailing_12_months",
            _BANK_MANUAL,
            ["journal_entry_source_ids", "statement_transaction_ids"],
        ),
        _line(
            "annualized_income_long_term.restricted_fair_value_total",
            "annualized_income_long_term",
            "Restricted Fair Value Total",
            "restricted_fair_value_total",
            "restricted_fair_value_total_currency",
            "manual_valuation_snapshots",
            ["manual_valuation_snapshot"],
            ["manual_valuation_snapshot_ids"],
            unavailable_reason="Restricted compensation is disclosed as explicit manual valuation input, not posted ledger cash.",
            blocker_codes=["manual_only_source"],
        ),
        _line(
            "notes.non_compliance_statement",
            "notes",
            "Package Non-Compliance Statement",
            None,
            None,
            "package_contract",
            ["package_contract"],
            ["note_id"],
            unavailable_reason="Disclosure wording is not a ledger-derived amount.",
        ),
    ],
    "completeness_warnings": [
        _warn(
            "missing_source_anchor",
            "Missing source anchor",
            ["balance_sheet", "income_statement", "cash_flow"],
            "fail_package_proof_for_trusted_totals",
            "Expose statement transaction, document, or explicit manual-input identifiers before treating totals as trusted.",
        ),
        _warn(
            "manual_only_source",
            "Manual-only source coverage",
            ["balance_sheet", "annualized_income_long_term"],
            "explicit_manual_input_required",
            "Keep manual valuation snapshot identifiers and valuation basis visible in the appendix.",
        ),
        _warn(
            "stale_market_data",
            "Stale market data",
            ["investment_performance", "balance_sheet"],
            "disclose_stale_or_refresh_required",
            "Use schedule freshness flags and refresh market data when provider prices are stale.",
        ),
        _warn(
            "duplicate_source_coverage",
            "Duplicate source coverage",
            ["balance_sheet", "cash_flow"],
            "exclude_or_disclose_duplicate_source",
            "Preserve duplicate detection and reconciliation state so the same source is not counted twice.",
        ),
        _warn(
            "overlapping_statement_period",
            "Overlapping statement period",
            ["income_statement", "cash_flow"],
            "review_required_before_trusted_total",
            "Surface overlapping bank statement periods and keep affected totals out of trusted proof until reviewed.",
        ),
    ],
}
