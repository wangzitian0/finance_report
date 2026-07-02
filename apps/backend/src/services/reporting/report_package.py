"""Static contract/notes/traceability data for the personal report package.

Pure data extracted from the reports router (no behavior): the canonical
package section contract, disclosure notes, and traceability appendix
template. Kept separate so the router stays a thin HTTP layer.
"""

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
