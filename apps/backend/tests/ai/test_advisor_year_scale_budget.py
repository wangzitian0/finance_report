"""SQL budgets of the advisor context at one year of activity (#2583 S7).

Home requests ``/chat/suggestions?include_structured=true`` and the app shell requests
``/workflow/status`` on each page. The backend runs one process, so the CPU of one
request delays every other request. Before #2583 S7 the suggestions request issued
174 SQL statements at 960 transactions: it built a balance sheet, an income statement
and a full package readiness that the suggestions do not read.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

import src.routers.chat as chat_router
from src.advisor import AIAdvisorService
from src.advisor.extension import service as advisor_service_module
from tests.factories import seed_year_of_journal_entries

ENTRY_COUNT = 1000
SUGGESTIONS_SQL_BUDGET = 60
CHAT_CONTEXT_SQL_BUDGET = 60


class _StatementCounter:
    def __init__(self, engine) -> None:
        self.count = 0
        self._engine = engine.sync_engine

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.count += 1

    def __enter__(self) -> _StatementCounter:
        event.listen(self._engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._on_execute)


class _FallbackRecorder:
    """Record the warnings of the advisor service and forward every logger call.

    Each advisor read logs a warning and returns a stub when it fails. A stub sends fewer
    statements, so a budget test must also prove that no read fell back.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.warnings: list[str] = []

    def warning(self, event: str, *args: object, **kwargs: object) -> None:
        self.warnings.append(event)
        self._inner.warning(event, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


@pytest.fixture
def advisor_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorder = _FallbackRecorder(advisor_service_module.logger)
    monkeypatch.setattr(advisor_service_module, "logger", recorder)
    return recorder.warnings


async def _seed_and_open_home(client, db: AsyncSession, user_id) -> None:
    await seed_year_of_journal_entries(
        db, user_id, first_day=date.today() - timedelta(days=364), entry_count=ENTRY_COUNT
    )
    # The app shell reads the workflow status first. The read derives and stores readiness.
    status = await client.get("/workflow/status")
    assert status.status_code == 200, status.text


async def test_AC_advisor_context_6_structured_suggestions_within_sql_budget_at_year_scale(
    client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch, advisor_warnings: list[str]
) -> None:
    """AC-advisor.context.6: at 1000 entries, after the app shell read the workflow status,
    ``GET /chat/suggestions?include_structured=true`` issues fewer than 60 SQL statements.
    Main at ``61760e8a`` issued 113 here (174 in the #2583 probe at 960 transactions)."""
    # A slow CI host must not hit the 2 s cap: a timeout returns no structured suggestions
    # and fewer statements, which would make this budget pass with an empty result.
    monkeypatch.setattr(chat_router, "SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS", 120.0)
    await _seed_and_open_home(client, db, test_user.id)
    warm_up = await client.get("/chat/suggestions", params={"include_structured": "true"})
    assert warm_up.status_code == 200, warm_up.text

    with _StatementCounter(db_engine) as counter:
        response = await client.get("/chat/suggestions", params={"include_structured": "true"})

    assert response.status_code == 200, response.text
    structured = response.json()["structured_suggestions"]
    assert structured, "the structured suggestions are empty: the advisor context did not finish"
    # The legacy manual entries are unproven inputs, so readiness is blocked. USD/SGD has no stored rate.
    assert {item["confidence_tier"] for item in structured} >= {"blocked", "stale"}
    assert advisor_warnings == [], f"an advisor read fell back to a stub: {advisor_warnings}"
    assert counter.count < SUGGESTIONS_SQL_BUDGET, f"structured suggestions issued {counter.count} SQL statements"


async def test_AC_advisor_context_6_chat_context_within_sql_budget_at_year_scale(
    client, db: AsyncSession, db_engine, test_user, advisor_warnings: list[str]
) -> None:
    """AC-advisor.context.6: at 1000 entries, after the app shell read the workflow status,
    the ``/chat`` answer context (``get_financial_context``) issues fewer than 60 SQL statements.
    Main at ``61760e8a`` issued 112 here."""
    await _seed_and_open_home(client, db, test_user.id)
    service = AIAdvisorService()
    await service.get_financial_context(db, test_user.id)

    with _StatementCounter(db_engine) as counter:
        context = await service.get_financial_context(db, test_user.id)

    # 800 salary entries of 100.00 and 200 card charges of 100.00, all into the bank.
    assert context["total_assets"] == "SGD 100000.00"
    assert context["total_liabilities"] == "SGD 20000.00"
    # The summary reads catch a ReportError without a warning. A failed read gives this tier.
    assert context["balance_sheet_confidence_tier"] == "DETERMINISTIC"
    assert context["income_statement_confidence_tier"] == "DETERMINISTIC"
    # Each month holds salary entries, today included, so the month-to-date income is above zero.
    assert context["monthly_income"] != "SGD 0.00"
    assert "[blocked]" in context["advisor_suggestions"]
    assert "[stale]" in context["advisor_suggestions"]
    assert advisor_warnings == [], f"an advisor read fell back to a stub: {advisor_warnings}"
    assert counter.count < CHAT_CONTEXT_SQL_BUDGET, f"chat context issued {counter.count} SQL statements"
