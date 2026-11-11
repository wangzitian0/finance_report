"""AIAdvisorService + chat stream/error types."""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.advisor.base.constants import CHAT_METADATA_SAFE_HREFS, MAX_CONTEXT_MESSAGES
from src.advisor.base.guardrails import (
    StreamRedactor,
    build_refusal,
    detect_language,
    ensure_disclaimer,
    is_non_financial,
    is_prompt_injection,
    is_sensitive_request,
    is_write_request,
    normalize_question,
    redact_sensitive,
)
from src.advisor.base.prompt import get_ai_advisor_prompt
from src.advisor.extension import app_reads
from src.advisor.extension.cache import _CACHE
from src.advisor.orm.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from src.audit import to_money
from src.config_app import get_effective_base_currency
from src.ledger import (
    Account,
    AccountType,
    JournalEntry,
    JournalLine,
    active_journal_entry_filter,
    worst_confidence_tier,
)
from src.llm import (
    ReasoningEffort,
    Scene,
    SceneBinding,
    estimate_tokens,
    get_config_source,
    get_llm_client,
    stream_ai_chat,
)
from src.observability import get_logger
from src.portfolio import PortfolioNotFoundError, PortfolioService, active_stock_symbols
from src.pricing import MarketDataScopeStatus, get_market_data_status
from src.reconciliation import get_reconciliation_stats
from src.reporting import (
    ReportError,
    current_package_readiness,
    generate_balance_sheet,
    generate_income_statement,
    get_category_breakdown,
)
from src.schemas.chat import AdvisorSuggestion, ChatActionChip, ChatCitation, ChatResponseMetadata
from src.schemas.reporting import PersonalReportPackageSnapshotStatus
from src.workflow import get_workflow_status, stored_package_readiness

settings = src.config.settings
logger = get_logger("src.advisor")

_REFUSAL_CHECKS: tuple[tuple[Callable[[str], bool], str], ...] = (
    (is_prompt_injection, "injection"),
    (is_sensitive_request, "sensitive"),
    (is_write_request, "write"),
    (is_non_financial, "non_financial"),
)
_BALANCE_TOKENS = ("net worth", "assets", "asset", "liabilities", "liability", "balance", "equity", "worth")
_CASH_FLOW_TOKENS = ("expense", "expenses", "spending", "income", "cash flow", "cash-flow", "cashflow", "month")


class AIAdvisorError(Exception):
    """Raised when AI advisor fails."""


@dataclass
class ChatStream:
    session_id: UUID
    stream: AsyncIterator[str]
    model_name: str | None
    cached: bool
    metadata: ChatResponseMetadata = field(default_factory=ChatResponseMetadata)


async def _bound_scene_binding(user_id: UUID | None) -> SceneBinding | None:
    if user_id is None:
        return None
    try:
        return await get_config_source(user_id).get_binding(Scene.ADVISOR_CHAT)
    except Exception:  # noqa: BLE001
        logger.warning("advisor.chat binding resolution failed; using env models", exc_info=True)
        return None


def _large_role_reasoning() -> ReasoningEffort:
    return ReasoningEffort(settings.to_llm_settings().role_reasoning_effort("large"))


def _line_confidence_tier(line: dict[str, Any]) -> str | None:
    if explicit := line.get("confidence_tier"):
        return str(explicit)
    prov = str(line.get("provenance") or "").strip().lower()
    if prov == "manual":
        return "MANUAL_TRUSTED"
    return "DETERMINISTIC" if prov in ("imported", "derived") else None


class AIAdvisorService:
    """AI advisor service to answer financial questions."""

    def __init__(self) -> None:
        self.api_key = settings.ai_api_key
        self.base_url = settings.ai_base_url
        self.large_model = settings.large_model
        self.small_model = settings.small_model

    async def chat_stream(
        self,
        db: AsyncSession,
        user_id: UUID,
        message: str,
        session_id: UUID | None = None,
        model: str | None = None,
    ) -> ChatStream:
        raw_message = message.strip()
        message = redact_sensitive(raw_message)
        language = detect_language(raw_message)

        session = await self._get_or_create_session(db, user_id, session_id, message)
        await self._record_message(db, session, ChatMessageRole.USER, message)

        for predicate, kind in _REFUSAL_CHECKS:
            if predicate(raw_message):
                refusal = build_refusal(kind, language)
                await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
                return self._cached_stream(session.id, refusal, model_name=None)

        context = await self.get_financial_context(db, user_id)
        metadata = self.build_chat_grounding_metadata(context, raw_message)
        context_hash = hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        bound = await _bound_scene_binding(user_id)
        model_key = model or (bound.model_id if bound else None) or self.large_model
        cache_key = f"{user_id}:{language}:{normalize_question(message)}:{context_hash}:{model_key}"
        _CACHE.prune()
        if cached := _CACHE.get(cache_key):
            cached = ensure_disclaimer(cached, language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, cached, model_name="cache")
            return self._cached_stream(session.id, cached, model_name="cache", metadata=metadata)

        messages = [
            {"role": "system", "content": get_ai_advisor_prompt(context, language)},
            *(await self._load_history(db, session.id)),
            {"role": "user", "content": message},
        ]
        if not self.api_key and not await get_config_source(user_id).is_configured():
            raise AIAdvisorError("AI provider API key not configured")

        return ChatStream(
            session_id=session.id,
            stream=self._stream_and_store(db, session, messages, language, cache_key, model, user_id, bound),
            model_name=model_key,
            cached=False,
            metadata=metadata,
        )

    async def get_financial_context(self, db: AsyncSession, user_id: UUID) -> dict[str, str]:
        context = await self._get_financial_summary_context(db, user_id)
        advisor_context = await self.get_advisor_context(db, user_id, financial_context=context)
        context["advisor_context"] = json.dumps(advisor_context, sort_keys=True, default=str)
        context["advisor_suggestions"] = (
            "; ".join(f"{item['basis']} [{item['confidence_tier']}]" for item in advisor_context["suggestions"])
            or "N/A"
        )
        return context

    async def _get_financial_summary_context(self, db: AsyncSession, user_id: UUID) -> dict[str, str]:
        today = date.today()
        start_date = today.replace(day=1)
        base_currency = await get_effective_base_currency(db, user_id=user_id)
        ending_unrealized_fx: Decimal | None = None
        try:
            balance = cast(
                dict[str, Any],
                await generate_balance_sheet(
                    db, user_id, as_of_date=today, currency=base_currency, include_trust_signals=False
                ),
            )
            total_assets = Decimal(str(balance["total_assets"]))
            total_liabilities = Decimal(str(balance["total_liabilities"]))
            opening_equity = Decimal(str(balance["total_equity"]))
            net_income_bs = Decimal(str(balance.get("net_income") or "0.00"))
            net_worth = total_assets - total_liabilities
            currency = str(balance.get("currency") or base_currency)
            bs_lines = [*cast(list[dict[str, Any]], balance.get("assets") or []), *cast(list[dict[str, Any]], balance.get("liabilities") or [])]
            bs_tier = str(balance["confidence_tier"]) if balance.get("confidence_tier") else (
                worst_confidence_tier([_line_confidence_tier(line) for line in bs_lines], default="DETERMINISTIC")
                or "DETERMINISTIC"
            )
            ending_unrealized_fx = Decimal(str(balance["unrealized_fx_gain_loss"]))
        except ReportError:
            total_assets = total_liabilities = opening_equity = net_income_bs = net_worth = Decimal("0")
            currency = base_currency
            bs_tier = "UNAVAILABLE"

        try:
            inc = cast(
                dict[str, Any],
                await generate_income_statement(
                    db,
                    user_id,
                    start_date=start_date,
                    end_date=today,
                    currency=currency,
                    ending_unrealized_fx_gain_loss=ending_unrealized_fx,
                ),
            )
            monthly_income = Decimal(str(inc["total_income"]))
            monthly_expenses = Decimal(str(inc["total_expenses"]))
            inc_lines = cast(list[dict[str, Any]], inc.get("income") or [])
            exp_lines = cast(list[dict[str, Any]], inc.get("expenses") or [])
            if monthly_income == Decimal("0") and monthly_expenses == Decimal("0"):
                latest_pnl_date = await db.scalar(
                    select(func.max(JournalEntry.entry_date))
                    .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
                    .join(Account, JournalLine.account_id == Account.id)
                    .where(
                        JournalEntry.user_id == user_id,
                        Account.user_id == user_id,
                        Account.type.in_((AccountType.INCOME, AccountType.EXPENSE)),
                        active_journal_entry_filter(JournalEntry),
                        JournalEntry.entry_date < start_date,
                    )
                )
                if latest_pnl_date is not None:
                    hist_end = latest_pnl_date.replace(
                        day=calendar.monthrange(latest_pnl_date.year, latest_pnl_date.month)[1]
                    )
                    inc = cast(
                        dict[str, Any],
                        await generate_income_statement(
                            db, user_id, start_date=latest_pnl_date.replace(day=1), end_date=hist_end, currency=currency
                        ),
                    )
                    monthly_income = Decimal(str(inc["total_income"]))
                    monthly_expenses = Decimal(str(inc["total_expenses"]))
                    inc_lines = cast(list[dict[str, Any]], inc.get("income") or [])
                    exp_lines = cast(list[dict[str, Any]], inc.get("expenses") or [])
            inc_tier = (
                worst_confidence_tier(
                    [_line_confidence_tier(line) for line in [*inc_lines, *exp_lines]], default="DETERMINISTIC"
                )
                or "DETERMINISTIC"
            )
        except ReportError:
            monthly_income = monthly_expenses = Decimal("0")
            exp_lines = []
            inc_tier = "UNAVAILABLE"

        try:
            breakdown = cast(
                dict[str, Any],
                await get_category_breakdown(
                    db, user_id, breakdown_type=AccountType.EXPENSE, period="monthly", currency=currency
                ),
            )
            top_items = cast(list[dict[str, Any]], breakdown.get("items") or [])[:3]
            if not top_items and exp_lines:
                sorted_exp = sorted(
                    exp_lines, key=lambda line: Decimal(str(line.get("amount") or "0")), reverse=True
                )[:3]
                top_items = [
                    {"category_name": line["name"], "total": line["amount"]}
                    for line in sorted_exp
                    if Decimal(str(line.get("amount") or "0")) != Decimal("0")
                ]
            top_expenses = ", ".join(f"{item['category_name']}: {currency} {item['total']}" for item in top_items)
        except ReportError:
            top_expenses = "N/A"

        fmt = lambda amt: self._format_money(amt, currency)  # noqa: E731
        return {
            "total_assets": fmt(total_assets),
            "total_liabilities": fmt(total_liabilities),
            "net_worth": fmt(net_worth),
            "equity": fmt(net_worth),
            "opening_equity": fmt(opening_equity),
            "net_income": fmt(net_income_bs),
            "monthly_income": fmt(monthly_income),
            "monthly_expenses": fmt(monthly_expenses),
            "top_expenses": top_expenses or "N/A",
            **(await self._get_reconciliation_summary(db, user_id)),
            "balance_sheet_confidence_tier": bs_tier,
            "income_statement_confidence_tier": inc_tier,
        }

    async def _get_reconciliation_summary(self, db: AsyncSession, user_id: UUID) -> dict[str, str]:
        stats = await get_reconciliation_stats(db, user_id)
        return {
            "unmatched_count": str(stats.unmatched_transactions),
            "match_rate": f"{stats.match_rate}%",
            "pending_review": str(stats.pending_review),
        }

    async def get_advisor_context(
        self, db: AsyncSession, user_id: UUID, *, financial_context: dict[str, str] | None = None
    ) -> dict[str, Any]:
        summary = financial_context or await self._get_financial_summary_context(db, user_id)
        context = await self._load_advisor_facts(db, user_id, summary)
        context["suggestions"] = [s.model_dump() for s in self._build_advisor_suggestions(context)]
        return self._redact_context(context)

    async def get_advisor_suggestions(self, db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
        context = await self._load_advisor_facts(db, user_id, await self._get_reconciliation_summary(db, user_id))
        suggestions = [s.model_dump() for s in self._build_advisor_suggestions(context)]
        return cast(list[dict[str, Any]], self._redact_context({"suggestions": suggestions})["suggestions"])

    async def _load_advisor_facts(
        self, db: AsyncSession, user_id: UUID, financial_summary: dict[str, str]
    ) -> dict[str, Any]:
        readiness = await self._load_report_readiness(db, user_id)
        workflow = await self._load_workflow_status(db, user_id, synced_package_readiness=readiness)
        market_data = await self._load_market_data_status(db, user_id)
        portfolio = await self._load_portfolio_summary(db, user_id)
        return self._assemble_advisor_facts(
            financial_summary, readiness=readiness, workflow=workflow, market_data=market_data, portfolio=portfolio
        )

    def _assemble_advisor_facts(
        self,
        financial_summary: dict[str, str],
        *,
        readiness: dict[str, Any],
        workflow: dict[str, Any],
        market_data: dict[str, Any],
        portfolio: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "financial_summary": financial_summary,
            "report_readiness": self._advisor_readiness(readiness),
            "authority_coverage": self._advisor_authority_coverage(readiness),
            "workflow": workflow,
            "market_data": market_data,
            "portfolio": portfolio,
            "cash_flow": {
                k: financial_summary.get(k, "N/A")
                for k in ("monthly_income", "monthly_expenses", "top_expenses", "unmatched_count", "pending_review")
            },
        }

    async def _load_report_readiness(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        try:
            readiness = await stored_package_readiness(db, user_id=user_id)
            if readiness is None:
                readiness = (await current_package_readiness(db, user_id=user_id)).model_dump(mode="json")
            readiness["document_status"] = PersonalReportPackageSnapshotStatus.DRAFT.value
            return readiness
        except Exception as exc:
            logger.warning("Failed to load advisor report readiness", error=str(exc))
            return {
                "state": "draft",
                "label": "Unavailable",
                "action_href": "/reports?tab=package",
                "blocking_count": 0,
                "blockers": [],
                "input_coverage": {
                    "manifest_decision_count": 0,
                    "authoritative_input_count": 0,
                    "unproven_input_count": 0,
                },
                "document_status": "draft",
            }

    async def _load_workflow_status(
        self, db: AsyncSession, user_id: UUID, *, synced_package_readiness: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            return self._jsonable(
                await get_workflow_status(db, user_id=user_id, synced_package_readiness=synced_package_readiness)
            )
        except Exception as exc:
            logger.warning("Failed to load advisor workflow status", error=str(exc))
            return {
                "primary_state": "empty",
                "next_action": {
                    "type": "upload",
                    "count": 0,
                    "href": "/upload",
                    "label": "Upload statements",
                    "summary": "Add source documents to start the workflow.",
                },
                "event_counts": {"unread": 0, "action_required": 0, "blocked": 0},
                "report_readiness": {"state": "none", "blocking_count": 0, "href": "/reports"},
            }

    async def _load_market_data_status(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        try:
            fx_pairs = await app_reads.fx_pairs()(db, user_id, include_default=True)
            statuses = await get_market_data_status(
                db, pairs=fx_pairs, symbols=await active_stock_symbols(db, user_id)
            )
        except Exception as exc:
            logger.warning("Failed to load advisor market data status", error=str(exc))
            statuses = []
        rows = [self._jsonable(s) for s in statuses]
        stale = [r for r in rows if r.get("fresh") is False]
        return {"statuses": rows, "stale_count": len(stale), "stale_scopes": [str(r.get("scope")) for r in stale]}

    async def _load_portfolio_summary(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        try:
            payload = self._jsonable(await PortfolioService().get_portfolio_summary(db, user_id))
            payload["available"] = True
            return payload
        except PortfolioNotFoundError:
            return {
                "available": False,
                "holdings_count": 0,
                "active_positions_count": 0,
                "total_market_value": "0.00",
                "currency": await get_effective_base_currency(db, user_id=user_id),
            }
        except Exception as exc:
            logger.warning("Failed to load advisor portfolio summary", error=str(exc))
            return {"available": False, "limitation": "Portfolio summary is unavailable."}

    def _advisor_readiness(self, readiness: dict[str, Any]) -> dict[str, Any]:
        state = str(readiness.get("state", "draft"))
        return {
            "package_id": readiness.get("package_id"),
            "state": state,
            "label": readiness.get("label", state),
            "trusted": readiness.get("document_status") == "trusted",
            "blocking_count": int(readiness.get("blocking_count") or 0),
            "blockers": readiness.get("blockers", []),
            "action_href": readiness.get("action_href", "/reports?tab=package"),
            "generated_at": readiness.get("generated_at"),
            "stale_since": readiness.get("stale_since"),
        }

    def _advisor_authority_coverage(self, readiness: dict[str, Any]) -> dict[str, Any]:
        cov = readiness.get("input_coverage") or {}
        return {
            "manifest_decision_count": int(cov.get("manifest_decision_count") or 0),
            "authoritative_input_count": int(cov.get("authoritative_input_count") or 0),
            "unproven_input_count": int(cov.get("unproven_input_count") or 0),
            "blocker_codes": [str(b.get("code")) for b in readiness.get("blockers") or []],
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
                    source_refs=["report_readiness", "authority_coverage"],
                    limitation="Do not describe the report package as trusted until blockers are resolved.",
                    next_action_href=str(readiness["action_href"]),
                )
            )
        if action_required := int(workflow.get("event_counts", {}).get("action_required") or 0):
            suggestions.append(
                AdvisorSuggestion(
                    basis=f"Workflow has {action_required} action-required event(s).",
                    confidence_tier="review_required",
                    source_refs=["workflow"],
                    limitation="Pending review items may affect report readiness and advisory conclusions.",
                    next_action_href=str(workflow.get("next_action", {}).get("href") or "/audit"),
                )
            )
        if market_data["stale_count"]:
            suggestions.append(
                AdvisorSuggestion(
                    basis=f"Market data is stale for {market_data['stale_count']} observed scope(s).",
                    confidence_tier="stale",
                    source_refs=["market_data"],
                    limitation="Portfolio valuation and market-sensitive report facts should be refreshed before relying on them.",
                    next_action_href="/portfolio?panel=prices",
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
                    next_action_href="/reconciliation?tab=review-queue",
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
        citations: list[ChatCitation] = []
        actions: list[ChatActionChip] = []
        seen_citations: set[str] = set()
        seen_actions: set[tuple[str, str]] = set()

        def add_citation(label: str, source_ref: str, confidence_tier: str | None, href: str) -> None:
            safe_href = self._safe_chat_href(href)
            if source_ref not in seen_citations and safe_href != "/":
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
            if safe_href != "/" and (kind, safe_href) not in seen_actions:
                seen_actions.add((kind, safe_href))
                actions.append(ChatActionChip(kind=kind, label=label, href=safe_href, count=count))

        lower_message = message.lower()
        pending_review = self._parse_positive_int(context.get("pending_review"))
        if any(t in lower_message for t in _BALANCE_TOKENS):
            add_citation(
                "Balance Sheet",
                "balance_sheet.total_equity",
                context.get("balance_sheet_confidence_tier"),
                "/reports?tab=balance-sheet",
            )
        if any(t in lower_message for t in _CASH_FLOW_TOKENS) or pending_review:
            add_citation(
                "Income Statement",
                "income_statement.current_month",
                context.get("income_statement_confidence_tier"),
                "/reports?tab=income-statement",
            )
        if pending_review:
            add_action(
                "reconciliation_review", f"Review {pending_review}", "/reconciliation?tab=review-queue", pending_review
            )

        suggestions = self._parse_advisor_context(context.get("advisor_context")).get("suggestions")
        if isinstance(suggestions, list):
            for suggestion in suggestions:
                if not isinstance(suggestion, dict):
                    continue
                tier = str(suggestion.get("confidence_tier") or "DETERMINISTIC")
                href = str(suggestion.get("next_action_href") or "/reports")
                refs = suggestion.get("source_refs")
                if isinstance(refs, list):
                    for ref in refs[:2]:
                        if isinstance(ref, str) and ref:
                            add_citation(self._label_for_source_ref(ref), ref, tier, href)
                            if len(citations) >= 4:
                                break
                if len(citations) >= 4:
                    break

        if not citations:
            add_citation("Financial Summary", "financial_summary", "DETERMINISTIC", "/reports")
        return ChatResponseMetadata(grounded=bool(citations or actions), citations=citations[:4], actions=actions[:3])

    def _display_confidence_tier(self, value: str | None) -> str:
        return str(value).upper() if value else "DETERMINISTIC"

    def _parse_positive_int(self, value: str | None) -> int:
        try:
            return max(int(str(value)), 0)
        except (TypeError, ValueError):
            return 0

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
            seps = ("&", "#") if "?" in route else ("?", "#")
            if trimmed == route or any(trimmed.startswith(f"{route}{sep}") for sep in seps):
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
            return {str(k): self._jsonable(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self._jsonable(v) for v in value]
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, date | datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "__dict__"):
            return {str(k): self._jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
        return value

    def _redact_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return json.loads(redact_sensitive(json.dumps(context, sort_keys=True, default=str)))

    async def _get_or_create_session(
        self, db: AsyncSession, user_id: UUID, session_id: UUID | None, message: str
    ) -> ChatSession:
        if session_id:
            session = (
                await db.execute(
                    select(ChatSession).where(
                        ChatSession.id == session_id,
                        ChatSession.user_id == user_id,
                        ChatSession.status == ChatSessionStatus.ACTIVE,
                    )
                )
            ).scalar_one_or_none()
            if not session:
                raise AIAdvisorError("Chat session not found")
            session.last_active_at = datetime.now(UTC)
            await db.flush()
            await db.refresh(session)
            return session

        session = ChatSession(
            user_id=user_id,
            title=message[:60].strip() or None,
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
        message = ChatMessage(
            session_id=session.id,
            role=role,
            content=content,
            tokens_in=estimate_tokens(content) if role == ChatMessageRole.USER else None,
            tokens_out=estimate_tokens(content) if role == ChatMessageRole.ASSISTANT else None,
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
        rows = list(
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(MAX_CONTEXT_MESSAGES)
                )
            )
            .scalars()
            .all()
        )
        return [{"role": m.role.value, "content": m.content} for m in reversed(rows) if m.role != ChatMessageRole.SYSTEM]

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
                if safe_chunk := redactor.process(chunk):
                    chunks.append(safe_chunk)
                    yield safe_chunk
        except Exception as exc:
            raise AIAdvisorError(str(exc)) from exc

        if tail := redactor.flush():
            chunks.append(tail)
            yield tail

        raw_response = "".join(chunks)
        if not raw_response.strip():
            raise AIAdvisorError("AIStreamError: provider returned empty response")

        response_text = ensure_disclaimer(raw_response, language)
        if extra := response_text[len(raw_response) :]:
            yield extra

        _CACHE.set(cache_key, response_text)
        await self._record_message(
            db, session, ChatMessageRole.ASSISTANT, response_text, model_name=model_used or self.large_model
        )
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
        from src.llm import AIStreamError
        from src.observability import ErrorIds

        models = [self.large_model]
        if preferred_model is None and bound is not None:
            try:
                async for chunk in get_llm_client(user_id).stream(Scene.ADVISOR_CHAT, messages):
                    yield chunk, bound.model_id
                return
            except AIStreamError as exc:
                logger.warning(
                    "Bound advisor scene failed, trying environment fallbacks",
                    error_id=ErrorIds.AI_STREAMING_FAILED,
                    model=bound.model_id,
                    error=str(exc),
                    retryable=exc.retryable,
                )
        reasoning: ReasoningEffort | None = bound.reasoning if bound else _large_role_reasoning()
        max_tokens = bound.max_tokens if bound else None
        if preferred_model:
            models = [preferred_model, *models]
            reasoning = max_tokens = None
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
        return f"{currency} {to_money(amount)}"

    def _chunk_text(self, text: str, size: int = 48) -> list[str]:
        return [text[i : i + size] for i in range(0, len(text), size)]
