from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

import src.routers.chat as chat_router
from src.advisor import AIAdvisorService
from src.advisor.extension import service as advisor_service_module
from src.workflow.extension.events import ensure_workflow_events_synced
from tests.factories import seed_year_of_journal_entries

SQL_BUDGET = 60


class _StatementCounter:
    def __init__(self, engine) -> None:
        self.count, self._engine = 0, engine.sync_engine
        self._cb = lambda *_a: setattr(self, "count", self.count + 1)

    def __enter__(self) -> _StatementCounter:
        event.listen(self._engine, "before_cursor_execute", self._cb)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._cb)


@pytest.fixture
def advisor_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    warnings: list[str] = []
    inner = advisor_service_module.logger
    monkeypatch.setattr(
        advisor_service_module,
        "logger",
        type(
            "_Recorder",
            (),
            {
                "warning": lambda _s, ev, *a, **kw: (warnings.append(ev), inner.warning(ev, *a, **kw)),
                "__getattr__": lambda _s, name: getattr(inner, name),
            },
        )(),
    )
    return warnings


async def _seed_and_open_home(client, db: AsyncSession, user_id) -> None:
    await seed_year_of_journal_entries(db, user_id, first_day=date.today() - timedelta(days=364), entry_count=1000)
    assert (await client.get("/workflow/status")).status_code == 200
    await ensure_workflow_events_synced(db, user_id=user_id, base_currency="SGD")
    await db.commit()


async def test_AC_advisor_context_6_sql_budgets_at_year_scale(
    client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch, advisor_warnings: list[str]
) -> None:
    monkeypatch.setattr(chat_router, "SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS", 120.0)
    await _seed_and_open_home(client, db, test_user.id)
    assert (await client.get("/chat/suggestions", params={"include_structured": "true"})).status_code == 200
    with _StatementCounter(db_engine) as sugg_counter:
        response = await client.get("/chat/suggestions", params={"include_structured": "true"})
    structured = response.json()["structured_suggestions"]
    assert (
        response.status_code == 200
        and structured
        and {i["confidence_tier"] for i in structured} >= {"blocked", "stale"}
        and sugg_counter.count < SQL_BUDGET
    )

    service = AIAdvisorService()
    await service.get_financial_context(db, test_user.id, base_currency="SGD")
    with _StatementCounter(db_engine) as ctx_counter:
        context = await service.get_financial_context(db, test_user.id, base_currency="SGD")
    assert (
        context["total_assets"],
        context["total_liabilities"],
        context["balance_sheet_confidence_tier"],
        context["income_statement_confidence_tier"],
        advisor_warnings,
    ) == (
        "SGD 100000.00",
        "SGD 20000.00",
        "DETERMINISTIC",
        "MANUAL_TRUSTED",
        [],
    )
    assert (
        context["monthly_income"] != "SGD 0.00"
        and "[blocked]" in context["advisor_suggestions"]
        and "[stale]" in context["advisor_suggestions"]
        and ctx_counter.count < SQL_BUDGET
    )
