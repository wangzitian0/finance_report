"""Deterministic framework policy matrix for personal reports."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import ManualValuationComponentType, ManualValuationSnapshot
from src.models.market_data import StockPrice
from src.models.portfolio import DividendIncome, MarketDataOverride
from src.schemas.reporting import (
    FrameworkPolicyDecision,
    FrameworkPolicyEvidenceAnchor,
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
        required_evidence=(
            ["source_anchor", "ledger_or_portfolio_anchor", "review_state"]
            if required_evidence is None
            else required_evidence
        ),
        disclosure_requirements=(
            ["basis", "source_coverage", "valuation_or_cutoff"]
            if disclosure_requirements is None
            else disclosure_requirements
        ),
        blocker_conditions=blocker_conditions
        if blocker_conditions is not None
        else [
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
            recognition="Recognize transfers when both legs or explicit pending processing evidence exist.",
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
            supported_instrument_types=["listed_equity", "listed_security", "etf", "bond", "fixture"],
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
            supported_instrument_types=["listed_equity", "listed_security", "etf", "bond", "fixture"],
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


def _result_id(
    framework_id: PersonalReportingFrameworkId,
    *,
    matrix_version: str,
    report_period_start: date,
    report_period_end: date,
    decisions: list[FrameworkPolicyDecision],
    gaps: list[FrameworkPolicyGap],
) -> str:
    decision_payloads = [decision.model_dump(mode="json") for decision in decisions]
    gap_payloads = [gap.model_dump(mode="json") for gap in gaps]
    payload = json.dumps(
        {
            "framework_id": framework_id.value,
            "matrix_version": matrix_version,
            "report_period_start": report_period_start.isoformat(),
            "report_period_end": report_period_end.isoformat(),
            "decisions": sorted(
                decision_payloads,
                key=lambda decision: json.dumps(decision, sort_keys=True, separators=(",", ":")),
            ),
            "gaps": sorted(gap_payloads, key=lambda gap: json.dumps(gap, sort_keys=True, separators=(",", ":"))),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return (
        f"policy-result:{framework_id.value}:{report_period_start.isoformat()}:{report_period_end.isoformat()}:{digest}"
    )


def _anchor(
    *,
    anchor_type: str,
    source_system: str,
    source_id: object,
    description: str | None = None,
) -> FrameworkPolicyEvidenceAnchor:
    return FrameworkPolicyEvidenceAnchor(
        anchor_id=f"{anchor_type}:{source_id}",
        anchor_type=anchor_type,
        source_system=source_system,
        source_id=str(source_id),
        description=description,
    )


def _position_domain_and_instrument(position: AtomicPosition) -> tuple[PolicyFactDomain, str]:
    if position.asset_type == AssetType.STOCK:
        return PolicyFactDomain.LISTED_SECURITY, "listed_equity"
    if position.asset_type == AssetType.ETF:
        return PolicyFactDomain.LISTED_SECURITY, "etf"
    if position.asset_type == AssetType.MUTUAL_FUND:
        return PolicyFactDomain.FUND, "fund"
    if position.asset_type == AssetType.CASH:
        return PolicyFactDomain.CASH, "cash"
    if position.asset_type == AssetType.PROPERTY:
        return PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "property"
    if position.asset_type == AssetType.BOND:
        # A bond is a marketable financial asset -> the listed-security line.
        return PolicyFactDomain.LISTED_SECURITY, "bond"
    if position.asset_type == AssetType.OTHER:
        # An unclassified *position* (brokerage evidence) lands in the private-asset
        # line; "private_asset" (not "manual_asset", which implies manual-valuation
        # provenance) keeps the instrument type's source semantics honest.
        return PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "private_asset"
    return (
        PolicyFactDomain.UNSUPPORTED,
        position.asset_type.value if position.asset_type is not None else "unknown_asset",
    )


def _manual_domain_and_instrument(snapshot: ManualValuationSnapshot) -> tuple[PolicyFactDomain, str]:
    restricted_component_instruments = {
        ManualValuationComponentType.ESOP: "esop",
        ManualValuationComponentType.RSU: "rsu",
        ManualValuationComponentType.STOCK_OPTIONS: "stock_option",
    }
    liability_component_instruments = {
        ManualValuationComponentType.MORTGAGE_BALANCE: "mortgage_liability",
        ManualValuationComponentType.TAX_PAYABLE: "payable",
        ManualValuationComponentType.OTHER_LIABILITY: "loan",
    }
    manual_asset_component_instruments = {
        ManualValuationComponentType.PROPERTY_VALUE: "property",
        ManualValuationComponentType.CPF_BALANCE: "manual_asset",
        ManualValuationComponentType.RETIREMENT_ACCOUNT: "manual_asset",
        ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT: "manual_asset",
        ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET: "manual_asset",
        ManualValuationComponentType.LONG_TERM_SAVINGS: "manual_asset",
        ManualValuationComponentType.TAX_REFUND: "manual_asset",
        ManualValuationComponentType.INSURANCE_CASH_VALUE: "manual_asset",
        ManualValuationComponentType.OTHER_ASSET: "manual_asset",
    }
    if snapshot.component_type in restricted_component_instruments:
        return PolicyFactDomain.RESTRICTED_COMPENSATION, restricted_component_instruments[snapshot.component_type]
    if snapshot.component_type in liability_component_instruments:
        return PolicyFactDomain.LIABILITY, liability_component_instruments[snapshot.component_type]
    return (
        PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE,
        manual_asset_component_instruments.get(snapshot.component_type, "manual_asset"),
    )


def _account_domain_and_instrument(account: Account) -> tuple[PolicyFactDomain, str] | None:
    if account.type == AccountType.ASSET:
        return PolicyFactDomain.CASH, "bank_account"
    if account.type == AccountType.LIABILITY:
        return PolicyFactDomain.LIABILITY, "loan"
    if account.type == AccountType.INCOME:
        return PolicyFactDomain.DIVIDEND_INTEREST, "interest"
    if account.type == AccountType.EXPENSE:
        return PolicyFactDomain.BROKERAGE_FEE, "brokerage_fee"
    return None


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

        line_mappings = dict(rule.line_mappings)
        if fact.domain == PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE and fact.instrument_type == "property":
            if framework_id == PersonalReportingFrameworkId.HKFRS_LIKE and fact.holding_intent == "investment":
                line_mappings["balance_sheet"] = "assets.investment_property"

        decisions.append(
            FrameworkPolicyDecision(
                domain=fact.domain,
                recognition=rule.policy_by_dimension[PolicyDimension.RECOGNITION],
                measurement=rule.policy_by_dimension[PolicyDimension.MEASUREMENT],
                classification=rule.policy_by_dimension[PolicyDimension.CLASSIFICATION],
                presentation=rule.policy_by_dimension[PolicyDimension.PRESENTATION],
                disclosure=rule.policy_by_dimension[PolicyDimension.DISCLOSURE],
                line_mappings=line_mappings,
                evidence_anchors=fact.anchors,
                accepted_value=rule.domain.value,
            )
        )

    return FrameworkPolicyResult(
        result_id=_result_id(
            framework_id,
            matrix_version=matrix.version,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            decisions=decisions,
            gaps=gaps,
        ),
        framework_id=framework_id,
        matrix_version=matrix.version,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        generated_at=report_period_end,
        required_statements=_REQUIRED_STATEMENTS,
        decisions=decisions,
        gaps=gaps,
    )


def _parse_notes_metadata(notes: str | None) -> tuple[str | None, str | None]:
    if not notes:
        return None, None

    intent_match = re.search(r"holding_intent:\s*(\w+)", notes, re.IGNORECASE)
    horizon_match = re.search(r"horizon:\s*(\w+)", notes, re.IGNORECASE)
    intent = intent_match.group(1).lower() if intent_match else None
    horizon = horizon_match.group(1).lower() if horizon_match else None
    return intent, horizon


async def framework_policy_facts_for_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    report_period_start: date,
    report_period_end: date,
    as_of_date: date,
) -> list[FrameworkPolicyFact]:
    """Build framework-neutral facts from existing source, ledger, and portfolio records."""
    facts: list[FrameworkPolicyFact] = []

    account_result = await db.execute(
        select(Account).where(
            Account.user_id == user_id,
            Account.is_active == True,  # noqa: E712
            Account.is_system == False,  # noqa: E712
        )
    )
    for account in account_result.scalars().all():
        mapping = _account_domain_and_instrument(account)
        if mapping is None:
            continue
        domain, instrument_type = mapping
        facts.append(
            FrameworkPolicyFact(
                fact_id=f"account:{account.id}",
                domain=domain,
                instrument_type=instrument_type,
                currency=account.currency,
                event_date=as_of_date,
                anchors=[
                    _anchor(
                        anchor_type="account",
                        source_system="canonical_ledger",
                        source_id=account.id,
                        description=account.name,
                    )
                ],
            )
        )

    position_result = await db.execute(
        select(AtomicPosition)
        .where(AtomicPosition.user_id == user_id)
        .where(AtomicPosition.snapshot_date <= as_of_date)
        .order_by(AtomicPosition.snapshot_date.desc(), AtomicPosition.created_at.desc())
    )
    seen_positions: set[str] = set()
    latest_positions: list[AtomicPosition] = []
    for position in position_result.scalars().all():
        normalized_identifier = position.asset_identifier.strip().upper()
        if normalized_identifier in seen_positions:
            continue
        seen_positions.add(normalized_identifier)
        latest_positions.append(position)

    latest_override_by_identifier: dict[str, MarketDataOverride] = {}
    latest_stock_price_by_identifier: dict[str, StockPrice] = {}
    if seen_positions:
        override_result = await db.execute(
            select(MarketDataOverride)
            .where(MarketDataOverride.user_id == user_id)
            .where(func.upper(MarketDataOverride.asset_identifier).in_(seen_positions))
            .where(MarketDataOverride.price_date <= as_of_date)
            .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
        )
        for override in override_result.scalars().all():
            latest_override_by_identifier.setdefault(override.asset_identifier.strip().upper(), override)

        stock_price_result = await db.execute(
            select(StockPrice)
            .where(StockPrice.symbol.in_(sorted(seen_positions)))
            .where(StockPrice.price_date <= as_of_date)
            .order_by(StockPrice.price_date.desc(), StockPrice.created_at.desc())
        )
        for stock_price in stock_price_result.scalars().all():
            latest_stock_price_by_identifier.setdefault(stock_price.symbol.strip().upper(), stock_price)

    for position in latest_positions:
        domain, instrument_type = _position_domain_and_instrument(position)
        anchors = [
            _anchor(
                anchor_type="atomic_position",
                source_system="portfolio_subledger",
                source_id=position.id,
                description=position.asset_identifier,
            )
        ]
        asset_identifier = position.asset_identifier.strip().upper()
        override = latest_override_by_identifier.get(asset_identifier)
        stock_price = latest_stock_price_by_identifier.get(asset_identifier)
        price_candidates: list[tuple[date, int, MarketDataOverride | StockPrice]] = []
        if stock_price is not None:
            price_candidates.append((stock_price.price_date, 0, stock_price))
        if override is not None:
            price_candidates.append((override.price_date, 1, override))
        price = (
            max(price_candidates, key=lambda candidate: (candidate[0], candidate[1]))[2] if price_candidates else None
        )
        if price is not None:
            source_system = "market_data_override" if isinstance(price, MarketDataOverride) else "stock_price"
            source_id = price.id
            identifier = price.asset_identifier if isinstance(price, MarketDataOverride) else price.symbol
            anchors.append(
                _anchor(
                    anchor_type="market_price",
                    source_system=source_system,
                    source_id=source_id,
                    description=f"{identifier} price dated {price.price_date.isoformat()}",
                )
            )
        facts.append(
            FrameworkPolicyFact(
                fact_id=f"atomic_position:{position.id}",
                domain=domain,
                instrument_type=instrument_type,
                amount=Decimal(position.market_value),
                currency=position.currency,
                event_date=position.snapshot_date,
                anchors=anchors,
            )
        )

    manual_result = await db.execute(
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.as_of_date <= as_of_date)
        .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )
    seen_manual: set[tuple[ManualValuationComponentType, str]] = set()
    for snapshot in manual_result.scalars().all():
        manual_key = (snapshot.component_type, snapshot.source)
        if manual_key in seen_manual:
            continue
        seen_manual.add(manual_key)
        domain, instrument_type = _manual_domain_and_instrument(snapshot)
        intent, horizon = _parse_notes_metadata(snapshot.notes)
        facts.append(
            FrameworkPolicyFact(
                fact_id=f"manual_valuation_snapshot:{snapshot.id}",
                domain=domain,
                instrument_type=instrument_type,
                amount=Decimal(snapshot.value),
                currency=snapshot.currency,
                event_date=snapshot.as_of_date,
                anchors=[
                    _anchor(
                        anchor_type="manual_valuation_snapshot",
                        source_system="manual_valuation",
                        source_id=snapshot.id,
                        description=snapshot.source,
                    )
                ],
                holding_intent=intent,
                horizon=horizon,
            )
        )

    dividend_result = await db.execute(
        select(DividendIncome)
        .where(DividendIncome.user_id == user_id)
        .where(DividendIncome.payment_date >= report_period_start)
        .where(DividendIncome.payment_date <= report_period_end)
    )
    for dividend in dividend_result.scalars().all():
        facts.append(
            FrameworkPolicyFact(
                fact_id=f"dividend_income:{dividend.id}",
                domain=PolicyFactDomain.DIVIDEND_INTEREST,
                instrument_type="dividend",
                amount=Decimal(dividend.amount),
                currency=dividend.currency,
                event_date=dividend.payment_date,
                anchors=[
                    _anchor(
                        anchor_type="dividend_income",
                        source_system="portfolio_subledger",
                        source_id=dividend.id,
                    )
                ],
            )
        )

    return facts


async def derive_user_framework_policy_result(
    db: AsyncSession,
    user_id: UUID,
    *,
    framework_id: PersonalReportingFrameworkId,
    report_period_start: date,
    report_period_end: date,
    as_of_date: date,
) -> FrameworkPolicyResult:
    """Derive the selected framework policy result from current user facts without writes."""
    facts = await framework_policy_facts_for_user(
        db,
        user_id,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        as_of_date=as_of_date,
    )
    return derive_framework_policy_result(
        framework_id,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        facts=facts,
    )
