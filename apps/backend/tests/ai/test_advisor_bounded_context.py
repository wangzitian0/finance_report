"""AC-advisor.context.1 — answers come only from the bounded read context, with citations.

The bounded read context is the deterministic fact set the advisor may ground
an answer in: reconciliation readiness, report readiness, workflow status,
portfolio positions, market data, and the category/cash-flow summary.  These
tests prove (a) ``get_advisor_context`` assembles **exactly** that set — most
reads go through each owning package's published root (readiness via
``src.reporting``, imported directly into ``service.py``); the one read whose
owner still lives in the app remainder (the fx-pair composer) flows through
the advisor's registered ``app_reads`` port — and (b) the response metadata
carries citations/actions that surface only those grounding sources (safe
hrefs, bounded source_refs).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor import AIAdvisorService, register_fx_pairs_read
from src.advisor.base.constants import CHAT_METADATA_SAFE_HREFS
from src.advisor.extension import service as advisor_service_module
from src.schemas.workflow import (
    WorkflowEventCountsResponse,
    WorkflowNextActionResponse,
    WorkflowNextActionType,
    WorkflowPrimaryState,
    WorkflowReportReadinessResponse,
    WorkflowReportReadinessState,
    WorkflowStatusResponse,
)

#: The bounded read context — the ONLY top-level fact groups an advisor
#: answer may be grounded in (AC-advisor.context.1).
BOUNDED_CONTEXT_KEYS = {
    "financial_summary",
    "report_readiness",
    "authority_coverage",
    "workflow",
    "market_data",
    "portfolio",
    "cash_flow",
    "suggestions",
}

#: Grounding vocabulary a suggestion/citation ``source_ref`` may cite.
BOUNDED_SOURCE_REFS = BOUNDED_CONTEXT_KEYS - {"suggestions"} | {"reconciliation"}

SENTINEL_BLOCKER_CODE = "port_sentinel_blocker"


def _fake_readiness_payload() -> dict:
    return {
        "package_id": "personal-financial-report-package",
        "state": "blocked",
        "label": "Blocked",
        "action_href": "/reports/package",
        "blocking_count": 1,
        "blockers": [
            {
                "code": SENTINEL_BLOCKER_CODE,
                "label": "Sentinel blocker (injected via the monkeypatched readiness read)",
                "severity": "blocking",
                "count": 1,
                "reason": "Proves the read flows through the actual call site, not a hardcoded value.",
                "action_href": "/reports/package",
            }
        ],
        "input_coverage": {
            "manifest_decision_count": 1,
            "authoritative_input_count": 1,
            "unproven_input_count": 1,
        },
    }


@pytest.fixture
def bounded_context_fakes(test_user, monkeypatch: pytest.MonkeyPatch):
    """Wire every bounded-context read to a deterministic fake."""
    now = datetime.now(UTC)

    async def fake_readiness(_db: AsyncSession, *, user_id):
        assert user_id == test_user.id
        return _fake_readiness_payload()

    async def fake_package_summary(_db: AsyncSession, *, user_id):
        payload = await fake_readiness(_db, user_id=user_id)
        return SimpleNamespace(
            status=SimpleNamespace(value="draft"),
            readiness=SimpleNamespace(model_dump=lambda mode="json": payload),
        )

    async def fake_fx_pairs(_db: AsyncSession, _user_id, *, include_default=True):
        del include_default
        return [("USD", "SGD")]

    async def fake_workflow(_db: AsyncSession, *, user_id):
        assert user_id == test_user.id
        return WorkflowStatusResponse(
            primary_state=WorkflowPrimaryState.NEEDS_ACTION,
            next_action=WorkflowNextActionResponse(
                type=WorkflowNextActionType.REVIEW_REQUIRED,
                count=2,
                href="/review",
                label="Review required",
                summary="Confirm pending source review items.",
            ),
            report_readiness=WorkflowReportReadinessResponse(
                state=WorkflowReportReadinessState.BLOCKED,
                blocking_count=1,
                href="/reports/package",
            ),
            event_counts=WorkflowEventCountsResponse(unread=1, action_required=2, blocked=0),
            active_session=None,
        )

    async def fake_market_data(_db: AsyncSession, *, pairs, symbols):
        del pairs, symbols
        return [
            SimpleNamespace(
                kind="stock",
                scope="AAPL",
                fresh=False,
                last_success_at=now - timedelta(days=4),
                last_success_date=date.today() - timedelta(days=4),
                last_observation_date=date.today() - timedelta(days=4),
            )
        ]

    async def fake_active_stock_symbols(_db: AsyncSession, _user_id):
        return ["AAPL"]

    async def fake_portfolio_summary(self, _db: AsyncSession, user_id, as_of_date=None):
        assert user_id == test_user.id
        assert as_of_date is None
        return SimpleNamespace(
            total_market_value=Decimal("10000.00"),
            total_cost_basis=Decimal("8000.00"),
            total_unrealized_pnl=Decimal("2000.00"),
            total_unrealized_pnl_percent=Decimal("25.00"),
            total_realized_pnl=Decimal("0.00"),
            total_realized_pnl_percent=Decimal("0.00"),
            net_pnl=Decimal("2000.00"),
            net_pnl_percent=Decimal("25.00"),
            holdings_count=1,
            active_positions_count=1,
            disposed_positions_count=0,
            currency="SGD",
        )

    monkeypatch.setattr(advisor_service_module, "current_package_document_summary", fake_package_summary)
    register_fx_pairs_read(fake_fx_pairs)
    monkeypatch.setattr(advisor_service_module, "get_workflow_status", fake_workflow)
    monkeypatch.setattr(advisor_service_module, "get_market_data_status", fake_market_data)
    monkeypatch.setattr(advisor_service_module, "active_stock_symbols", fake_active_stock_symbols)
    monkeypatch.setattr(advisor_service_module.PortfolioService, "get_portfolio_summary", fake_portfolio_summary)


FINANCIAL_SUMMARY = {
    "monthly_income": "SGD 5000.00",
    "monthly_expenses": "SGD 3000.00",
    "top_expenses": "Dining: SGD 500.00",
    "unmatched_count": "1",
    "pending_review": "2",
}


async def test_AC_advisor_context_1_context_is_exactly_the_bounded_read_set(
    db: AsyncSession, test_user, bounded_context_fakes
) -> None:
    """AC-advisor.context.1: the advisor context contains exactly the bounded fact groups,
    every read actually reaches its real call site (sentinel round-trip), and every
    suggestion cites only bounded grounding sources."""
    service = AIAdvisorService()

    context = await service.get_advisor_context(db, test_user.id, financial_context=dict(FINANCIAL_SUMMARY))

    # (a) Nothing outside the bounded read context enters the answer's grounding.
    assert set(context) == BOUNDED_CONTEXT_KEYS

    # (b) The readiness fact came through the actual call site (sentinel round-trip),
    # not a hardcoded/stale value.
    assert context["report_readiness"]["blocking_count"] == 1
    assert context["authority_coverage"]["blocker_codes"] == [SENTINEL_BLOCKER_CODE]

    # (c) Every suggestion is grounded: cites only bounded sources, states a basis
    # and a safe next action.
    assert context["suggestions"], "grounded suggestions must be derived from the context"
    for item in context["suggestions"]:
        assert item["basis"]
        assert item["source_refs"], "a suggestion must cite its grounding sources"
        assert set(item["source_refs"]) <= BOUNDED_SOURCE_REFS
        assert item["next_action_href"].startswith("/")


async def test_AC_advisor_context_1_response_metadata_carries_bounded_citations(
    db: AsyncSession, test_user, bounded_context_fakes
) -> None:
    """AC-advisor.context.1: the response metadata carries citations/actions that surface
    the bounded grounding sources through safe internal routes only."""
    service = AIAdvisorService()

    advisor_context = await service.get_advisor_context(db, test_user.id, financial_context=dict(FINANCIAL_SUMMARY))
    chat_context = {
        **FINANCIAL_SUMMARY,
        "balance_sheet_confidence_tier": "DETERMINISTIC",
        "income_statement_confidence_tier": "DETERMINISTIC",
        "advisor_context": json.dumps(advisor_context, sort_keys=True, default=str),
    }

    metadata = service.build_chat_grounding_metadata(chat_context, "Why is my net worth down?")

    assert metadata.grounded is True
    assert metadata.citations, "a grounded answer must carry citations"
    safe_hrefs = set(CHAT_METADATA_SAFE_HREFS)
    known_refs = BOUNDED_SOURCE_REFS | {
        "balance_sheet.total_equity",
        "income_statement.current_month",
    }
    for citation in metadata.citations:
        assert citation.href in safe_hrefs, f"citation href {citation.href!r} is not a safe route"
        assert citation.source_ref in known_refs, (
            f"citation {citation.source_ref!r} is outside the bounded read context"
        )
    for action in metadata.actions:
        assert action.href in safe_hrefs, f"action href {action.href!r} is not a safe route"
