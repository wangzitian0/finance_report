from __future__ import annotations; import inspect; from datetime import UTC, date, datetime, timedelta; from decimal import Decimal; from pathlib import Path; from uuid import uuid4; import pytest; from httpx import AsyncClient; from sqlalchemy import event, insert, select, update; from sqlalchemy.ext.asyncio import AsyncSession; import src.reporting.extension.package_document as package_document_mod; import src.workflow.extension.events as workflow_events; from src.audit import JournalEntrySourceType, Money; from src.extraction import BankStatementStatus, DocumentType, Stage1Status, UploadedDocument; from src.extraction.orm.statement_summary import StatementSummary; from src.identity import User; from src.ledger import Account, AccountType, Direction, Entry, JournalEntry, JournalEntryAuthorityState, JournalEntryStatus, JournalLine, post_entry; from src.pricing import FxRate; from src.workflow import WorkflowEvent, WorkflowEventFamily, WorkflowEventStatus, stored_package_readiness; from src.workflow.extension.events import ensure_workflow_events_synced, workflow_input_stamp; YEAR_SCALE_ENTRY_COUNT = 1000; STEADY_READ_SQL_BUDGET = 40; _WRITE_PREFIXES = ('INSERT', 'UPDATE', 'DELETE')
class _SqlCounter:
    def __init__(self) -> None: self.statements: list[str] = []
    def __call__(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None: self.statements.append(statement.lstrip())
    @property
    def writes(self) -> list[str]: return [statement for statement in self.statements if statement[:6].upper() in _WRITE_PREFIXES]
async def _seed_year_of_manual_entries(db: AsyncSession, user_id) -> None:
    bank = Account(user_id=user_id, name='Bank', code='1001', type=AccountType.ASSET, currency='SGD'); salary = Account(user_id=user_id, name='Salary', code='4001', type=AccountType.INCOME, currency='SGD'); db.add_all([bank, salary]); await db.flush(); now = datetime.now(UTC); today = date.today(); entries = []; lines = []
    for index in range(YEAR_SCALE_ENTRY_COUNT): entry_id = uuid4(); entries.append({'id': entry_id, 'user_id': user_id, 'entry_date': today - timedelta(days=index % 360), 'memo': f'txn {index}', 'source_type': JournalEntrySourceType.MANUAL, 'source_id': None, 'decision_anchor_id': None, 'decision_authority_state': JournalEntryAuthorityState.LEGACY_UNPROVEN, 'status': JournalEntryStatus.POSTED, 'void_reason': None, 'void_reversal_entry_id': None, 'created_at': now, 'updated_at': now}); [lines.append({'id': uuid4(), 'journal_entry_id': entry_id, 'account_id': account.id, 'direction': direction, 'amount': Decimal('100.00'), 'currency': 'SGD', 'fx_rate': None, 'event_type': None, 'tags': None, 'line_no': line_no, 'created_at': now, 'updated_at': now}) for line_no, (account, direction) in enumerate(((bank, Direction.DEBIT), (salary, Direction.CREDIT)))]
    await db.execute(insert(JournalEntry), entries); await db.execute(insert(JournalLine), lines); await db.commit()
async def test_AC_workflow_sync_1_year_scale_status_read_is_bounded_and_write_free(client: AsyncClient, db: AsyncSession, db_engine, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-workflow.sync.1'; await _seed_year_of_manual_entries(db, test_user.id); real_traceability = package_document_mod.build_personal_report_package_traceability_payload; traceability_calls = 0
    async def counting_traceability(**kwargs): nonlocal traceability_calls; traceability_calls += 1; return await real_traceability(**kwargs)
    monkeypatch.setattr(package_document_mod, 'build_personal_report_package_traceability_payload', counting_traceability)
    cold_counter = _SqlCounter(); event.listen(db_engine.sync_engine, 'before_cursor_execute', cold_counter)
    try: first = await client.get('/workflow/status')
    finally: event.remove(db_engine.sync_engine, 'before_cursor_execute', cold_counter)
    assert first.status_code == 200, first.text; assert first.json()['report_readiness']['state'] == 'blocked'; assert traceability_calls == 0; assert cold_counter.writes == []
    await ensure_workflow_events_synced(db, user_id=test_user.id); await db.commit()
    synced_baseline = None
    for _ in range(2):
        counter = _SqlCounter(); event.listen(db_engine.sync_engine, 'before_cursor_execute', counter)
        try: repeated = await client.get('/workflow/status')
        finally: event.remove(db_engine.sync_engine, 'before_cursor_execute', counter)
        assert repeated.status_code == 200, repeated.text
        payload = repeated.json()
        if synced_baseline is None:
            synced_baseline = payload
            assert payload['primary_state'] == first.json()['primary_state']
            assert payload['report_readiness'] == first.json()['report_readiness']
            assert payload['event_counts'] == first.json()['event_counts']
        else:
            assert payload == synced_baseline
        assert traceability_calls == 0; assert counter.writes == []; assert len(counter.statements) < STEADY_READ_SQL_BUDGET, counter.statements
async def _make_statement(db: AsyncSession, user_id, *, status: BankStatementStatus) -> StatementSummary: document = UploadedDocument(user_id=user_id, file_path='statements/fresh.csv', file_hash='f' * 64, original_filename='fresh.csv', document_type=DocumentType.BANK_STATEMENT); db.add(document); await db.flush(); statement = StatementSummary(user_id=user_id, uploaded_document_id=document.id, file_hash='f' * 64, institution='Demo Bank', status=status); db.add(statement); await db.commit(); return statement
async def _event_states(db: AsyncSession, user_id) -> dict[WorkflowEventFamily, WorkflowEventStatus]: db.expire_all(); events = (await db.execute(select(WorkflowEvent).where(WorkflowEvent.user_id == user_id))).scalars().all(); return {item.family: item.status for item in events}
async def test_AC_workflow_sync_2_a_source_change_derives_events_again(client: AsyncClient, db: AsyncSession, db_engine, test_user: User) -> None:
    'AC-workflow.sync.2'; user_id = test_user.id; counter = _SqlCounter(); event.listen(db_engine.sync_engine, 'before_cursor_execute', counter)
    try:
        empty = await client.get('/workflow/status'); assert empty.status_code == 200, empty.text; assert empty.json()['primary_state'] == 'empty'
        statement_id = (await _make_statement(db, user_id, status=BankStatementStatus.PARSED)).id
        counter.statements.clear(); needs_review = await client.get('/workflow/status'); assert needs_review.json()['next_action']['type'] == 'review_required'
        needs_events = await client.get('/workflow/events'); assert needs_events.status_code == 200, needs_events.text; assert {item['family']: item['status'] for item in needs_events.json()['items']}[WorkflowEventFamily.REVIEW_REQUIRED.value] == WorkflowEventStatus.UNREAD.value
        assert counter.writes == []
    finally: event.remove(db_engine.sync_engine, 'before_cursor_execute', counter)
    assert await _event_states(db, user_id) == {}
    await ensure_workflow_events_synced(db, user_id=user_id); await db.commit(); assert (await _event_states(db, user_id))[WorkflowEventFamily.REVIEW_REQUIRED] == WorkflowEventStatus.UNREAD
    await db.execute(update(StatementSummary).where(StatementSummary.id == statement_id).values(stage1_status=Stage1Status.APPROVED, stage1_reviewed_at=datetime.now(UTC))); await db.commit()
    read_counter = _SqlCounter(); event.listen(db_engine.sync_engine, 'before_cursor_execute', read_counter)
    try:
        events = await client.get('/workflow/events'); assert events.status_code == 200, events.text
        families = {item['family']: item['status'] for item in events.json()['items']}
        assert WorkflowEventFamily.REVIEW_REQUIRED.value not in families; assert families[WorkflowEventFamily.REVIEW_COMPLETED.value] == WorkflowEventStatus.UNREAD.value
        assert (await client.get('/workflow/status')).json()['next_action']['type'] != 'review_required'
    finally: event.remove(db_engine.sync_engine, 'before_cursor_execute', read_counter)
    assert read_counter.writes == []
    await ensure_workflow_events_synced(db, user_id=user_id); await db.commit(); states = await _event_states(db, user_id)
    assert states[WorkflowEventFamily.REVIEW_REQUIRED] == WorkflowEventStatus.ARCHIVED; assert states[WorkflowEventFamily.REVIEW_COMPLETED] == WorkflowEventStatus.UNREAD
@pytest.mark.no_db
def test_AC_workflow_sync_3_workflow_reads_use_readonly_session_without_table_scan() -> None:
    'AC-workflow.sync.3'; import src.routers.workflow as workflow_router
    backend_src = Path(__file__).resolve().parents[2] / 'src'
    assert not (backend_src / 'workflow/extension/source_fingerprint.py').exists()
    events_src = (backend_src / 'workflow/extension/events.py').read_text(encoding='utf-8')
    assert 'Base.metadata.tables' not in events_src; assert 'source_fingerprint' in events_src
    for endpoint in (workflow_router.get_workflow_status_endpoint, workflow_router.list_workflow_events_endpoint):
        assert 'ReadCtx' in inspect.getsource(endpoint)
async def test_AC_workflow_sync_4_input_stamp_changes_only_with_relevant_inputs(db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-workflow.sync.4'
    async def stamp() -> str: await db.commit(); return await workflow_input_stamp(db, user_id=test_user.id)
    baseline = await stamp(); assert await stamp() == baseline; other = User(id=uuid4(), email=f'other-{uuid4()}@example.com', hashed_password='hashed'); db.add(other); await db.flush(); db.add(Account(user_id=other.id, name='Other bank', type=AccountType.ASSET, currency='SGD')); assert await stamp() == baseline; db.add(WorkflowEvent(user_id=test_user.id, family=WorkflowEventFamily.REPORT_READY, severity='info', title='Ready', summary='Ready', source_type='report_package', source_id=uuid4(), action_href='/reports?tab=package', dedupe_key='excluded-table-probe')); assert await stamp() == baseline; seen = {baseline}
    async def assert_changed() -> None: current = await stamp(); assert current not in seen; seen.add(current)
    account = Account(user_id=test_user.id, name='Bank', type=AccountType.ASSET, currency='SGD'); db.add(account); await assert_changed(); account.name = 'Renamed bank'; await assert_changed(); entry = JournalEntry(user_id=test_user.id, entry_date=date.today(), memo='Owner-joined probe', source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.DRAFT); db.add(entry); await db.flush(); line = JournalLine(journal_entry_id=entry.id, account_id=account.id, direction=Direction.DEBIT, amount=Decimal('1.00'), currency='SGD'); db.add(line); await assert_changed(); line.amount = Decimal('2.00'); await assert_changed(); db.add(FxRate(base_currency='TST', quote_currency='XYZ', rate=Decimal('1.5'), rate_date=date.today(), source='t')); await assert_changed(); test_user.base_currency = 'USD'; await assert_changed()
    class _Tomorrow(date):
        @classmethod
        def today(cls) -> date: return date.today() + timedelta(days=1)
    monkeypatch.setattr(workflow_events, 'date', _Tomorrow); await assert_changed()
async def test_AC_workflow_sync_4_tenant_scope_matches_stored_trace_records(db: AsyncSession, test_user: User) -> None: 'AC-workflow.sync.4'; bank = Account(user_id=test_user.id, name='Bank', type=AccountType.ASSET, currency='SGD'); income = Account(user_id=test_user.id, name='Salary', type=AccountType.INCOME, currency='SGD'); db.add_all((bank, income)); await db.flush(); before = await workflow_input_stamp(db, user_id=test_user.id); await post_entry(db, user_id=test_user.id, entry_date=date.today(), memo='Anchored entry', entry=Entry.transfer(debit=bank.id, credit=income.id, money=Money(Decimal('10'), 'SGD'))); await db.commit(); after = await workflow_input_stamp(db, user_id=test_user.id); assert after != before
async def test_AC_workflow_sync_5_a_state_older_than_the_max_age_derives_again(db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-workflow.sync.5'; from src.workflow.extension.events import WORKFLOW_SYNC_STATE_MAX_AGE, ensure_workflow_events_synced; from src.workflow.orm.models import WorkflowSyncState; user_id = test_user.id; real_readiness = workflow_events.current_package_readiness; derivations = 0
    async def counting_readiness(db, *, user_id): nonlocal derivations; derivations += 1; return await real_readiness(db, user_id=user_id)
    monkeypatch.setattr(workflow_events, 'current_package_readiness', counting_readiness); await ensure_workflow_events_synced(db, user_id=user_id); await db.commit(); assert derivations == 1; await ensure_workflow_events_synced(db, user_id=user_id); await db.commit(); assert derivations == 1; await db.execute(update(WorkflowSyncState).where(WorkflowSyncState.user_id == user_id).values(updated_at=datetime.now(UTC) - WORKFLOW_SYNC_STATE_MAX_AGE - timedelta(minutes=1))); await db.commit(); await ensure_workflow_events_synced(db, user_id=user_id); await db.commit(); assert derivations == 2
async def test_AC_workflow_sync_7_report_error_becomes_blocked_readiness_state(db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-workflow.sync.7'; from src.reporting import ReportError; from src.workflow import WorkflowPrimaryState, WorkflowReportReadinessState, get_workflow_status
    async def failing_readiness(db, *, user_id): raise ReportError('No registered L1 mapping for ledger account 00000000-0000-0000-0000-000000000001')
    monkeypatch.setattr(workflow_events, 'current_package_readiness', failing_readiness); status = await get_workflow_status(db, user_id=test_user.id); assert status.primary_state == WorkflowPrimaryState.BLOCKED; assert status.report_readiness.state == WorkflowReportReadinessState.BLOCKED; assert status.report_readiness.blocking_count == 1; assert status.report_readiness.href == '/reports?tab=package'; await ensure_workflow_events_synced(db, user_id=test_user.id); await db.commit(); cached = await stored_package_readiness(db, user_id=test_user.id); assert cached is not None; assert cached['state'] == 'blocked'; assert cached['blocking_count'] == 1; assert cached['blockers'][0]['code'] == 'report_generation_error'; assert 'No registered L1 mapping' in cached['blockers'][0]['reason']
