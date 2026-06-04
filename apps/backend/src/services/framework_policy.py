"""Deterministic framework policy matrix for personal reports."""

from __future__ import annotations

from datetime import date

from src.schemas.reporting import (
    FrameworkPolicyDecision,
    FrameworkPolicyFact,
    FrameworkPolicyGap,
    FrameworkPolicyMatrix,
    FrameworkPolicyMatrixRule,
    FrameworkPolicyResult,
    PersonalReportingFrameworkId,
    PolicyDimension,
    PolicyFactDomain,
)

_REQUIRED_STATEMENTS = [
    "balance_sheet",
    "income_statement",
    "cash_flow",
    "notes",
    "traceability_appendix",
]


def _policy(
    *,
    recognition: str,
    measurement: str,
    classification: str,
    presentation: str,
    disclosure: str,
) -> dict[PolicyDimension, str]:
    return {
        PolicyDimension.RECOGNITION: recognition,
        PolicyDimension.MEASUREMENT: measurement,
        PolicyDimension.CLASSIFICATION: classification,
        PolicyDimension.PRESENTATION: presentation,
        PolicyDimension.DISCLOSURE: disclosure,
    }


def _rule(
    *,
    domain: PolicyFactDomain,
    supported_instrument_types: list[str],
    recognition: str,
    measurement: str,
    classification: str,
    presentation: str,
    disclosure: str,
    line_mappings: dict[str, str],
    required_evidence: list[str] | None = None,
    disclosure_requirements: list[str] | None = None,
    blocker_conditions: list[str] | None = None,
) -> FrameworkPolicyMatrixRule:
    return FrameworkPolicyMatrixRule(
        domain=domain,
        supported_instrument_types=supported_instrument_types,
        policy_by_dimension=_policy(
            recognition=recognition,
            measurement=measurement,
            classification=classification,
            presentation=presentation,
            disclosure=disclosure,
        ),
        line_mappings=line_mappings,
        required_evidence=required_evidence or ["source_anchor", "ledger_or_portfolio_anchor", "review_state"],
        disclosure_requirements=disclosure_requirements or ["basis", "source_coverage", "valuation_or_cutoff"],
        blocker_conditions=blocker_conditions
        or [
            "missing_source_anchor",
            "pending_review",
            "missing_measurement_basis",
        ],
    )


def _common_rules(framework_label: str) -> list[FrameworkPolicyMatrixRule]:
    return [
        _rule(
            domain=PolicyFactDomain.CASH,
            supported_instrument_types=["bank_account", "cash", "deposit", "fixture"],
            recognition="Recognize cash movements on transaction date after source cutoff validation.",
            measurement="Measure cash at nominal amount; translate non-reporting currencies using transaction or period-end FX rules.",
            classification="Cash and bank account asset.",
            presentation=f"{framework_label} balance sheet cash and cash equivalents.",
            disclosure="Disclose source coverage, cutoff, currency, and unresolved bank statement gaps.",
            line_mappings={"balance_sheet": "assets.cash_and_cash_equivalents", "cash_flow": "cash.ending_cash"},
        ),
        _rule(
            domain=PolicyFactDomain.FUND,
            supported_instrument_types=["fund", "money_market_fund", "etf_fund", "fixture"],
            recognition="Recognize fund holdings when brokerage or custodian evidence confirms ownership.",
            measurement="Measure at observable fund NAV or quoted fair value when freshness evidence exists.",
            classification="Investment asset, classified by liquidity and redemption terms.",
            presentation=f"{framework_label} investment schedule fund line.",
            disclosure="Disclose valuation source, price date, liquidity terms, and stale NAV blockers.",
            line_mappings={"balance_sheet": "assets.investments.funds", "notes": "notes.fund_liquidity"},
        ),
        _rule(
            domain=PolicyFactDomain.DIVIDEND_INTEREST,
            supported_instrument_types=["dividend", "interest", "coupon", "fixture"],
            recognition="Recognize dividends and interest on entitlement, ex-date, payment date, or statement date per source evidence.",
            measurement="Measure gross and net cash amounts separately when withholding evidence exists.",
            classification="Investment or bank income.",
            presentation=f"{framework_label} income statement dividend and interest income.",
            disclosure="Disclose withholding, tax-note hooks, and source date used for recognition.",
            line_mappings={"income_statement": "income.dividends_and_interest", "notes": "notes.tax_hooks"},
        ),
        _rule(
            domain=PolicyFactDomain.BROKERAGE_FEE,
            supported_instrument_types=["commission", "brokerage_fee", "platform_fee", "fixture"],
            recognition="Recognize brokerage fees when the trade or broker statement evidence is available.",
            measurement="Measure fees at settled cash amount and preserve currency/FX treatment.",
            classification="Cost basis adjustment or investment expense according to linked transaction type.",
            presentation=f"{framework_label} cash-flow and investment performance fee lines.",
            disclosure="Disclose whether fees affect cost basis or period expense.",
            line_mappings={"income_statement": "expenses.investment_fees", "cash_flow": "investing.fees"},
        ),
        _rule(
            domain=PolicyFactDomain.FX,
            supported_instrument_types=["fx_transaction", "fx_rate", "currency_translation", "fixture"],
            recognition="Recognize FX effects when source currency differs from report currency.",
            measurement="Use transaction-date rates for transactions, average rates for period income where configured, and period-end rates for balances.",
            classification="FX gain/loss, translation adjustment, or disclosure-only rate effect.",
            presentation=f"{framework_label} FX line mapping by statement type.",
            disclosure="Disclose rate source, rate date, missing-rate blockers, and stale-rate fallback.",
            line_mappings={"income_statement": "income.fx_gain_loss", "balance_sheet": "equity.fx_translation"},
        ),
        _rule(
            domain=PolicyFactDomain.RESTRICTED_COMPENSATION,
            supported_instrument_types=["rsu", "esop", "stock_option", "restricted_share", "fixture"],
            recognition="Recognize restricted compensation when grant, vesting, or exercise evidence exists.",
            measurement="Measure at accepted fair-value input with explicit restriction and liquidity treatment.",
            classification="Restricted wealth or compensation schedule item, not default liquid net worth.",
            presentation=f"{framework_label} long-term compensation schedule.",
            disclosure="Disclose vesting, restriction, liquidity class, valuation date, and manual valuation review.",
            line_mappings={
                "balance_sheet": "assets.restricted_compensation",
                "notes": "notes.restricted_asset_treatment",
            },
        ),
        _rule(
            domain=PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE,
            supported_instrument_types=["property", "mortgage", "private_asset", "manual_asset", "fixture"],
            recognition="Recognize manual property, mortgage, and private assets only with explicit source date and owner review.",
            measurement="Measure using accepted manual valuation basis; block trusted totals when basis is missing.",
            classification="Manual asset, private asset, or secured liability.",
            presentation=f"{framework_label} manual valuation and liability schedule.",
            disclosure="Disclose valuation basis, confidence tier, source date, and trusted-total blocker state.",
            line_mappings={"balance_sheet": "assets.manual_private_assets", "notes": "notes.manual_valuation_basis"},
        ),
        _rule(
            domain=PolicyFactDomain.LIABILITY,
            supported_instrument_types=["loan", "credit_card", "mortgage_liability", "payable", "fixture"],
            recognition="Recognize liabilities from statement, loan, or manual obligation evidence.",
            measurement="Measure at outstanding principal or statement balance with FX translation when needed.",
            classification="Current or long-term liability by due date and instrument type.",
            presentation=f"{framework_label} balance sheet liability line.",
            disclosure="Disclose source balance date, interest hooks, and unresolved liability coverage gaps.",
            line_mappings={"balance_sheet": "liabilities.financial_liabilities", "notes": "notes.liability_coverage"},
        ),
        _rule(
            domain=PolicyFactDomain.TRANSFER,
            supported_instrument_types=["internal_transfer", "broker_transfer", "cash_transfer", "fixture"],
            recognition="Recognize transfers when both legs or explicit pending Processing evidence exist.",
            measurement="Measure transfer legs at source cash amounts and FX translated report-currency equivalents.",
            classification="Internal movement, not income or expense.",
            presentation=f"{framework_label} cash-flow transfer reconciliation.",
            disclosure="Disclose unmatched or in-transit transfer blockers.",
            line_mappings={"cash_flow": "cash.internal_transfers", "notes": "notes.transfer_matching"},
        ),
        _rule(
            domain=PolicyFactDomain.TAX_NOTE,
            supported_instrument_types=["withholding_tax", "tax_note", "tax_relevant_item", "fixture"],
            recognition="Preserve tax-relevant evidence as notes unless a deterministic ledger posting exists.",
            measurement="Measure withheld or tax-relevant amounts from source evidence without estimating tax filings.",
            classification="Disclosure hook, withholding line, or tax-note appendix.",
            presentation=f"{framework_label} notes and tax-hook disclosure.",
            disclosure="Disclose that the package is not tax advice or a tax filing.",
            line_mappings={"notes": "notes.tax_relevant_items"},
        ),
    ]


def get_framework_policy_matrix(framework_id: PersonalReportingFrameworkId) -> FrameworkPolicyMatrix:
    """Return the deterministic v1 policy matrix for a supported framework."""
    if framework_id == PersonalReportingFrameworkId.US_GAAP_LIKE:
        listed_security = _rule(
            domain=PolicyFactDomain.LISTED_SECURITY,
            supported_instrument_types=["listed_equity", "listed_security", "etf", "fixture"],
            recognition="Recognize listed securities when brokerage evidence confirms trade or holding ownership.",
            measurement="Measure at quoted fair value when market data is fresh; preserve cost basis and unrealized gain evidence.",
            classification="Marketable investment asset.",
            presentation="US-like balance sheet marketable securities with unrealized gain note discipline.",
            disclosure="Disclose price source, stale price blocker, cost basis, and unrealized gain presentation.",
            line_mappings={
                "balance_sheet": "assets.marketable_securities",
                "income_statement": "income.unrealized_investment_gain_loss",
                "notes": "notes.us_like_market_price_basis",
            },
        )
    else:
        listed_security = _rule(
            domain=PolicyFactDomain.LISTED_SECURITY,
            supported_instrument_types=["listed_equity", "listed_security", "etf", "fixture"],
            recognition="Recognize listed securities when brokerage evidence confirms trade or holding ownership.",
            measurement="Measure at quoted fair value when market data is fresh; preserve cost basis and fair-value movement evidence.",
            classification="Financial asset measured with HK-like fair-value presentation.",
            presentation="HK-like balance sheet financial assets at fair value with investment revaluation note discipline.",
            disclosure="Disclose price source, stale price blocker, fair-value hierarchy hint, and revaluation presentation.",
            line_mappings={
                "balance_sheet": "assets.financial_assets_at_fair_value",
                "income_statement": "income.fair_value_change_in_financial_assets",
                "notes": "notes.hk_like_fair_value_basis",
            },
        )

    rules = [
        listed_security,
        *_common_rules("US-like" if framework_id == PersonalReportingFrameworkId.US_GAAP_LIKE else "HK-like"),
    ]
    return FrameworkPolicyMatrix(framework_id=framework_id, version="1.0", rules=rules)


def _find_rule(matrix: FrameworkPolicyMatrix, fact: FrameworkPolicyFact) -> FrameworkPolicyMatrixRule | None:
    if fact.domain == PolicyFactDomain.UNSUPPORTED:
        return None
    for rule in matrix.rules:
        if rule.domain != fact.domain:
            continue
        if fact.instrument_type in rule.supported_instrument_types:
            return rule
    return None


def _gap_for_fact(fact: FrameworkPolicyFact) -> FrameworkPolicyGap:
    return FrameworkPolicyGap(
        code="unsupported_policy_domain",
        fact_id=fact.fact_id,
        domain=fact.domain,
        instrument_type=fact.instrument_type,
        blocker=True,
        reason="No deterministic v1 framework policy rule exists for this fact domain and instrument type.",
        remediation="Add an explicit policy rule, accepted manual valuation basis, or reviewed structured policy field before trusted output.",
        evidence_anchors=fact.anchors,
    )


def derive_framework_policy_result(
    framework_id: PersonalReportingFrameworkId,
    *,
    report_period_start: date,
    report_period_end: date,
    facts: list[FrameworkPolicyFact],
) -> FrameworkPolicyResult:
    """Derive a read-only framework policy result from framework-neutral facts."""
    matrix = get_framework_policy_matrix(framework_id)
    decisions: list[FrameworkPolicyDecision] = []
    gaps: list[FrameworkPolicyGap] = []

    for fact in facts:
        rule = _find_rule(matrix, fact)
        if rule is None:
            gaps.append(_gap_for_fact(fact))
            continue

        decisions.append(
            FrameworkPolicyDecision(
                domain=fact.domain,
                recognition=rule.policy_by_dimension[PolicyDimension.RECOGNITION],
                measurement=rule.policy_by_dimension[PolicyDimension.MEASUREMENT],
                classification=rule.policy_by_dimension[PolicyDimension.CLASSIFICATION],
                presentation=rule.policy_by_dimension[PolicyDimension.PRESENTATION],
                disclosure=rule.policy_by_dimension[PolicyDimension.DISCLOSURE],
                line_mappings=rule.line_mappings,
                evidence_anchors=fact.anchors,
                accepted_value=rule.domain.value,
            )
        )

    return FrameworkPolicyResult(
        framework_id=framework_id,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        generated_at=report_period_end,
        required_statements=_REQUIRED_STATEMENTS,
        decisions=decisions,
        gaps=gaps,
    )
