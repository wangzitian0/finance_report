"""Executable TrustedYearScenario v0 terminal proof (#696)."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof
from common.testing.trusted_year import TRUSTED_YEAR_SCENARIO
from sqlalchemy import select

from src.audit import (
    SqlTraceRecordRepository,
    TraceEmitter,
    TraceRecord,
    TraceRecordPersistenceError,
    TraceRecordType,
    TraceResult,
    TraceScope,
    VersionedTraceRef,
    current_authoritative_trace_decision_projection,
)
from src.audit.orm.trace_record import TraceRecordParentRow, TraceRecordRow
from src.config import settings
from src.database import create_session_maker_from_db
from src.deps import PaginationParams
from src.extraction import DocumentType, ParseJob, UploadedDocument
from src.extraction.base.result import (
    ExtractedPositionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.extension import transaction_classification
from src.extraction.extension.extraction_trace import (
    build_extraction_trace_records,
    extraction_trace_policy_registry,
)
from src.extraction.extension.reviewed_statement_envelope import (
    ReviewedStatementEnvelopeCommand,
    confirm_reviewed_statement_envelope,
    persist_statement_extraction_result,
)
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement, resolve_statement_transactions
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import (
    ClassificationRule,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    RuleType,
)
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, post_opening_balance_entry
from src.pricing import record_manual_valuation
from src.pricing.orm.market_data import StockPrice
from src.reporting import PackageAssembler
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
    get_personal_report_package_snapshot,
    list_personal_report_package_snapshots,
)
from src.routers.statements import import_brokerage_statement_positions
from src.schemas import (
    PersonalReportingFrameworkId,
    PersonalReportPackageGenerateRequest,
    PersonalReportPackageReadinessState,
    PersonalReportPackageSnapshotStatus,
)
from tests.statement_ingestion import execute_statement_ingestion, posting_dependencies


def _bank_csv() -> bytes:
    return (
        b"Statement Currency,Date,Description,Debit Amount,Credit Amount\n"
        b"SGD,2026-06-05,Salary credit,,5000.00\n"
        b"SGD,2026-06-10,Rent debit,1000.00,\n"
        b"SGD,2026-06-15,Buy security,1000.00,\n"
    )


async def _ingest_reviewed_bank_statement(db, *, user_id, bank: Account) -> None:
    content = _bank_csv()
    digest = hashlib.sha256(content).hexdigest()
    bank_id = bank.id
    statement = StatementSummary(
        user_id=user_id,
        file_hash=digest,
        institution="DBS",
        status=BankStatementStatus.UPLOADED,
    )
    db.add(statement)
    await db.flush()
    statement_id = statement.id
    await db.commit()
    await execute_statement_ingestion(
        ParseJob(
            statement_id=statement_id,
            filename="trusted-year-v0.csv",
            institution="DBS",
            user_id=user_id,
            account_id=bank_id,
            file_hash=digest,
            storage_key="trusted-year/v0.csv",
            model=None,
        ),
        content=content,
        session_maker=create_session_maker_from_db(db),
    )
    db.expire_all()
    statement = await db.get(StatementSummary, statement_id)
    assert statement is not None
    transactions = await resolve_statement_transactions(db, statement)
    source_record = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    assert source_record is not None
    statement.account_id = bank_id
    statement.currency = "SGD"
    statement.period_start = min(transaction.txn_date for transaction in transactions)
    statement.period_end = max(transaction.txn_date for transaction in transactions)
    statement.opening_balance = TRUSTED_YEAR_SCENARIO.opening_cash
    statement.closing_balance = TRUSTED_YEAR_SCENARIO.expected.ending_cash
    await db.flush()
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))
    await confirm_reviewed_statement_envelope(
        db,
        user_id=user_id,
        statement_id=statement.id,
        command=ReviewedStatementEnvelopeCommand(
            source_result_digest=source_record.content_digest,
            account_id=bank_id,
            currency="SGD",
            period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=statement.opening_balance,
            closing_balance=statement.closing_balance,
            rationale="TrustedYearScenario v0 reviewed source envelope.",
        ),
        trace_emitter=emitter,
    )
    approved = await approve_statement(db, statement.id, user_id)
    outcome = await auto_create_posted_entries_for_statement(db, approved, user_id, dependencies=posting_dependencies())
    assert outcome.review_reasons == ()
    assert outcome.created_count == 3


async def _import_brokerage_position(db, *, user_id) -> None:
    position = TRUSTED_YEAR_SCENARIO.position
    digest = hashlib.sha256(f"trusted-year-v0:{position.institution}:{position.symbol}".encode()).hexdigest()
    result = StatementExtractionResult.create(
        producer_version="trusted-year-v0@1",
        source_content_digest=digest,
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        institution=position.institution,
        account_last4="2026",
        period_start=position.as_of,
        period_end=position.as_of,
        balances=(),
        transactions=(),
        positions=(
            ExtractedPositionFact(
                fact_id="trusted-year-v0-aapl",
                symbol=position.symbol,
                quantity=position.quantity,
                market_value=position.source_value,
                currency="SGD",
                confidence=Decimal("0.95"),
                asset_type="stock",
            ),
        ),
        confidence=Decimal("0.95"),
        balance_validated=True,
        warnings=(),
        review_reasons=(),
        provenance=SourceProvenance(
            intake_mode="csv",
            method=ExtractionMethod.DETERMINISTIC,
            provider="trusted-year-v0-brokerage",
            model="v1",
        ),
        statement_currency="SGD",
    )
    document = UploadedDocument(
        user_id=user_id,
        file_path=f"memory://trusted-year/{digest}",
        file_hash=digest,
        original_filename="trusted-year-v0-moomoo.csv",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    db.add(document)
    await db.flush()
    statement = StatementSummary(
        user_id=user_id,
        uploaded_document_id=document.id,
        file_hash=digest,
        institution=position.institution,
        account_last4="2026",
        currency="SGD",
        period_start=position.as_of,
        period_end=position.as_of,
        status=BankStatementStatus.PARSED,
        extraction_metadata={"statement_extraction_result": result.to_payload()},
    )
    db.add(statement)
    await db.flush()
    traces = build_extraction_trace_records(
        result,
        user_id=user_id,
        execution_id=f"trusted-year-v0:{statement.id}:{result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    await persist_statement_extraction_result(
        db,
        statement=statement,
        result=result,
        source_trace_record_id=traces[0].record_id,
    )
    await db.commit()
    imported = await import_brokerage_statement_positions(statement.id, db, user_id)
    assert (imported.parsed_positions, imported.created_atomic_positions) == (1, 1)


async def _stream_body(response) -> str:
    return "".join([chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator])


async def _supersede_selected_authority_parents(db, *, user_id, document) -> None:
    """Invalidate selected authority through the append-only graph product reads."""
    decision_ids = {entry.decision_id for entry in document.input_manifest}
    projection = current_authoritative_trace_decision_projection(TraceScope.tenant(user_id)).subquery(
        "trusted_year_current_decisions"
    )
    current_ids = set(
        (await db.execute(select(projection.c.decision_id).where(projection.c.decision_id.in_(decision_ids)))).scalars()
    )
    assert current_ids == decision_ids

    observation_ids: set = set()
    frontier = decision_ids
    visited = set(decision_ids)
    while frontier:
        parent_ids = set(
            (
                await db.execute(
                    select(TraceRecordParentRow.parent_id).where(TraceRecordParentRow.record_id.in_(frontier))
                )
            ).scalars()
        )
        unseen = parent_ids - visited
        if not unseen:
            break
        rows = (
            await db.execute(select(TraceRecordRow.id, TraceRecordRow.record_type).where(TraceRecordRow.id.in_(unseen)))
        ).all()
        observation_ids.update(
            record_id for record_id, record_type in rows if record_type is TraceRecordType.OBSERVATION
        )
        frontier = {record_id for record_id, record_type in rows if record_type is TraceRecordType.DECISION}
        visited.update(unseen)
    assert observation_ids
    repository = SqlTraceRecordRepository(db)
    parents = [
        parent
        for parent_id in sorted(observation_ids, key=str)
        if (parent := await repository.get(TraceScope.tenant(user_id), parent_id)) is not None
    ]
    assert {parent.record_id for parent in parents} == observation_ids

    def correction(parent, *, scope, target_id: str, suffix: str) -> TraceRecord:
        return TraceRecord.observation(
            scope=scope,
            target=VersionedTraceRef(
                parent.target.kind,
                target_id,
                f"{parent.target.version}:{suffix}",
            ),
            target_class=parent.target_class,
            assertion=parent.assertion,
            authority=parent.authority,
            result=TraceResult.UNPROVEN,
            execution_id=f"trusted-year-v0:{suffix}:{parent.record_id}",
            evidence_manifest_digest=hashlib.sha256(
                f"trusted-year-v0:{suffix}:{parent.record_id}".encode()
            ).hexdigest(),
            occurred_at=datetime.now(UTC),
            score=None,
            reason_code="trusted_year_authority_counterfactual",
            supersedes_id=parent.record_id,
        )

    first = parents[0]
    with pytest.raises(TraceRecordPersistenceError, match="cross-scope"):
        await repository.append(
            correction(
                first,
                scope=TraceScope.tenant(uuid4()),
                target_id=first.target.id,
                suffix="cross-scope",
            )
        )
    with pytest.raises(TraceRecordPersistenceError, match="lineage"):
        await repository.append(
            correction(
                first,
                scope=first.scope,
                target_id=f"{first.target.id}:mismatch",
                suffix="target-mismatch",
            )
        )

    for parent in parents:
        await repository.append(
            correction(
                parent,
                scope=parent.scope,
                target_id=parent.target.id,
                suffix="superseded",
            )
        )


@ac_proof(
    "trusted-year-v0-terminal",
    ac_ids=[
        "AC-testing.trusted-year.2",
        "AC-testing.trusted-year.3",
        "AC-testing.package-lifecycle.1",
    ],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["bank_statement", "brokerage_statement"],
    scenario_id="trusted-year-v0",
    oracle_kind="independent_decimal",
    issue="#696",
)
async def test_AC_testing_trusted_year_2_deterministic_executor_proves_package_lifecycle(
    db, test_user, monkeypatch
) -> None:
    """AC-testing.trusted-year.2 AC-testing.trusted-year.3 AC-testing.package-lifecycle.1."""
    scenario = TRUSTED_YEAR_SCENARIO
    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def deterministic_proposer(transactions, _policy):
        categories = {
            "Salary credit": TransactionCategory.SALARY,
            "Rent debit": TransactionCategory.HOUSING,
        }
        return [
            CategoryProposal(category=categories[item.description].value, confidence=99, reason="trusted-year-v0")
            for item in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", deterministic_proposer)
    bank = Account(user_id=test_user.id, name="DBS", type=AccountType.ASSET, currency="SGD")
    securities = Account(
        user_id=test_user.id,
        name="Asset - Securities",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add_all((bank, securities))
    await db.flush()
    db.add(
        ClassificationRule(
            user_id=test_user.id,
            created_by=test_user.id,
            version_number=1,
            effective_date=date(2026, 1, 1),
            rule_name="Reviewed TrustedYear investment purchase",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["Buy security"]},
            tag_mappings={"intent": "investment_purchase"},
            default_account_id=securities.id,
        )
    )
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: scenario.opening_cash},
        currency="SGD",
        memo="TrustedYearScenario v0 opening cash",
    )
    await _ingest_reviewed_bank_statement(db, user_id=test_user.id, bank=bank)
    await _import_brokerage_position(db, user_id=test_user.id)
    db.add(
        StockPrice(
            symbol=scenario.position.symbol,
            price=scenario.position.selected_value / scenario.position.quantity,
            currency="SGD",
            price_date=scenario.position.as_of,
            source="trusted-year-v0-recorded-provider",
        )
    )
    valuation = scenario.valuation
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType(valuation.component_type),
        liquidity_class=ManualValuationLiquidityClass(valuation.liquidity_class),
        as_of=valuation.as_of,
        value=valuation.value,
        currency="SGD",
        source=valuation.source,
    )
    await db.commit()

    async def skip_market_refresh(*_args, **_kwargs) -> None:
        pass

    monkeypatch.setattr("src.routers.reports._ensure_report_market_data_fresh", skip_market_refresh)
    snapshot = await generate_personal_report_package_snapshot(
        db,
        user_id=test_user.id,
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            as_of_date=date(2026, 12, 31),
            currency="SGD",
            include_restricted=True,
        ),
    )
    document = snapshot.document
    expected = scenario.expected
    assert snapshot.status is PersonalReportPackageSnapshotStatus.TRUSTED
    assert document.readiness.state is PersonalReportPackageReadinessState.READY, document.readiness.blockers
    assert document.sections.balance_sheet.total_assets == expected.total_assets
    assert document.sections.balance_sheet.total_liabilities == expected.total_liabilities
    assert document.sections.balance_sheet.total_equity == expected.ledger_equity
    assert document.sections.balance_sheet.net_income == expected.net_income
    assert document.sections.balance_sheet.net_worth_adjustment_gain_loss == expected.net_worth_adjustment
    assert document.sections.balance_sheet.is_balanced
    assert document.sections.balance_sheet.assets
    assert document.sections.income_statement.income
    assert document.sections.income_statement.expenses
    assert document.sections.income_statement.net_income == expected.net_income
    assert document.sections.cash_flow.summary.ending_cash == expected.ending_cash
    assert document.sections.cash_flow.summary.investing_activities == -expected.investment_purchase
    assert document.sections.cash_flow.operating
    assert document.sections.cash_flow.investing
    holding = next(
        item
        for item in document.sections.investment_performance.holdings
        if item.asset_identifier == scenario.position.symbol
    )
    assert holding.market_value == expected.investment_market_value
    assert document.sections.notes.notes
    assert document.sections.traceability_appendix.lines
    assert document.readiness.input_coverage.unproven_input_count == 0
    manifest_refs = {input_ref for entry in document.input_manifest for input_ref in entry.input_refs}
    assert {input_ref.partition(":")[0] for input_ref in manifest_refs} == set(scenario.expected_manifest)
    assert all(
        entry.decision_id and entry.target_kind and entry.target_id and entry.assertion_kind and entry.authority_tier
        for entry in document.input_manifest
    )

    frozen = document.model_dump(mode="json")
    listed = await list_personal_report_package_snapshots(db, test_user.id, pagination=PaginationParams())
    assert [item.id for item in listed] == [snapshot.id]
    reopened = await get_personal_report_package_snapshot(snapshot.id, db, test_user.id)
    assert reopened.document.model_dump(mode="json") == frozen
    json_export = await export_personal_report_package_snapshot(
        snapshot.id, db, test_user.id, format=PackageSnapshotExportFormat.JSON
    )
    csv_export = await export_personal_report_package_snapshot(
        snapshot.id, db, test_user.id, format=PackageSnapshotExportFormat.CSV
    )
    json_body = await _stream_body(json_export)
    assert str(snapshot.id) in json_body
    assert "115250.00" in json_body
    assert "balance_sheet.total_assets" in await _stream_body(csv_export)

    authority_counterfactual = await db.begin_nested()
    await _supersede_selected_authority_parents(
        db,
        user_id=test_user.id,
        document=document,
    )
    candidate = await PackageAssembler().assemble(
        db,
        user_id=test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        as_of_date=date(2026, 12, 31),
        currency="SGD",
        include_restricted=True,
    )
    assert candidate.status is PersonalReportPackageSnapshotStatus.DRAFT
    assert candidate.readiness.state is PersonalReportPackageReadinessState.BLOCKED
    assert candidate.package_decision_id is None
    assert candidate.readiness.input_coverage.unproven_input_count > 0
    assert "unproven_package_input" in {blocker.code for blocker in candidate.readiness.blockers}
    await authority_counterfactual.rollback()

    db.add(
        StockPrice(
            symbol=scenario.position.symbol,
            price=Decimal("200.00"),
            currency="SGD",
            price_date=scenario.position.as_of,
            source="trusted-year-v0-later-price",
        )
    )
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType(valuation.component_type),
        liquidity_class=ManualValuationLiquidityClass(valuation.liquidity_class),
        as_of=valuation.as_of,
        value=Decimal("200000.00"),
        currency="SGD",
        source=valuation.source,
    )
    await db.commit()
    reopened_after_mutation = await get_personal_report_package_snapshot(snapshot.id, db, test_user.id)
    assert reopened_after_mutation.document.model_dump(mode="json") == frozen
    export_after_mutation = await export_personal_report_package_snapshot(
        snapshot.id, db, test_user.id, format=PackageSnapshotExportFormat.JSON
    )
    assert await _stream_body(export_after_mutation) == json_body
