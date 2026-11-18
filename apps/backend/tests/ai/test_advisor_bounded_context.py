from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor import AIAdvisorService, register_fx_pairs_read
from src.advisor.base.constants import CHAT_METADATA_SAFE_HREFS
from src.advisor.extension import service as advisor_service_module
from tests.ai.conftest import aret, fake_market_data_item, fake_portfolio_summary, fake_readiness_payload, fake_workflow_status

BOUNDED_CONTEXT_KEYS = {"financial_summary", "report_readiness", "authority_coverage", "workflow", "market_data", "portfolio", "cash_flow", "suggestions"}
BOUNDED_SOURCE_REFS = BOUNDED_CONTEXT_KEYS - {"suggestions"} | {"reconciliation"}
FINANCIAL_SUMMARY = {"monthly_income": "SGD 5000.00", "monthly_expenses": "SGD 3000.00", "top_expenses": "Dining: SGD 500.00", "unmatched_count": "1", "pending_review": "2"}


@pytest.fixture
def bounded_context_fakes(test_user, monkeypatch: pytest.MonkeyPatch):
    workflow_calls: list[dict | None] = []
    payload = fake_readiness_payload("port_sentinel_blocker", 1, "/reports?tab=package")

    async def fake_workflow(_db: AsyncSession, *, user_id, synced_package_readiness=None, base_currency=None):
        assert user_id == test_user.id
        workflow_calls.append(synced_package_readiness)
        return fake_workflow_status(blocking_count=1)

    register_fx_pairs_read(lambda _db, _uid, *, include_default=True: aret([("USD", "SGD")]))
    monkeypatch.setattr(advisor_service_module, "current_package_readiness", lambda _db, *, user_id, base_currency=None: aret(SimpleNamespace(model_dump=lambda mode="json": payload)))
    monkeypatch.setattr(advisor_service_module, "get_workflow_status", fake_workflow)
    monkeypatch.setattr(advisor_service_module, "get_market_data_status", lambda _db, *, pairs, symbols: aret([fake_market_data_item()]))
    monkeypatch.setattr(advisor_service_module, "active_stock_symbols", lambda _db, _uid: aret(["AAPL"]))
    monkeypatch.setattr(advisor_service_module.PortfolioService, "get_portfolio_summary", lambda _s, _db, user_id, as_of_date=None, base_currency=None: aret(fake_portfolio_summary()))
    return {"workflow_calls": workflow_calls, "payload": payload}


async def test_AC_advisor_context_1_bounded_read_set_and_citations(db: AsyncSession, test_user, bounded_context_fakes) -> None:
    service = AIAdvisorService()
    context = await service.get_advisor_context(db, test_user.id, financial_context=dict(FINANCIAL_SUMMARY), base_currency="SGD")
    assert (set(context), context["report_readiness"]["blocking_count"], context["authority_coverage"]["blocker_codes"], bounded_context_fakes["workflow_calls"], bool(context["suggestions"])) == (
        BOUNDED_CONTEXT_KEYS, 1, ["port_sentinel_blocker"], [{**bounded_context_fakes["payload"], "document_status": "draft"}], True,
    )
    assert all(i["basis"] and i["source_refs"] and set(i["source_refs"]) <= BOUNDED_SOURCE_REFS and i["next_action_href"].startswith("/") for i in context["suggestions"])

    metadata = service.build_chat_grounding_metadata(
        {**FINANCIAL_SUMMARY, "balance_sheet_confidence_tier": "DETERMINISTIC", "income_statement_confidence_tier": "DETERMINISTIC", "advisor_context": json.dumps(context, sort_keys=True, default=str)},
        "Why is my net worth down?",
    )
    safe_hrefs, known_refs = set(CHAT_METADATA_SAFE_HREFS), BOUNDED_SOURCE_REFS | {"balance_sheet.total_equity", "income_statement.current_month"}
    assert metadata.grounded is True and metadata.citations
    assert all(c.href in safe_hrefs and c.source_ref in known_refs for c in metadata.citations) and all(a.href in safe_hrefs for a in metadata.actions)
