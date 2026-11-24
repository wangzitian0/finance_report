from __future__ import annotations

import asyncio, hashlib, os
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from common.audit.base import TraceRecord as CommonTraceRecord
from common.audit.extension import TraceRecordCodec as CommonTraceRecordCodec
from common.testing.ac_proof import PROOF_ATTR, ac_proof
from sqlalchemy import select
from src.audit import (
    SqlTraceRecordRepository,
    TerminalAuditSpec,
    TerminalAuditVerifier,
    TraceDecisionPolicyRegistry,
    TraceDecisionRef,
    TraceEmitter,
    TraceRecord,
    TraceRecordCodec as BackendTraceRecordCodec,
    TraceRecordPersistenceError,
    TraceRecordType,
    TraceResult,
    TraceScope,
    VersionedTraceRef,
    current_authoritative_trace_decision_projection,
)
from src.audit.money import Money
from src.audit.orm.trace_record import TraceRecordParentRow, TraceRecordRow
from src.config import settings
from src.database import create_session_maker_from_db
from src.deps import PaginationParams
from src.extraction import (
    BankStatementStatus,
    DocumentType,
    ExtractedPositionFact,
    ExtractionMethod,
    ParseJob,
    ReviewedStatementEnvelopeCommand,
    RuleType,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
    StatementSummary,
    UploadedDocument,
    confirm_reviewed_statement_envelope,
    extraction_trace_policy_registry,
    persist_statement_extraction_result,
)
from src.extraction.extension import transaction_classification
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import (
    approve_statement_with_transactions,
    resolve_statement_transactions,
)
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.ledger import (
    Account,
    AccountType,
    Entry,
    initialize_opening_positions,
    ledger_trace_policy_registry,
    post_entry,
)
from src.pricing import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    pricing_trace_policy_registry,
    record_manual_valuation,
)
from src.pricing.orm.market_data import StockPrice
from src.reporting import PackageAssembler, personal_report_package_decision_ref
from src.reporting.base.package_decision import PackageReadinessDecisionPolicy
from src.request_context import RequestContext
from src.routers.portfolio import import_brokerage_positions
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
    get_personal_report_package_snapshot,
    list_personal_report_package_snapshots,
)
from src.schemas import (
    PersonalReportingFrameworkId,
    PersonalReportPackageGenerateRequest,
    PersonalReportPackageReadinessState,
    PersonalReportPackageSnapshotStatus,
)
from src.schemas.portfolio import BrokerageImportRequest
from tests._support.executed_proof import executed_proof_assertion_version, register_executed_proof_consumer
from tests._support.trusted_year import TRUSTED_YEAR_SCENARIO
from tests.statement_ingestion import execute_statement_ingestion, posting_dependencies, run_for


class _FrozenTraceRepository:
    def __init__(self, records: tuple[TraceRecord, ...]) -> None:
        self._records = {r.record_id: r for r in records}

    async def get(self, scope, record_id):
        record = self._records.get(record_id)
        return record if record is not None and record.scope == scope else None


def _bank_csv() -> bytes:
    return (
        b"Statement Currency,Date,Description,Debit Amount,Credit Amount\n"
        b"SGD,2026-06-05,Salary credit,,5000.00\n"
        b"SGD,2026-06-10,Rent debit,1000.00,\n"
        b"SGD,2026-06-15,Buy security,1000.00,\n"
    )


async def _ingest_reviewed_bank_statement(db, *, user_id, bank: Account, securities_id) -> None:
    content = _bank_csv()
    digest = hashlib.sha256(content).hexdigest()
    statement = StatementSummary(
        user_id=user_id, file_hash=digest, institution="DBS", status=BankStatementStatus.UPLOADED
    )
    db.add(statement)
    await db.flush()
    statement_id = statement.id
    await db.commit()
    await execute_statement_ingestion(
        ParseJob(
            statement_id=statement_id,
            run_id=await run_for(db, statement_id),
            filename="trusted-year-v0.csv",
            institution="DBS",
            user_id=user_id,
            account_id=bank.id,
            file_hash=digest,
            storage_key="trusted-year/v0.csv",
        ),
        content=content,
        session_maker=create_session_maker_from_db(db),
    )
    db.expire_all()
    statement = await db.get(StatementSummary, statement_id)
    transactions = await resolve_statement_transactions(db, statement)
    inv_txn = next(t for t in transactions if t.description == "Buy security")
    await post_entry(
        db,
        user_id=user_id,
        entry_date=inv_txn.txn_date,
        memo="TrustedYearScenario v0 investment purchase",
        source_id=inv_txn.id,
        operation="trusted-year-investment-purchase",
        entry=Entry.transfer(
            debit=securities_id,
            credit=bank.id,
            money=Money(inv_txn.amount, inv_txn.currency),
            event_type="investment_buy",
            tags={"asset_identifier": TRUSTED_YEAR_SCENARIO.position.symbol},
        ),
        base_currency="SGD",
    )
    source_record = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    (
        statement.account_id,
        statement.currency,
        statement.period_start,
        statement.period_end,
        statement.opening_balance,
        statement.closing_balance,
    ) = (
        bank.id,
        "SGD",
        min(t.txn_date for t in transactions),
        max(t.txn_date for t in transactions),
        TRUSTED_YEAR_SCENARIO.opening_cash,
        TRUSTED_YEAR_SCENARIO.expected.ending_cash,
    )
    await db.flush()
    await confirm_reviewed_statement_envelope(
        db,
        user_id=user_id,
        statement_id=statement.id,
        command=ReviewedStatementEnvelopeCommand(
            source_result_digest=source_record.content_digest,
            account_id=bank.id,
            currency="SGD",
            period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=statement.opening_balance,
            closing_balance=statement.closing_balance,
            rationale="TrustedYearScenario v0 reviewed source envelope.",
        ),
        trace_emitter=TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())),
    )
    approved, approved_txns = await approve_statement_with_transactions(db, statement.id, user_id)
    outcome = await auto_create_posted_entries_for_statement(
        db,
        approved,
        user_id,
        dependencies=replace(
            posting_dependencies(), transfer_exclusions=lambda _db, ids: _async_set({inv_txn.id} & set(ids))
        ),
        transactions=approved_txns,
    )
    assert (outcome.review_reasons, outcome.created_count) == ((), 2)


async def _async_set(val):
    return val


async def _import_brokerage_position(db, *, user_id) -> None:
    pos = TRUSTED_YEAR_SCENARIO.position
    digest = hashlib.sha256(f"trusted-year-v0:{pos.institution}:{pos.symbol}".encode()).hexdigest()
    result = StatementExtractionResult.create(
        producer_version="trusted-year-v0@1",
        source_content_digest=digest,
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        institution=pos.institution,
        account_last4="2026",
        period_start=pos.as_of,
        period_end=pos.as_of,
        balances=(),
        transactions=(),
        positions=(
            ExtractedPositionFact(
                fact_id="trusted-year-v0-aapl",
                symbol=pos.symbol,
                quantity=pos.quantity,
                market_value=pos.source_value,
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
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="trusted-year-v0-brokerage", model="v1"
        ),
        statement_currency="SGD",
    )
    doc = UploadedDocument(
        user_id=user_id,
        file_path=f"memory://trusted-year/{digest}",
        file_hash=digest,
        original_filename="trusted-year-v0-moomoo.csv",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    statement = StatementSummary(
        user_id=user_id,
        uploaded_document_id=doc.id,
        file_hash=digest,
        institution=pos.institution,
        account_last4="2026",
        currency="SGD",
        period_start=pos.as_of,
        period_end=pos.as_of,
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
        db, statement=statement, result=result, source_trace_record_id=traces[0].record_id
    )
    await db.commit()
    imported = await import_brokerage_positions(
        BrokerageImportRequest(statement_id=statement.id), RequestContext(db, user_id)
    )
    assert (imported.parsed_positions, imported.created_atomic_positions) == (1, 1)


async def _stream_body(response) -> str:
    return "".join([c.decode() if isinstance(c, bytes) else c async for c in response.body_iterator])


async def _supersede_selected_authority_parents(db, *, user_id, document) -> None:
    decision_ids = {entry.decision_id for entry in document.input_manifest}
    proj = current_authoritative_trace_decision_projection(TraceScope.tenant(user_id)).subquery(
        "trusted_year_current_decisions"
    )
    assert (
        set((await db.execute(select(proj.c.decision_id).where(proj.c.decision_id.in_(decision_ids)))).scalars())
        == decision_ids
    )
    obs_ids, frontier, visited = set(), decision_ids, set(decision_ids)
    while frontier:
        unseen = (
            set(
                (
                    await db.execute(
                        select(TraceRecordParentRow.parent_id).where(TraceRecordParentRow.record_id.in_(frontier))
                    )
                ).scalars()
            )
            - visited
        )
        if not unseen:
            break
        rows = (
            await db.execute(select(TraceRecordRow.id, TraceRecordRow.record_type).where(TraceRecordRow.id.in_(unseen)))
        ).all()
        obs_ids.update(rid for rid, rt in rows if rt is TraceRecordType.OBSERVATION)
        frontier = {rid for rid, rt in rows if rt is TraceRecordType.DECISION}
        visited.update(unseen)
    repo = SqlTraceRecordRepository(db)
    parents = [
        p for pid in sorted(obs_ids, key=str) if (p := await repo.get(TraceScope.tenant(user_id), pid)) is not None
    ]
    assert obs_ids and {p.record_id for p in parents} == obs_ids
    correction = lambda parent, *, scope, target_id, suffix: TraceRecord.observation(
        scope=scope,
        target=VersionedTraceRef(parent.target.kind, target_id, f"{parent.target.version}:{suffix}"),
        target_class=parent.target_class,
        assertion=parent.assertion,
        authority=parent.authority,
        result=TraceResult.UNPROVEN,
        execution_id=f"trusted-year-v0:{suffix}:{parent.record_id}",
        evidence_manifest_digest=hashlib.sha256(f"trusted-year-v0:{suffix}:{parent.record_id}".encode()).hexdigest(),
        occurred_at=datetime.now(UTC),
        score=None,
        reason_code="trusted_year_authority_counterfactual",
        supersedes_id=parent.record_id,
    )
    first = parents[0]
    for scope, tid, suffix, err in (
        (TraceScope.tenant(uuid4()), first.target.id, "cross-scope", "cross-scope"),
        (first.scope, f"{first.target.id}:mismatch", "target-mismatch", "lineage"),
    ):
        with pytest.raises(TraceRecordPersistenceError, match=err):
            await repo.append(correction(first, scope=scope, target_id=tid, suffix=suffix))
    for parent in parents:
        await repo.append(correction(parent, scope=parent.scope, target_id=parent.target.id, suffix="superseded"))


@ac_proof(
    "trusted-year-v0-terminal",
    ac_ids=["AC-testing.trusted-year.2", "AC-testing.trusted-year.3", "AC-testing.package-lifecycle.1"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["bank_statement", "brokerage_statement"],
    scenario_id="trusted-year-v0",
    oracle_kind="independent_decimal",
    required_observation_kind="terminal_audit",
    issue="#696",
)
async def test_trusted_year_deterministic_executor_proves_package_lifecycle(
    db, test_user, monkeypatch, request
) -> None:
    scenario, expected = TRUSTED_YEAR_SCENARIO, TRUSTED_YEAR_SCENARIO.expected
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    categories = {"Salary credit": TransactionCategory.SALARY, "Rent debit": TransactionCategory.HOUSING}
    monkeypatch.setattr(
        transaction_classification,
        "propose_categories",
        lambda txns, _p: _async_set(
            [
                CategoryProposal(category=categories[t.description].value, confidence=99, reason="trusted-year-v0")
                for t in txns
            ]
        ),
    )
    bank = Account(user_id=test_user.id, name="DBS", type=AccountType.ASSET, currency="SGD")
    securities = Account(user_id=test_user.id, name="Asset - Securities", type=AccountType.ASSET, currency="SGD")
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
            tag_mappings={"intent": "transfer"},
            default_account_id=securities.id,
        )
    )
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 12, 31),
        balances={bank.id: scenario.opening_cash, securities.id: Decimal("0")},
        currency="SGD",
        memo="TrustedYearScenario v0 opening cash",
        base_currency="SGD",
    )
    await _ingest_reviewed_bank_statement(db, user_id=test_user.id, bank=bank, securities_id=securities.id)
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
    val = scenario.valuation
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType(val.component_type),
        liquidity_class=ManualValuationLiquidityClass(val.liquidity_class),
        as_of=val.as_of,
        value=val.value,
        currency="SGD",
        source=val.source,
    )
    await db.commit()

    snapshot = await generate_personal_report_package_snapshot(
        RequestContext(db, test_user.id),
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            as_of_date=date(2026, 12, 31),
            currency="SGD",
            include_restricted=True,
        ),
    )
    await db.commit()
    doc = snapshot.document
    bs, inc, cf = doc.sections.balance_sheet, doc.sections.income_statement, doc.sections.cash_flow
    assert (snapshot.status, doc.readiness.state, doc.readiness.input_coverage.unproven_input_count) == (
        PersonalReportPackageSnapshotStatus.TRUSTED,
        PersonalReportPackageReadinessState.READY,
        0,
    )
    assert (
        bs.total_assets,
        bs.total_liabilities,
        bs.total_equity,
        bs.net_income,
        bs.net_worth_adjustment_gain_loss,
        bs.is_balanced,
    ) == (
        expected.total_assets,
        expected.total_liabilities,
        expected.ledger_equity,
        expected.net_income,
        expected.net_worth_adjustment,
        True,
    )
    assert (
        bs.assets
        and inc.income
        and inc.expenses
        and inc.net_income == expected.net_income
        and cf.operating
        and cf.investing
        and doc.sections.notes.notes
        and doc.sections.traceability_appendix.lines
    )
    assert (
        cf.summary.ending_cash,
        cf.summary.investing_activities,
        cf.cash_bridge.unclassified_cash,
        cf.proof_state,
        cf.proof_reasons,
    ) == (expected.ending_cash, -expected.investment_purchase, Decimal("0.00"), "proven", [])
    assert (
        next(
            h for h in doc.sections.investment_performance.holdings if h.asset_identifier == scenario.position.symbol
        ).market_value
        == expected.investment_market_value
    )
    assert {ref.partition(":")[0] for e in doc.input_manifest for ref in e.input_refs} == set(
        scenario.expected_manifest
    )
    assert all(
        e.decision_id and e.target_kind and e.target_id and e.assertion_kind and e.authority_tier
        for e in doc.input_manifest
    )

    trace_repo = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry(
            (
                *extraction_trace_policy_registry().policies,
                *ledger_trace_policy_registry().policies,
                *pricing_trace_policy_registry().policies,
                PackageReadinessDecisionPolicy(),
            )
        ),
    )
    scope, proof_decl = (
        TraceScope.tenant(test_user.id),
        getattr(test_trusted_year_deterministic_executor_proves_package_lifecycle, PROOF_ATTR),
    )
    terminal_spec = TerminalAuditSpec(
        scope=scope,
        package=personal_report_package_decision_ref(doc),
        manifest=tuple(
            TraceDecisionRef(
                decision_id=i.decision_id,
                target=VersionedTraceRef(i.target_kind, i.target_id, i.target_version),
                assertion=VersionedTraceRef(i.assertion_kind, i.assertion_id, i.assertion_version),
            )
            for i in doc.input_manifest
        ),
        repository_id="wangzitian0/finance_report",
        commit_sha="a" * 40,
        scenario_id=scenario.scenario_id,
        proof=VersionedTraceRef(
            "executed_proof",
            proof_decl.proof_id,
            executed_proof_assertion_version(
                proof_id=proof_decl.proof_id,
                scenario_id=proof_decl.scenario_id,
                oracle_kind=proof_decl.oracle_kind,
                ac_ids=proof_decl.ac_ids,
                stage=proof_decl.stage,
                task_category=proof_decl.task_category,
                required_observation_kind=proof_decl.required_observation_kind,
            ),
        ),
        execution_id="trusted-year-graph-verification",
    )
    pkg_rec = await TerminalAuditVerifier(trace_repo).verify_graph(terminal_spec)
    graph_records = [
        await trace_repo.get(scope, rid)
        for rid in {pkg_rec.record_id, *pkg_rec.parent_ids, *(i.decision_id for i in terminal_spec.manifest)}
    ]
    assert pkg_rec.record_id == terminal_spec.package.decision_id and all(r is not None for r in graph_records)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        frozen_repo = _FrozenTraceRepository(tuple(graph_records))
        register_executed_proof_consumer(
            request.node,
            lambda executed_proof: CommonTraceRecordCodec.decode(
                BackendTraceRecordCodec.encode(
                    asyncio.run(
                        TerminalAuditVerifier(frozen_repo).audit(
                            replace(
                                terminal_spec,
                                commit_sha=(
                                    bp := BackendTraceRecordCodec.decode(CommonTraceRecordCodec.encode(executed_proof))
                                ).target.version,
                                execution_id=bp.execution_id,
                            ),
                            bp,
                        )
                    )
                )
            ),
        )

    frozen = doc.model_dump(mode="json")
    assert [
        i.id
        for i in await list_personal_report_package_snapshots(
            RequestContext(db, test_user.id), pagination=PaginationParams()
        )
    ] == [snapshot.id]
    assert (
        await get_personal_report_package_snapshot(snapshot.id, RequestContext(db, test_user.id))
    ).document.model_dump(mode="json") == frozen
    json_body = await _stream_body(
        await export_personal_report_package_snapshot(
            snapshot.id, RequestContext(db, test_user.id), format=PackageSnapshotExportFormat.JSON
        )
    )
    csv_body = await _stream_body(
        await export_personal_report_package_snapshot(
            snapshot.id, RequestContext(db, test_user.id), format=PackageSnapshotExportFormat.CSV
        )
    )
    assert str(snapshot.id) in json_body and "115250.00" in json_body and "balance_sheet.total_assets" in csv_body

    cf_tx = await db.begin_nested()
    await _supersede_selected_authority_parents(db, user_id=test_user.id, document=doc)
    cand = await PackageAssembler().assemble(
        db,
        user_id=test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        as_of_date=date(2026, 12, 31),
        currency="SGD",
        include_restricted=True,
    )
    assert (cand.status, cand.readiness.state, cand.package_decision_id) == (
        PersonalReportPackageSnapshotStatus.DRAFT,
        PersonalReportPackageReadinessState.BLOCKED,
        None,
    )
    assert cand.readiness.input_coverage.unproven_input_count > 0 and "unproven_package_input" in {
        b.code for b in cand.readiness.blockers
    }
    await cf_tx.rollback()

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
        component_type=ManualValuationComponentType(val.component_type),
        liquidity_class=ManualValuationLiquidityClass(val.liquidity_class),
        as_of=val.as_of,
        value=Decimal("200000.00"),
        currency="SGD",
        source=val.source,
    )
    await db.commit()
    assert (
        await get_personal_report_package_snapshot(snapshot.id, RequestContext(db, test_user.id))
    ).document.model_dump(mode="json") == frozen
    assert (
        await _stream_body(
            await export_personal_report_package_snapshot(
                snapshot.id, RequestContext(db, test_user.id), format=PackageSnapshotExportFormat.JSON
            )
        )
        == json_body
    )
