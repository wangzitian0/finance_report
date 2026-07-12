"""Personal report-package traceability appendix assembly.

Builds the traceability payload (source/ledger anchors per report line) from
posted journal entries, manual valuations, atomic positions, dividends, market
prices, and the evidence graph. Extracted from the reports router so the router
stays a thin HTTP layer; behavior is unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.extension.evidence_lineage import EvidenceLineageService
from src.models.account import Account, AccountType
from src.models.journal import JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicPosition, AtomicTransaction
from src.models.layer3 import ManualValuationLiquidityClass, ManualValuationSnapshot
from src.models.portfolio import DividendIncome, MarketDataOverride
from src.reporting.base.report_package_contract import PERSONAL_REPORT_PACKAGE_TRACEABILITY
from src.reporting.extension.confidence_tier import derive_confidence_tier


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
    if source_type == JournalEntrySourceType.AUTO_PARSED:
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
    db: AsyncSession,
    user_id: UUID,
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


async def build_personal_report_package_traceability_payload(
    *,
    start_date: date | None,
    end_date: date | None,
    as_of_date: date | None,
    db: AsyncSession | None,
    user_id: UUID | None,
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
        .where(ManualValuationSnapshot.superseded_by_id.is_(None))
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
            "valuation_basis": (snapshot.valuation_basis.value if snapshot.valuation_basis else "unspecified"),
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
