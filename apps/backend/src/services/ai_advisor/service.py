"""AIAdvisorService + chat stream/error types."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.llm.common import ReasoningEffort, Scene, SceneBinding
from src.llm.factory import get_config_source
from src.models import (
    AccountType,
    ChatMessage,
    ChatMessageRole,
    ChatSession,
    ChatSessionStatus,
)
from src.money import to_money
from src.prompts.ai_advisor import get_ai_advisor_prompt
from src.schemas.chat import AdvisorSuggestion, ChatActionChip, ChatCitation, ChatResponseMetadata
from src.services.ai_advisor._base import CHAT_METADATA_SAFE_HREFS, CONFIDENCE_WORST_ORDER, MAX_CONTEXT_MESSAGES, logger
from src.services.ai_advisor._cache import _CACHE
from src.services.ai_advisor._guardrails import (
    StreamRedactor,
    build_refusal,
    detect_language,
    ensure_disclaimer,
    estimate_tokens,
    is_non_financial,
    is_prompt_injection,
    is_sensitive_request,
    is_write_request,
    normalize_question,
    redact_sensitive,
)
from src.services.ai_streaming import stream_ai_chat
from src.services.market_data import MarketDataScopeStatus, get_market_data_status
from src.services.portfolio import PortfolioNotFoundError, PortfolioService
from src.services.reconciliation import get_reconciliation_stats
from src.services.report_readiness import get_personal_report_package_readiness
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_income_statement,
    get_category_breakdown,
)
from src.services.workflow_events import get_workflow_status


class AIAdvisorError(Exception):
    """Raised when AI advisor fails."""

    pass


@dataclass
class ChatStream:
    session_id: UUID
    stream: AsyncIterator[str]
    model_name: str | None
    cached: bool
    metadata: ChatResponseMetadata = field(default_factory=ChatResponseMetadata)


async def _bound_scene_binding(user_id: UUID | None) -> SceneBinding | None:
    """The user's ``advisor.chat`` binding (EPIC-023 AC23.4.5), or None.

    Carries the **qualified** ``provider_id/model`` (so the transport resolves the
    exact provider even with several configured) plus the configured reasoning depth
    and ``max_tokens``. Best-effort: ``user_id is None`` or any config-resolution
    error falls back to the env model list rather than breaking chat — and is logged
    so a broken per-user config is diagnosable instead of silently ignored."""
    if user_id is None:
        return None
    try:
        return await get_config_source(user_id).get_binding(Scene.ADVISOR_CHAT)
    except Exception:  # noqa: BLE001 - config issues must never break chat
        logger.warning("advisor.chat binding resolution failed; using env models", exc_info=True)
        return None


class AIAdvisorService:
    """AI advisor service to answer financial questions."""

    def __init__(self) -> None:
        self.api_key = settings.ai_api_key
        self.base_url = settings.ai_base_url
        self.primary_model = settings.primary_model
        self.fallback_models = settings.fallback_models

    async def chat_stream(
        self,
        db: AsyncSession,
        user_id: UUID,
        message: str,
        session_id: UUID | None = None,
        model: str | None = None,
    ) -> ChatStream:
        """Create a streaming chat response for a user message."""
        raw_message = message.strip()
        message = redact_sensitive(raw_message)
        language = detect_language(raw_message)

        session = await self._get_or_create_session(db, user_id, session_id, message)
        await self._record_message(db, session, ChatMessageRole.USER, message)

        if is_prompt_injection(raw_message):
            refusal = build_refusal("injection", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        if is_sensitive_request(raw_message):
            refusal = build_refusal("sensitive", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        if is_write_request(raw_message):
            refusal = build_refusal("write", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        if is_non_financial(raw_message):
            refusal = build_refusal("non_financial", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        context = await self.get_financial_context(db, user_id)
        metadata = self.build_chat_grounding_metadata(context, raw_message)
        context_hash = hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        # Resolve the user's advisor.chat binding once (one DB round-trip) and reuse
        # it for the cache key and streaming, so the cached entry and the streamed
        # response can never be keyed/generated under different models.
        bound = await _bound_scene_binding(user_id)
        bound_model = bound.model_id if bound else None
        # The cache key must reflect the model that will actually answer: an explicit
        # per-message model, else the bound model, else the env primary.
        model_key = model or bound_model or self.primary_model
        cache_key = f"{user_id}:{language}:{normalize_question(message)}:{context_hash}:{model_key}"
        _CACHE.prune()
        cached = _CACHE.get(cache_key)
        if cached:
            cached = ensure_disclaimer(cached, language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, cached, model_name="cache")
            return self._cached_stream(session.id, cached, model_name="cache", metadata=metadata)

        prompt = get_ai_advisor_prompt(context, language)
        history = await self._load_history(db, session.id)
        messages = [{"role": "system", "content": prompt}, *history]
        messages.append({"role": "user", "content": message})

        # Configured = the user has their own provider, or there is a deployment
        # default, or the env key is set (EPIC-023): a BYO-provider user must not be
        # blocked just because the deployment has no AI_API_KEY.
        if not self.api_key and not await get_config_source(user_id).is_configured():
            raise AIAdvisorError("AI provider API key not configured")

        return ChatStream(
            session_id=session.id,
            stream=self._stream_and_store(
                db,
                session,
                messages,
                language,
                cache_key,
                model,
                user_id,
                bound,
            ),
            model_name=None,
            cached=False,
            metadata=metadata,
        )

    async def get_financial_context(self, db: AsyncSession, user_id: UUID) -> dict[str, str]:
        """Build summarized financial context for the advisor."""
        context = await self._get_financial_summary_context(db, user_id)
        advisor_context = await self.get_advisor_context(db, user_id, financial_context=context)
        context["advisor_context"] = json.dumps(advisor_context, sort_keys=True, default=str)
        context["advisor_suggestions"] = (
            "; ".join(f"{item['basis']} [{item['confidence_tier']}]" for item in advisor_context["suggestions"])
            or "N/A"
        )
        return context

    async def _get_financial_summary_context(self, db: AsyncSession, user_id: UUID) -> dict[str, str]:
        """Build the legacy summary fields consumed by existing chat surfaces."""
        today = date.today()
        start_date = today.replace(day=1)

        context: dict[str, str] = {}

        try:
            balance = await generate_balance_sheet(db, user_id, as_of_date=today)
            total_assets = Decimal(str(balance["total_assets"]))
            total_liabilities = Decimal(str(balance["total_liabilities"]))
            total_equity = Decimal(str(balance["total_equity"]))
            currency = balance.get("currency", settings.base_currency)
            balance_sheet_confidence_tier = str(balance.get("confidence_tier") or "DETERMINISTIC")
        except ReportError:
            total_assets = Decimal("0")
            total_liabilities = Decimal("0")
            total_equity = Decimal("0")
            currency = settings.base_currency
            balance_sheet_confidence_tier = "UNAVAILABLE"

        try:
            income_statement = await generate_income_statement(
                db, user_id, start_date=start_date, end_date=today, currency=currency
            )
            monthly_income = Decimal(str(income_statement["total_income"]))
            monthly_expenses = Decimal(str(income_statement["total_expenses"]))
            income_statement_confidence_tier = self._worst_confidence_tier(
                [
                    line.get("confidence_tier")
                    for line in [
                        *(income_statement.get("income") or []),
                        *(income_statement.get("expenses") or []),
                    ]
                    if isinstance(line, dict)
                ]
            )
        except ReportError:
            monthly_income = Decimal("0")
            monthly_expenses = Decimal("0")
            income_statement_confidence_tier = "UNAVAILABLE"

        try:
            breakdown = await get_category_breakdown(
                db,
                user_id,
                breakdown_type=AccountType.EXPENSE,
                period="monthly",
                currency=currency,
            )
            top_items = breakdown.get("items", [])[:3]
            top_expenses = ", ".join(f"{item['category_name']}: {currency} {item['total']}" for item in top_items)
        except ReportError:
            top_expenses = "N/A"

        stats = await get_reconciliation_stats(db, user_id)

        context.update(
            {
                "total_assets": self._format_money(total_assets, currency),
                "total_liabilities": self._format_money(total_liabilities, currency),
                "equity": self._format_money(total_equity, currency),
                "monthly_income": self._format_money(monthly_income, currency),
                "monthly_expenses": self._format_money(monthly_expenses, currency),
                "top_expenses": top_expenses or "N/A",
                "unmatched_count": str(stats.unmatched_transactions),
                "match_rate": f"{stats.match_rate}%",
                "pending_review": str(stats.pending_review),
                "balance_sheet_confidence_tier": balance_sheet_confidence_tier,
                "income_statement_confidence_tier": income_statement_confidence_tier,
            }
        )

        return context

    async def get_advisor_context(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        financial_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build deterministic application facts and structured suggestions for the advisor."""
        financial_summary = financial_context or await self._get_financial_summary_context(db, user_id)
        readiness = await self._load_report_readiness(db, user_id)
        workflow = await self._load_workflow_status(db, user_id)
        market_data = await self._load_market_data_status(db, user_id)
        portfolio = await self._load_portfolio_summary(db, user_id)

        context: dict[str, Any] = {
            "financial_summary": financial_summary,
            "report_readiness": self._advisor_readiness(readiness),
            "source_trust": self._advisor_source_trust(readiness),
            "workflow": workflow,
            "market_data": market_data,
            "portfolio": portfolio,
            "cash_flow": {
                "monthly_income": financial_summary.get("monthly_income", "N/A"),
                "monthly_expenses": financial_summary.get("monthly_expenses", "N/A"),
                "top_expenses": financial_summary.get("top_expenses", "N/A"),
                "unmatched_count": financial_summary.get("unmatched_count", "N/A"),
                "pending_review": financial_summary.get("pending_review", "N/A"),
            },
        }
        context["suggestions"] = [suggestion.model_dump() for suggestion in self._build_advisor_suggestions(context)]
        return self._redact_context(context)

    async def _load_report_readiness(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        try:
            return await get_personal_report_package_readiness(db, user_id=user_id)
        except Exception as exc:
            logger.warning("Failed to load advisor report readiness", error=str(exc))
            return {
                "state": "draft",
                "label": "Unavailable",
                "action_href": "/reports/package",
                "blocking_count": 0,
                "blockers": [],
                "source_trust_summary": {},
            }

    async def _load_workflow_status(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        try:
            status = await get_workflow_status(db, user_id=user_id)
        except Exception as exc:
            logger.warning("Failed to load advisor workflow status", error=str(exc))
            return {
                "primary_state": "empty",
                "next_action": {
                    "type": "upload",
                    "count": 0,
                    "href": "/statements/upload",
                    "label": "Upload statements",
                    "summary": "Add source documents to start the workflow.",
                },
                "event_counts": {"unread": 0, "action_required": 0, "blocked": 0},
                "report_readiness": {"state": "none", "blocking_count": 0, "href": "/reports"},
            }
        return self._jsonable(status)

    async def _load_market_data_status(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        try:
            statuses = await get_market_data_status(db, user_id=user_id, include_default_fx=True)
        except Exception as exc:
            logger.warning("Failed to load advisor market data status", error=str(exc))
            statuses = []

        rows = [self._jsonable(status) for status in statuses]
        stale_rows = [row for row in rows if row.get("fresh") is False]
        return {
            "statuses": rows,
            "stale_count": len(stale_rows),
            "stale_scopes": [str(row.get("scope")) for row in stale_rows],
        }

    async def _load_portfolio_summary(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        try:
            summary = await PortfolioService().get_portfolio_summary(db, user_id)
        except PortfolioNotFoundError:
            return {
                "available": False,
                "holdings_count": 0,
                "active_positions_count": 0,
                "total_market_value": "0.00",
                "currency": settings.base_currency,
            }
        except Exception as exc:
            logger.warning("Failed to load advisor portfolio summary", error=str(exc))
            return {"available": False, "limitation": "Portfolio summary is unavailable."}

        payload = self._jsonable(summary)
        payload["available"] = True
        return payload

    def _advisor_readiness(self, readiness: dict[str, Any]) -> dict[str, Any]:
        state = str(readiness.get("state", "draft"))
        return {
            "package_id": readiness.get("package_id"),
            "state": state,
            "label": readiness.get("label", state),
            "trusted": state in {"ready", "generated"},
            "blocking_count": int(readiness.get("blocking_count") or 0),
            "blockers": readiness.get("blockers", []),
            "action_href": readiness.get("action_href", "/reports/package"),
            "generated_at": readiness.get("generated_at"),
            "stale_since": readiness.get("stale_since"),
        }

    def _advisor_source_trust(self, readiness: dict[str, Any]) -> dict[str, Any]:
        source_trust = readiness.get("source_trust_summary") or {}
        return {
            "source_classes": list(source_trust.get("source_classes") or []),
            "deterministic_pr_source_classes": list(source_trust.get("deterministic_pr_source_classes") or []),
            "post_merge_llm_ocr_source_classes": list(source_trust.get("post_merge_llm_ocr_source_classes") or []),
            "manual_trusted_source_classes": list(source_trust.get("manual_trusted_source_classes") or []),
            "gap_source_classes": list(source_trust.get("gap_source_classes") or []),
            "blocker_codes": list(source_trust.get("blocker_codes") or []),
        }

    def _build_advisor_suggestions(self, context: dict[str, Any]) -> list[AdvisorSuggestion]:
        suggestions: list[AdvisorSuggestion] = []
        readiness = context["report_readiness"]
        workflow = context["workflow"]
        market_data = context["market_data"]
        portfolio = context["portfolio"]
        cash_flow = context["cash_flow"]

        if readiness["blocking_count"]:
            suggestions.append(
                AdvisorSuggestion(
                    basis=f"Report readiness is {readiness['state']} with {readiness['blocking_count']} blocker(s).",
                    confidence_tier="blocked",
                    source_refs=["report_readiness", "source_trust"],
                    limitation="Do not describe the report package as trusted until blockers are resolved.",
                    next_action_href=str(readiness["action_href"]),
                )
            )

        event_counts = workflow.get("event_counts", {})
        action_required = int(event_counts.get("action_required") or 0)
        if action_required:
            next_action = workflow.get("next_action", {})
            suggestions.append(
                AdvisorSuggestion(
                    basis=f"Workflow has {action_required} action-required event(s).",
                    confidence_tier="review_required",
                    source_refs=["workflow"],
                    limitation="Pending review items may affect report readiness and advisory conclusions.",
                    next_action_href=str(next_action.get("href") or "/review"),
                )
            )

        if market_data["stale_count"]:
            suggestions.append(
                AdvisorSuggestion(
                    basis=f"Market data is stale for {market_data['stale_count']} observed scope(s).",
                    confidence_tier="stale",
                    source_refs=["market_data"],
                    limitation="Portfolio valuation and market-sensitive report facts should be refreshed before relying on them.",
                    next_action_href="/portfolio/prices/update",
                )
            )

        if portfolio.get("available") and int(portfolio.get("active_positions_count") or 0):
            suggestions.append(
                AdvisorSuggestion(
                    basis=(
                        f"Portfolio has {portfolio.get('active_positions_count')} active position(s) "
                        f"and market value {portfolio.get('total_market_value')} {portfolio.get('currency')}."
                    ),
                    confidence_tier="deterministic",
                    source_refs=["portfolio"],
                    limitation="This is a factual portfolio summary, not trading, tax, legal, or regulated investment advice.",
                    next_action_href="/portfolio",
                )
            )

        if cash_flow.get("pending_review") not in {None, "0", "N/A"}:
            suggestions.append(
                AdvisorSuggestion(
                    basis=f"Cash-flow context has {cash_flow['pending_review']} pending reconciliation review item(s).",
                    confidence_tier="review_required",
                    source_refs=["cash_flow", "reconciliation"],
                    limitation="Unreviewed reconciliation items should not be used as trusted cash-flow conclusions.",
                    next_action_href="/reconciliation/review-queue",
                )
            )

        if not suggestions:
            suggestions.append(
                AdvisorSuggestion(
                    basis="No blocking advisor facts were found in the current application state.",
                    confidence_tier="deterministic",
                    source_refs=["financial_summary"],
                    limitation="The advisor remains read-only and should cite source limitations when the user asks for detail.",
                    next_action_href="/reports",
                )
            )
        return suggestions

    def build_chat_grounding_metadata(self, context: dict[str, str], message: str) -> ChatResponseMetadata:
        """Build compact UI grounding metadata for one streamed chat answer."""
        citations: list[ChatCitation] = []
        actions: list[ChatActionChip] = []
        seen_citations: set[str] = set()
        seen_actions: set[tuple[str, str]] = set()

        def add_citation(label: str, source_ref: str, confidence_tier: str | None, href: str) -> None:
            safe_href = self._safe_chat_href(href)
            if source_ref in seen_citations or safe_href == "/":
                return
            seen_citations.add(source_ref)
            citations.append(
                ChatCitation(
                    label=label,
                    source_ref=source_ref,
                    confidence_tier=self._display_confidence_tier(confidence_tier),
                    href=safe_href,
                )
            )

        def add_action(kind: str, label: str, href: str, count: int | None = None) -> None:
            safe_href = self._safe_chat_href(href)
            key = (kind, safe_href)
            if safe_href == "/" or key in seen_actions:
                return
            seen_actions.add(key)
            actions.append(ChatActionChip(kind=kind, label=label, href=safe_href, count=count))

        lower_message = message.lower()
        pending_review = self._parse_positive_int(context.get("pending_review"))
        asks_balance = any(
            token in lower_message
            for token in ("net worth", "assets", "asset", "liabilities", "liability", "balance", "equity", "worth")
        )
        asks_cash_flow = any(
            token in lower_message
            for token in ("expense", "expenses", "spending", "income", "cash flow", "cash-flow", "cashflow", "month")
        )

        if asks_balance:
            add_citation(
                "Balance Sheet",
                "balance_sheet.total_equity",
                context.get("balance_sheet_confidence_tier"),
                "/reports/balance-sheet",
            )

        if asks_cash_flow or pending_review:
            add_citation(
                "Income Statement",
                "income_statement.current_month",
                context.get("income_statement_confidence_tier"),
                "/reports/income-statement",
            )

        if pending_review:
            add_action(
                "reconciliation_review",
                f"Review {pending_review}",
                "/reconciliation/review-queue",
                pending_review,
            )

        advisor_context = self._parse_advisor_context(context.get("advisor_context"))
        suggestions = advisor_context.get("suggestions") if isinstance(advisor_context, dict) else []
        if isinstance(suggestions, list):
            for suggestion in suggestions:
                if not isinstance(suggestion, dict):
                    continue
                source_refs = suggestion.get("source_refs")
                confidence_tier = str(suggestion.get("confidence_tier") or "DETERMINISTIC")
                href = str(suggestion.get("next_action_href") or "/reports")
                if isinstance(source_refs, list):
                    for source_ref in source_refs[:2]:
                        if not isinstance(source_ref, str) or not source_ref:
                            continue
                        add_citation(self._label_for_source_ref(source_ref), source_ref, confidence_tier, href)
                        if len(citations) >= 4:
                            break
                if len(citations) >= 4:
                    break

        if not citations:
            add_citation("Financial Summary", "financial_summary", "DETERMINISTIC", "/reports")

        return ChatResponseMetadata(
            grounded=bool(citations or actions),
            citations=citations[:4],
            actions=actions[:3],
        )

    def _worst_confidence_tier(self, values: list[str | None]) -> str:
        tiers = [str(value).upper() for value in values if value]
        if not tiers:
            return "DETERMINISTIC"
        return min(tiers, key=lambda tier: CONFIDENCE_WORST_ORDER.get(tier, -1))

    def _display_confidence_tier(self, value: str | None) -> str:
        if not value:
            return "DETERMINISTIC"
        return str(value).upper()

    def _parse_positive_int(self, value: str | None) -> int:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    def _parse_advisor_context(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _safe_chat_href(self, href: str) -> str:
        trimmed = href.strip()
        for route in CHAT_METADATA_SAFE_HREFS:
            if trimmed == route or trimmed.startswith(f"{route}?") or trimmed.startswith(f"{route}#"):
                return route
        return "/"

    def _label_for_source_ref(self, source_ref: str) -> str:
        return re.sub(r"[_\\.]+", " ", source_ref).strip().title() or "Application Fact"

    def _jsonable(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, MarketDataScopeStatus):
            return value.to_dict()
        if isinstance(value, dict):
            return {str(key): self._jsonable(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._jsonable(item) for item in value]
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, date | datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "__dict__"):
            return {str(key): self._jsonable(item) for key, item in vars(value).items() if not key.startswith("_")}
        return value

    def _redact_context(self, context: dict[str, Any]) -> dict[str, Any]:
        redacted = redact_sensitive(json.dumps(context, sort_keys=True, default=str))
        return json.loads(redacted)

    async def _get_or_create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        session_id: UUID | None,
        message: str,
    ) -> ChatSession:
        if session_id:
            result = await db.execute(
                select(ChatSession)
                .where(ChatSession.id == session_id)
                .where(ChatSession.user_id == user_id)
                .where(ChatSession.status == ChatSessionStatus.ACTIVE)
            )
            session = result.scalar_one_or_none()
            if not session:
                raise AIAdvisorError("Chat session not found")
            session.last_active_at = datetime.now(UTC)
            await db.flush()
            await db.refresh(session)
            return session

        title = message[:60].strip() or None
        session = ChatSession(
            user_id=user_id,
            title=title,
            status=ChatSessionStatus.ACTIVE,
            last_active_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    async def _record_message(
        self,
        db: AsyncSession,
        session: ChatSession,
        role: ChatMessageRole,
        content: str,
        model_name: str | None = None,
    ) -> ChatMessage:
        tokens_out = estimate_tokens(content) if role == ChatMessageRole.ASSISTANT else None
        tokens_in = estimate_tokens(content) if role == ChatMessageRole.USER else None
        message = ChatMessage(
            session_id=session.id,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model_name=model_name,
        )
        session.last_active_at = datetime.now(UTC)
        if session.title is None and role == ChatMessageRole.USER:
            session.title = content[:60].strip() or None
        db.add(message)
        await db.flush()
        try:
            await db.refresh(message)
        except Exception:
            logger.warning("Failed to refresh message after flush", exc_info=True)
        return message

    async def _load_history(self, db: AsyncSession, session_id: UUID) -> list[dict[str, str]]:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(MAX_CONTEXT_MESSAGES)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        history: list[dict[str, str]] = []
        for message in messages:
            if message.role == ChatMessageRole.SYSTEM:
                continue
            history.append({"role": message.role.value, "content": message.content})
        return history

    async def _stream_and_store(
        self,
        db: AsyncSession,
        session: ChatSession,
        messages: list[dict[str, str]],
        language: str,
        cache_key: str,
        preferred_model: str | None,
        user_id: UUID | None = None,
        bound: SceneBinding | None = None,
    ) -> AsyncIterator[str]:
        redactor = StreamRedactor()
        chunks: list[str] = []
        model_used: str | None = None

        try:
            async for chunk, model_name in self._stream_openrouter(messages, preferred_model, user_id, bound):
                model_used = model_name
                safe_chunk = redactor.process(chunk)
                if safe_chunk:
                    chunks.append(safe_chunk)
                    yield safe_chunk
        except Exception as exc:
            raise AIAdvisorError(str(exc)) from exc

        tail = redactor.flush()
        if tail:
            chunks.append(tail)
            yield tail

        response_text = "".join(chunks)
        response_text = ensure_disclaimer(response_text, language)
        if response_text != "".join(chunks):
            extra = response_text[len("".join(chunks)) :]
            if extra:
                yield extra

        _CACHE.set(cache_key, response_text)

        await self._record_message(
            db,
            session,
            ChatMessageRole.ASSISTANT,
            response_text,
            model_name=model_used or self.primary_model,
        )
        # Commit here because the router has already returned the StreamingResponse
        # and cannot commit after the generator completes.  This is a documented
        # exception to the "routers own commit()" rule.
        await db.commit()

    def _cached_stream(
        self,
        session_id: UUID,
        response: str,
        model_name: str | None,
        metadata: ChatResponseMetadata | None = None,
    ) -> ChatStream:
        async def generator() -> AsyncIterator[str]:
            for chunk in self._chunk_text(response):
                yield chunk
                await asyncio.sleep(0.01)

        return ChatStream(
            session_id=session_id,
            stream=generator(),
            model_name=model_name,
            cached=True,
            metadata=metadata or ChatResponseMetadata(),
        )

    async def _stream_openrouter(
        self,
        messages: list[dict[str, str]],
        preferred_model: str | None,
        user_id: UUID | None = None,
        bound: SceneBinding | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        from src.constants.error_ids import ErrorIds
        from src.services.ai_streaming import AIStreamError

        models = [self.primary_model, *self.fallback_models]
        # The binding's reasoning/max_tokens apply only when its model is used (no
        # per-message override). They're hints/caps, harmless if a fallback ignores them.
        reasoning = bound.reasoning if bound else None
        max_tokens = bound.max_tokens if bound else None
        if preferred_model:
            models = [preferred_model, *models]
            reasoning = max_tokens = None  # explicit per-message model: env defaults
        elif bound is not None:
            # No per-message override: prefer the user's configured advisor.chat
            # model (EPIC-023 AC23.4.5) so /settings/llm actually takes effect. The
            # bound model is qualified (provider_id/model); ai_streaming resolves the
            # exact provider from the qualifier.
            models = [bound.model_id, *models]
        last_error: Exception | None = None

        for i, model in enumerate(models):
            try:
                async for chunk in self._stream_model(model, messages, user_id, reasoning, max_tokens):
                    yield chunk, model
                return
            except AIStreamError as exc:
                logger.warning(
                    "AI model failed, trying fallback",
                    error_id=ErrorIds.AI_STREAMING_FAILED,
                    model=model,
                    attempt=i + 1,
                    total=len(models),
                    error=str(exc),
                    retryable=getattr(exc, "retryable", False),
                )
                last_error = exc
                continue
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                logger.exception(
                    "Programming error in AI streaming",
                    error_id=ErrorIds.AI_STREAMING_FAILED,
                    model=model,
                    error_type=type(exc).__name__,
                )
                raise AIAdvisorError(f"Internal error: {type(exc).__name__}") from exc

        if last_error:
            logger.error(
                "All AI models failed",
                error_id=ErrorIds.AI_ALL_MODELS_FAILED,
                models_tried=len(models),
                last_error=str(last_error),
            )
            raise last_error

    async def _stream_model(
        self,
        model: str,
        messages: list[dict[str, str]],
        user_id: UUID | None = None,
        reasoning: ReasoningEffort | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        async for chunk in stream_ai_chat(
            messages=messages,
            model=model,
            user_id=user_id,
            reasoning=reasoning,
            max_tokens=max_tokens,
            timeout=120.0,
        ):
            yield chunk

    def _format_money(self, amount: Decimal, currency: str) -> str:
        quantized = to_money(amount)
        return f"{currency} {quantized}"

    def _chunk_text(self, text: str, size: int = 48) -> list[str]:
        return [text[i : i + size] for i in range(0, len(text), size)]
