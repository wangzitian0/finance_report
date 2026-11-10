from __future__ import annotations; from datetime import date, timedelta; import pytest; from sqlalchemy import event; from sqlalchemy.ext.asyncio import AsyncSession; import src.routers.chat as chat_router; from src.advisor import AIAdvisorService; from src.advisor.extension import service as advisor_service_module; from tests.factories import seed_year_of_journal_entries; ENTRY_COUNT = 1000; SUGGESTIONS_SQL_BUDGET = 60; CHAT_CONTEXT_SQL_BUDGET = 60
class _StatementCounter:
    def __init__(self, engine) -> None: self.count = 0; self._engine = engine.sync_engine
    def _on_execute(self, conn, cursor, statement, parameters, context, executemany) -> None: self.count += 1
    def __enter__(self) -> _StatementCounter: event.listen(self._engine, 'before_cursor_execute', self._on_execute); return self
    def __exit__(self, *_exc: object) -> None: event.remove(self._engine, 'before_cursor_execute', self._on_execute)
class _FallbackRecorder:
    def __init__(self, inner) -> None: self._inner = inner; self.warnings: list[str] = []
    def warning(self, event: str, *args: object, **kwargs: object) -> None: self.warnings.append(event); self._inner.warning(event, *args, **kwargs)
    def __getattr__(self, name: str): return getattr(self._inner, name)
@pytest.fixture
def advisor_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]: recorder = _FallbackRecorder(advisor_service_module.logger); monkeypatch.setattr(advisor_service_module, 'logger', recorder); return recorder.warnings
async def _seed_and_open_home(client, db: AsyncSession, user_id) -> None: await seed_year_of_journal_entries(db, user_id, first_day=date.today() - timedelta(days=364), entry_count=ENTRY_COUNT); status = await client.get('/workflow/status'); assert status.status_code == 200, status.text
async def test_AC_advisor_context_6_structured_suggestions_within_sql_budget_at_year_scale(client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch, advisor_warnings: list[str]) -> None:
    'AC-advisor.context.6'; monkeypatch.setattr(chat_router, 'SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS', 120.0); await _seed_and_open_home(client, db, test_user.id); warm_up = await client.get('/chat/suggestions', params={'include_structured': 'true'}); assert warm_up.status_code == 200, warm_up.text
    with _StatementCounter(db_engine) as counter: response = await client.get('/chat/suggestions', params={'include_structured': 'true'})
    assert response.status_code == 200, response.text; structured = response.json()['structured_suggestions']; assert structured, 'the structured suggestions are empty: the advisor context did not finish'; assert {item['confidence_tier'] for item in structured} >= {'blocked', 'stale'}; assert advisor_warnings == [], f'an advisor read fell back to a stub: {advisor_warnings}'; assert counter.count < SUGGESTIONS_SQL_BUDGET, f'structured suggestions issued {counter.count} SQL statements'
async def test_AC_advisor_context_6_chat_context_within_sql_budget_at_year_scale(client, db: AsyncSession, db_engine, test_user, advisor_warnings: list[str]) -> None:
    'AC-advisor.context.6'; await _seed_and_open_home(client, db, test_user.id); service = AIAdvisorService(); await service.get_financial_context(db, test_user.id)
    with _StatementCounter(db_engine) as counter: context = await service.get_financial_context(db, test_user.id)
    assert context['total_assets'] == 'SGD 100000.00'; assert context['total_liabilities'] == 'SGD 20000.00'; assert context['balance_sheet_confidence_tier'] == 'DETERMINISTIC'; assert context['income_statement_confidence_tier'] == 'MANUAL_TRUSTED'; assert context['monthly_income'] != 'SGD 0.00'; assert '[blocked]' in context['advisor_suggestions']; assert '[stale]' in context['advisor_suggestions']; assert advisor_warnings == [], f'an advisor read fell back to a stub: {advisor_warnings}'; assert counter.count < CHAT_CONTEXT_SQL_BUDGET, f'chat context issued {counter.count} SQL statements'
