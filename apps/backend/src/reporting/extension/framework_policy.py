"""Deterministic framework policy matrix for personal reports."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import canonical_json_digest
from src.extraction.orm.layer2 import AssetType, AtomicPosition
from src.ledger import Account, AccountType, JournalEntry, JournalEntryAuthorityState, JournalLine, ProcessingAccount
from src.ledger.orm.journal import active_journal_entry_filter
from src.portfolio import DividendIncome
from src.pricing import (
    ManualValuationComponentType,
    ManualValuationFact,
    MarketDataOverride,
    list_current_manual_valuation_facts,
)
from src.pricing.orm.market_data import StockPrice
from src.reporting.base.l1_registry import EXPENSE_CATEGORY_LINES, INCOME_CATEGORY_LINES, L1_REGISTRY
from src.reporting.base.types import PersonalReportingFrameworkId, PolicyDimension
from src.schemas.reporting import (
    FrameworkPolicyDecision,
    FrameworkPolicyEvidenceAnchor,
    FrameworkPolicyFact,
    FrameworkPolicyGap,
    FrameworkPolicyMatrix,
    FrameworkPolicyMatrixRule,
    FrameworkPolicyResult,
    PolicyFactDomain,
)

_REQUIRED_STATEMENTS = [
    "balance_sheet",
    "income_statement",
    "cash_flow",
    "notes",
    "traceability_appendix",
]
_DEFAULT_EVIDENCE = ["source_anchor", "ledger_or_portfolio_anchor", "review_state"]
_DEFAULT_DISCLOSURE = ["basis", "source_coverage", "valuation_or_cutoff"]
_DEFAULT_BLOCKERS = ["missing_source_anchor", "pending_review", "missing_measurement_basis"]

_COMMON_SPECS: tuple[tuple[PolicyFactDomain, str, str, str, str, str, str, str], ...] = (
    (
        PolicyFactDomain.CASH,
        "cash_in_transit",
        "Recognize the ledger-owned Processing identity as funds in transit.",
        "Include the exact posted balance with the same period-end currency translation as other cash.",
        "Cash equivalent held in transit between custody accounts.",
        "{fw} balance sheet separately presents cash in transit.",
        "Unsettled funds remain visible until both transfer legs are posted.",
        "balance_sheet=assets.cash_in_transit,cash_flow=cash.internal_transfers",
    ),
    (
        PolicyFactDomain.CASH,
        "bank_account,cash,deposit,fixture",
        "Recognize cash movements on transaction date after source cutoff validation.",
        "Measure cash at nominal amount; translate non-reporting currencies using transaction or period-end FX rules.",
        "Cash and bank account asset.",
        "{fw} balance sheet cash and cash equivalents.",
        "Disclose source coverage, cutoff, currency, and unresolved bank statement gaps.",
        "balance_sheet=assets.cash_and_cash_equivalents,cash_flow=cash.ending_cash",
    ),
    (
        PolicyFactDomain.FUND,
        "fund,money_market_fund,etf_fund,fixture",
        "Recognize fund holdings when brokerage or custodian evidence confirms ownership.",
        "Measure at observable fund NAV or quoted fair value when freshness evidence exists.",
        "Investment asset, classified by liquidity and redemption terms.",
        "{fw} investment schedule fund line.",
        "Disclose valuation source, price date, liquidity terms, and stale NAV blockers.",
        "balance_sheet=assets.investments.funds,notes=notes.fund_liquidity",
    ),
    (
        PolicyFactDomain.DIVIDEND_INTEREST,
        "dividend,interest,coupon,fixture",
        "Recognize dividends and interest on entitlement, ex-date, payment date, or statement date per source evidence.",
        "Measure gross and net cash amounts separately when withholding evidence exists.",
        "Investment or bank income.",
        "{fw} income statement dividend and interest income.",
        "Disclose withholding, tax-note hooks, and source date used for recognition.",
        "income_statement=income.dividends_and_interest,notes=notes.tax_hooks",
    ),
    (
        PolicyFactDomain.BROKERAGE_FEE,
        "commission,brokerage_fee,platform_fee,fixture",
        "Recognize brokerage fees when the trade or broker statement evidence is available.",
        "Measure fees at settled cash amount and preserve currency/FX treatment.",
        "Cost basis adjustment or investment expense according to linked transaction type.",
        "{fw} cash-flow and investment performance fee lines.",
        "Disclose whether fees affect cost basis or period expense.",
        "income_statement=expenses.investment_fees,cash_flow=investing.fees",
    ),
    (
        PolicyFactDomain.FX,
        "fx_transaction,fx_rate,currency_translation,fixture",
        "Recognize FX effects when source currency differs from report currency.",
        "Use transaction-date rates for transactions, average rates for period income where configured, and period-end rates for balances.",
        "FX gain/loss, translation adjustment, or disclosure-only rate effect.",
        "{fw} FX line mapping by statement type.",
        "Disclose rate source, rate date, missing-rate blockers, and stale-rate fallback.",
        "income_statement=income.fx_gain_loss,balance_sheet=equity.fx_translation",
    ),
    (
        PolicyFactDomain.RESTRICTED_COMPENSATION,
        "rsu,esop,stock_option,restricted_share,fixture",
        "Recognize restricted compensation when grant, vesting, or exercise evidence exists.",
        "Measure at accepted fair-value input with explicit restriction and liquidity treatment.",
        "Restricted wealth or compensation schedule item, not default liquid net worth.",
        "{fw} long-term compensation schedule.",
        "Disclose vesting, restriction, liquidity class, valuation date, and manual valuation review.",
        "balance_sheet=assets.restricted_compensation,notes=notes.restricted_asset_treatment",
    ),
    (
        PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE,
        "property,mortgage,private_asset,manual_asset,fixture",
        "Recognize manual property, mortgage, and private assets only with explicit source date and owner review.",
        "Measure using accepted manual valuation basis; block trusted totals when basis is missing.",
        "Manual asset, private asset, or secured liability.",
        "{fw} manual valuation and liability schedule.",
        "Disclose valuation basis, confidence tier, source date, and trusted-total blocker state.",
        "balance_sheet=assets.manual_private_assets,notes=notes.manual_valuation_basis",
    ),
    (
        PolicyFactDomain.LIABILITY,
        "loan,credit_card,mortgage_liability,payable,fixture",
        "Recognize liabilities from statement, loan, or manual obligation evidence.",
        "Measure at outstanding principal or statement balance with FX translation when needed.",
        "Current or long-term liability by due date and instrument type.",
        "{fw} balance sheet liability line.",
        "Disclose source balance date, interest hooks, and unresolved liability coverage gaps.",
        "balance_sheet=liabilities.financial_liabilities,notes=notes.liability_coverage",
    ),
    (
        PolicyFactDomain.TRANSFER,
        "internal_transfer,broker_transfer,cash_transfer,fixture",
        "Recognize transfers when both legs or explicit pending processing evidence exist.",
        "Measure transfer legs at source cash amounts and FX translated report-currency equivalents.",
        "Internal movement, not income or expense.",
        "{fw} cash-flow transfer reconciliation.",
        "Disclose unmatched or in-transit transfer blockers.",
        "cash_flow=cash.internal_transfers,notes=notes.transfer_matching",
    ),
    (
        PolicyFactDomain.TAX_NOTE,
        "withholding_tax,tax_note,tax_relevant_item,fixture",
        "Preserve tax-relevant evidence as notes unless a deterministic ledger posting exists.",
        "Measure withheld or tax-relevant amounts from source evidence without estimating tax filings.",
        "Disclosure hook, withholding line, or tax-note appendix.",
        "{fw} notes and tax-hook disclosure.",
        "Disclose that the package is not tax advice or a tax filing.",
        "notes=notes.tax_relevant_items",
    ),
)

_ASSET_MAP = {
    AssetType.STOCK: (PolicyFactDomain.LISTED_SECURITY, "listed_equity"),
    AssetType.ETF: (PolicyFactDomain.LISTED_SECURITY, "etf"),
    AssetType.MUTUAL_FUND: (PolicyFactDomain.FUND, "fund"),
    AssetType.CASH: (PolicyFactDomain.CASH, "cash"),
    AssetType.PROPERTY: (PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "property"),
    AssetType.BOND: (PolicyFactDomain.LISTED_SECURITY, "bond"),
    AssetType.OTHER: (PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "private_asset"),
}
_MANUAL_RESTRICTED = {
    ManualValuationComponentType.ESOP: "esop",
    ManualValuationComponentType.RSU: "rsu",
    ManualValuationComponentType.STOCK_OPTIONS: "stock_option",
}
_MANUAL_LIABILITY = {
    ManualValuationComponentType.MORTGAGE_BALANCE: "mortgage_liability",
    ManualValuationComponentType.TAX_PAYABLE: "payable",
    ManualValuationComponentType.OTHER_LIABILITY: "loan",
}
_ACCOUNT_MAP = {
    AccountType.LIABILITY: (PolicyFactDomain.LIABILITY, "loan"),
    AccountType.INCOME: (PolicyFactDomain.PERSONAL_INCOME, "unclassified_income"),
    AccountType.EXPENSE: (PolicyFactDomain.PERSONAL_EXPENSE, "unclassified_expense"),
}


def _rule(
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
        policy_by_dimension={
            PolicyDimension.RECOGNITION: recognition,
            PolicyDimension.MEASUREMENT: measurement,
            PolicyDimension.CLASSIFICATION: classification,
            PolicyDimension.PRESENTATION: presentation,
            PolicyDimension.DISCLOSURE: disclosure,
        },
        line_mappings=line_mappings,
        required_evidence=list(_DEFAULT_EVIDENCE) if required_evidence is None else required_evidence,
        disclosure_requirements=list(_DEFAULT_DISCLOSURE) if disclosure_requirements is None else disclosure_requirements,
        blocker_conditions=list(_DEFAULT_BLOCKERS) if blocker_conditions is None else blocker_conditions,
    )


def _parse_mappings(spec: str) -> dict[str, str]:
    return dict(pair.split("=", 1) for pair in spec.split(","))


def _personal_activity_rules(fw: str) -> list[FrameworkPolicyMatrixRule]:
    return [
        _rule(
            domain,
            [category, instrument] if category == fallback else [category],
            "Recognize the exact accepted economic category frozen into the posted command.",
            "Use posted amounts and the selected period-average currency conversion.",
            L1_REGISTRY[line_id].label,
            f"{fw} {L1_REGISTRY[line_id].label}.",
            "Missing or unsupported historical categories remain other income or expenses.",
            {"income_statement": line_id.value},
        )
        for domain, categories, fallback, instrument in (
            (PolicyFactDomain.PERSONAL_INCOME, INCOME_CATEGORY_LINES, "OTHER_INCOME", "unclassified_income"),
            (PolicyFactDomain.PERSONAL_EXPENSE, EXPENSE_CATEGORY_LINES, "OTHER_EXPENSE", "unclassified_expense"),
        )
        for category, line_id in categories.items()
    ]


def get_framework_policy_matrix(framework_id: PersonalReportingFrameworkId) -> FrameworkPolicyMatrix:
    is_us = framework_id == PersonalReportingFrameworkId.US_GAAP_LIKE
    fw = "US-like" if is_us else "HK-like"
    listed_security = _rule(
        PolicyFactDomain.LISTED_SECURITY,
        ["listed_equity", "listed_security", "etf", "bond", "fixture"],
        "Recognize listed securities when brokerage evidence confirms trade or holding ownership.",
        (
            "Measure at quoted fair value when market data is fresh; preserve cost basis and unrealized gain evidence."
            if is_us
            else "Measure at quoted fair value when market data is fresh; preserve cost basis and fair-value movement evidence."
        ),
        "Marketable investment asset."
        if is_us
        else "Financial asset measured with HK-like fair-value presentation.",
        (
            "US-like balance sheet marketable securities with unrealized gain note discipline."
            if is_us
            else "HK-like balance sheet financial assets at fair value with investment revaluation note discipline."
        ),
        (
            "Disclose price source, stale price blocker, cost basis, and unrealized gain presentation."
            if is_us
            else "Disclose price source, stale price blocker, fair-value hierarchy hint, and revaluation presentation."
        ),
        (
            {
                "balance_sheet": "assets.marketable_securities",
                "income_statement": "income.unrealized_investment_gain_loss",
                "notes": "notes.us_like_market_price_basis",
            }
            if is_us
            else {
                "balance_sheet": "assets.financial_assets_at_fair_value",
                "income_statement": "income.fair_value_change_in_financial_assets",
                "notes": "notes.hk_like_fair_value_basis",
            }
        ),
    )
    common = [
        _rule(d, inst.split(","), rec, meas, cls, pres.format(fw=fw), disc, _parse_mappings(maps))
        for d, inst, rec, meas, cls, pres, disc, maps in _COMMON_SPECS
    ]
    return FrameworkPolicyMatrix(
        framework_id=framework_id,
        version="2.0",
        rules=[listed_security, *_personal_activity_rules(fw), *common],
    )


def _find_rule(matrix: FrameworkPolicyMatrix, fact: FrameworkPolicyFact) -> FrameworkPolicyMatrixRule | None:
    if fact.domain == PolicyFactDomain.UNSUPPORTED:
        return None
    return next(
        (r for r in matrix.rules if r.domain == fact.domain and fact.instrument_type in r.supported_instrument_types),
        None,
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
    key_fn = lambda obj: json.dumps(obj, sort_keys=True, separators=(",", ":"))  # noqa: E731
    digest = canonical_json_digest(
        {
            "framework_id": framework_id.value,
            "matrix_version": matrix_version,
            "report_period_start": report_period_start.isoformat(),
            "report_period_end": report_period_end.isoformat(),
            "decisions": sorted((d.model_dump(mode="json") for d in decisions), key=key_fn),
            "gaps": sorted((g.model_dump(mode="json") for g in gaps), key=key_fn),
        }
    )[:16]
    return f"policy-result:{framework_id.value}:{report_period_start.isoformat()}:{report_period_end.isoformat()}:{digest}"


def _anchor(
    anchor_type: str, source_system: str, source_id: object, description: str | None = None
) -> FrameworkPolicyEvidenceAnchor:
    return FrameworkPolicyEvidenceAnchor(
        anchor_id=f"{anchor_type}:{source_id}",
        anchor_type=anchor_type,
        source_system=source_system,
        source_id=str(source_id),
        description=description,
    )


def _position_domain_and_instrument(position: AtomicPosition) -> tuple[PolicyFactDomain, str]:
    if position.asset_type is None:
        return PolicyFactDomain.UNSUPPORTED, "unknown_asset"
    return _ASSET_MAP.get(position.asset_type, (PolicyFactDomain.UNSUPPORTED, position.asset_type.value))


def _manual_domain_and_instrument(snapshot: ManualValuationFact) -> tuple[PolicyFactDomain, str]:
    ct = snapshot.component_type
    if ct in _MANUAL_RESTRICTED:
        return PolicyFactDomain.RESTRICTED_COMPENSATION, _MANUAL_RESTRICTED[ct]
    if ct in _MANUAL_LIABILITY:
        return PolicyFactDomain.LIABILITY, _MANUAL_LIABILITY[ct]
    return (
        PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE,
        "property" if ct == ManualValuationComponentType.PROPERTY_VALUE else "manual_asset",
    )


def _account_domain_and_instrument(account: Account) -> tuple[PolicyFactDomain, str] | None:
    if account.type == AccountType.ASSET:
        is_transit = getattr(account, "is_system", False) and getattr(account, "code", None) == ProcessingAccount().code
        return PolicyFactDomain.CASH, "cash_in_transit" if is_transit else "bank_account"
    return _ACCOUNT_MAP.get(account.type)


def derive_framework_policy_result(
    framework_id: PersonalReportingFrameworkId,
    *,
    report_period_start: date,
    report_period_end: date,
    facts: list[FrameworkPolicyFact],
) -> FrameworkPolicyResult:
    matrix = get_framework_policy_matrix(framework_id)
    decisions: list[FrameworkPolicyDecision] = []
    gaps: list[FrameworkPolicyGap] = []
    for fact in facts:
        rule = _find_rule(matrix, fact)
        if rule is None:
            gaps.append(
                FrameworkPolicyGap(
                    code="unsupported_policy_domain",
                    fact_id=fact.fact_id,
                    domain=fact.domain,
                    instrument_type=fact.instrument_type,
                    blocker=True,
                    reason="No deterministic v1 framework policy rule exists for this fact domain and instrument type.",
                    remediation="Add an explicit policy rule, accepted manual valuation basis, or reviewed structured policy field before trusted output.",
                    evidence_anchors=fact.anchors,
                )
            )
            continue
        line_mappings = dict(rule.line_mappings)
        if (
            fact.domain == PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE
            and fact.instrument_type == "property"
            and framework_id == PersonalReportingFrameworkId.HKFRS_LIKE
            and fact.holding_intent == "investment"
        ):
            line_mappings["balance_sheet"] = "assets.investment_property"
        p = rule.policy_by_dimension
        decisions.append(
            FrameworkPolicyDecision(
                domain=fact.domain,
                recognition=p[PolicyDimension.RECOGNITION],
                measurement=p[PolicyDimension.MEASUREMENT],
                classification=p[PolicyDimension.CLASSIFICATION],
                presentation=p[PolicyDimension.PRESENTATION],
                disclosure=p[PolicyDimension.DISCLOSURE],
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
    intent_m = re.search(r"holding_intent:\s*(\w+)", notes, re.IGNORECASE)
    horizon_m = re.search(r"horizon:\s*(\w+)", notes, re.IGNORECASE)
    return (intent_m.group(1).lower() if intent_m else None, horizon_m.group(1).lower() if horizon_m else None)


async def framework_policy_facts_for_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    report_period_start: date,
    report_period_end: date,
    as_of_date: date,
) -> list[FrameworkPolicyFact]:
    facts: list[FrameworkPolicyFact] = []
    for account in (await db.scalars(select(Account).where(Account.user_id == user_id))).all():
        if (mapping := _account_domain_and_instrument(account)) is not None:
            facts.append(
                FrameworkPolicyFact(
                    fact_id=f"account:{account.id}",
                    domain=mapping[0],
                    instrument_type=mapping[1],
                    currency=account.currency,
                    event_date=as_of_date,
                    anchors=[_anchor("account", "canonical_ledger", account.id, account.name)],
                )
            )

    category_rows = await db.execute(
        select(JournalLine, Account)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(
            JournalEntry.user_id == user_id,
            Account.user_id == user_id,
            active_journal_entry_filter(JournalEntry),
            JournalEntry.decision_authority_state == JournalEntryAuthorityState.ANCHORED,
            JournalEntry.decision_anchor_id.is_not(None),
            JournalEntry.entry_date >= report_period_start,
            JournalEntry.entry_date <= report_period_end,
            Account.type.in_((AccountType.INCOME, AccountType.EXPENSE)),
        )
    )
    for line, account in category_rows.all():
        category = (line.tags or {}).get("economic_category")
        is_income = account.type == AccountType.INCOME
        if isinstance(category, str) and category in (INCOME_CATEGORY_LINES if is_income else EXPENSE_CATEGORY_LINES):
            facts.append(
                FrameworkPolicyFact(
                    fact_id=f"journal_line:{line.id}",
                    domain=PolicyFactDomain.PERSONAL_INCOME if is_income else PolicyFactDomain.PERSONAL_EXPENSE,
                    instrument_type=category,
                    currency=line.currency,
                    anchors=[_anchor("journal_line", "canonical_ledger", line.id, "Accepted posted economic category")],
                )
            )

    pos_rows = (
        await db.scalars(
            select(AtomicPosition)
            .where(AtomicPosition.user_id == user_id, AtomicPosition.snapshot_date <= as_of_date)
            .order_by(AtomicPosition.snapshot_date.desc(), AtomicPosition.created_at.desc())
        )
    ).all()
    latest_by_ident: dict[str, AtomicPosition] = {}
    for position in pos_rows:
        latest_by_ident.setdefault(position.asset_identifier.strip().upper(), position)
    seen_positions = set(latest_by_ident)

    overrides: dict[str, MarketDataOverride] = {}
    stock_prices: dict[str, StockPrice] = {}
    if seen_positions:
        for ov in (
            await db.scalars(
                select(MarketDataOverride)
                .where(
                    MarketDataOverride.user_id == user_id,
                    func.upper(MarketDataOverride.asset_identifier).in_(seen_positions),
                    MarketDataOverride.price_date <= as_of_date,
                )
                .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
            )
        ).all():
            overrides.setdefault(ov.asset_identifier.strip().upper(), ov)
        for sp in (
            await db.scalars(
                select(StockPrice)
                .where(StockPrice.symbol.in_(sorted(seen_positions)), StockPrice.price_date <= as_of_date)
                .order_by(StockPrice.price_date.desc(), StockPrice.created_at.desc())
            )
        ).all():
            stock_prices.setdefault(sp.symbol.strip().upper(), sp)

    for norm, position in latest_by_ident.items():
        domain, instrument_type = _position_domain_and_instrument(position)
        anchors = [_anchor("atomic_position", "portfolio_subledger", position.id, position.asset_identifier)]
        candidates: list[tuple[date, int, MarketDataOverride | StockPrice]] = []
        if (sp_cand := stock_prices.get(norm)) is not None:
            candidates.append((sp_cand.price_date, 0, sp_cand))
        if (ov_cand := overrides.get(norm)) is not None:
            candidates.append((ov_cand.price_date, 1, ov_cand))
        if candidates:
            price = max(candidates, key=lambda c: (c[0], c[1]))[2]
            source_kind, ident = (
                ("market_data_override", price.asset_identifier)
                if isinstance(price, MarketDataOverride)
                else ("stock_price", price.symbol)
            )
            anchors.append(
                _anchor("market_price", source_kind, price.id, f"{ident} price dated {price.price_date.isoformat()}")
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

    for snapshot in await list_current_manual_valuation_facts(db, user_id, as_of_date=as_of_date):
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
                anchors=[_anchor("manual_valuation_snapshot", "manual_valuation", snapshot.id, snapshot.source)],
                holding_intent=intent,
                horizon=horizon,
            )
        )

    for div in (
        await db.scalars(
            select(DividendIncome).where(
                DividendIncome.user_id == user_id,
                DividendIncome.payment_date >= report_period_start,
                DividendIncome.payment_date <= report_period_end,
            )
        )
    ).all():
        facts.append(
            FrameworkPolicyFact(
                fact_id=f"dividend_income:{div.id}",
                domain=PolicyFactDomain.DIVIDEND_INTEREST,
                instrument_type="dividend",
                amount=Decimal(div.amount),
                currency=div.currency,
                event_date=div.payment_date,
                anchors=[_anchor("dividend_income", "portfolio_subledger", div.id)],
            )
        )

    return sorted(facts, key=lambda fact: fact.fact_id)


async def derive_user_framework_policy_result(
    db: AsyncSession,
    user_id: UUID,
    *,
    framework_id: PersonalReportingFrameworkId,
    report_period_start: date,
    report_period_end: date,
    as_of_date: date,
) -> FrameworkPolicyResult:
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
