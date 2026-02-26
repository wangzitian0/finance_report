"""AI advisor service for conversational financial insights."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logger import get_logger
from src.models import (
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    ChatMessage,
    ChatMessageRole,
    ChatSession,
    ChatSessionStatus,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.prompts.ai_advisor import DISCLAIMER_EN, DISCLAIMER_ZH, get_ai_advisor_prompt
from src.services.openrouter_streaming import stream_openrouter_chat
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_income_statement,
    get_category_breakdown,
)

logger = get_logger(__name__)

MAX_CONTEXT_MESSAGES = 20
CACHE_TTL_SECONDS = 3600

INJECTION_PATTERNS = (
    r"ignore (all|previous|prior) instructions",
    r"disregard (all|previous|prior) instructions",
    r"reveal (the )?(system|developer) prompt",
    r"system prompt",
    r"developer message",
    r"jailbreak",
    r"bypass safety",
    r"override (rules|policy)",
    r"forget what we talked about",
    r"you are now a",
)

SENSITIVE_PATTERNS = (
    r"password",
    r"account number",
    r"card number",
    r"credit card",
    r"cvv",
    r"otp",
    r"pin",
    r"social security",
    r"ssn",
    r"secret key",
)

NON_FINANCIAL_PATTERNS = (
    r"weather",
    r"joke",
    r"movie",
    r"music",
    r"recipe",
    r"sports",
    r"news",
    r"code",
    r"programming",
)

# SECURITY: Match long number sequences but avoid common date/time patterns
# (YYYY-MM-DD, DD/MM/YYYY, etc.)
# Generic branch: 12+ consecutive digits (no separators) to reduce accidental date matches
SENSITIVE_NUMBER_RE = re.compile(
    r"(?<!\d)\d{12,}(?!\d)"  # 12+ contiguous digits (account numbers, identifiers)
    r"|"
    r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"  # Credit card format: 4x4 digits
)

DISCLAIMER_BY_LANG = {
    "en": DISCLAIMER_EN,
    "zh": DISCLAIMER_ZH,
}

REFUSAL_BY_REASON = {
    "injection": {
        "en": "I cannot help with that request. Please ask a finance-related question.",
        "zh": (
            "\u6211\u65e0\u6cd5\u534f\u52a9\u8be5\u8bf7\u6c42\u3002"
            "\u8bf7\u63d0\u51fa\u4e0e\u8d22\u52a1\u76f8\u5173\u7684\u95ee\u9898\u3002"
        ),
    },
    "write": {
        "en": (
            "I can only provide read-only analysis and cannot create or modify ledger entries. "
            "Please use the manual entry workflow."
        ),
        "zh": (
            "\u6211\u53ea\u80fd\u63d0\u4f9b\u53ea\u8bfb\u5206\u6790\uff0c"
            "\u65e0\u6cd5\u521b\u5efa\u6216\u4fee\u6539\u5206\u5f55\u3002"
            "\u8bf7\u4f7f\u7528\u624b\u52a8\u5f55\u5165\u6d41\u7a0b\u3002"
        ),
    },
    "sensitive": {
        "en": "For safety reasons, I cannot provide sensitive information.",
        "zh": (
            "\u51fa\u4e8e\u5b89\u5168\u539f\u56e0\uff0c\u6211\u65e0\u6cd5\u63d0\u4f9b\u654f\u611f\u4fe1\u606f\u3002"
        ),
    },
    "non_financial": {
        "en": "This assistant only answers finance-related questions.",
        "zh": ("\u8be5\u52a9\u624b\u4ec5\u56de\u7b54\u8d22\u52a1\u76f8\u5173\u95ee\u9898\u3002"),
    },
}


class AIAdvisorError(Exception):
    """Raised when AI advisor fails."""

    pass


@dataclass
class ChatStream:
    session_id: UUID
    stream: AsyncIterator[str]
    model_name: str | None
    cached: bool


class ResponseCache:
    """Simple in-memory cache for common answers."""

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        now = time.time()
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if now >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str) -> None:
        expires_at = time.time() + self._ttl
        self._store[key] = (expires_at, value)

    def prune(self) -> None:
        now = time.time()
        expired = [key for key, (exp, _) in self._store.items() if exp <= now]
        for key in expired:
            self._store.pop(key, None)


_CACHE = ResponseCache()


def detect_language(message: str) -> str:
    """Detect message language based on CJK presence."""
    if re.search(r"[\u4e00-\u9fff]", message):
        return "zh"
    return "en"


def normalize_question(message: str) -> str:
    """Normalize question string for caching."""
    cleaned = re.sub(r"\s+", " ", message.strip().lower())
    normalized = re.sub(r"[^a-z0-9\s]", "", cleaned)
    if normalized:
        return normalized
    return hashlib.sha1(message.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Estimate token count for usage tracking."""
    return max(1, len(text) // 4)


def _matches_any(message: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)


def is_prompt_injection(message: str) -> bool:
    return _matches_any(message, INJECTION_PATTERNS)


def is_sensitive_request(message: str) -> bool:
    return _matches_any(message, SENSITIVE_PATTERNS)


def is_non_financial(message: str) -> bool:
    return _matches_any(message, NON_FINANCIAL_PATTERNS)


def is_write_request(message: str) -> bool:
    return _matches_any(
        message,
        (
            r"create (a )?(journal|entry)",
            r"post (a )?(journal|entry)",
            r"delete (a )?(journal|entry)",
            r"void (a )?(journal|entry)",
            r"modify (a )?(ledger|entry)",
            r"write (a )?(ledger|entry)",
        ),
    )


def redact_sensitive(text: str) -> str:
    """Redact long number sequences to avoid sensitive data leaks."""
    return SENSITIVE_NUMBER_RE.sub("[REDACTED]", text)


def ensure_disclaimer(text: str, language: str) -> str:
    """Ensure the output ends with the disclaimer."""
    disclaimer = DISCLAIMER_BY_LANG.get(language, DISCLAIMER_EN)
    if text.strip().endswith(disclaimer):
        return text
    if not text.endswith("\n"):
        text += "\n\n"
    return f"{text}{disclaimer}"


def build_refusal(reason: str, language: str) -> str:
    """Build refusal response with disclaimer."""
    message = REFUSAL_BY_REASON.get(reason, REFUSAL_BY_REASON["non_financial"]).get(
        language, REFUSAL_BY_REASON["non_financial"]["en"]
    )
    return ensure_disclaimer(message, language)


class StreamRedactor:
    """Streaming redactor that masks sensitive numbers without breaking chunks."""

    def __init__(self, tail_size: int = 64) -> None:
        self._tail_size = tail_size
        self._buffer = ""

    def process(self, chunk: str) -> str:
        combined = self._buffer + chunk
        if len(combined) <= self._tail_size:
            self._buffer = combined
            return ""
        safe_part = combined[: -self._tail_size]
        self._buffer = combined[-self._tail_size :]
        return redact_sensitive(safe_part)

    def flush(self) -> str:
        if not self._buffer:
            return ""
        output = redact_sensitive(self._buffer)
        self._buffer = ""
        return output


class AIAdvisorService:
    """AI advisor service to answer financial questions."""

    def __init__(self) -> None:
        self.api_key = settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url
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
        message = message.strip()
        language = detect_language(message)

        session = await self._get_or_create_session(db, user_id, session_id, message)
        await self._record_message(db, session, ChatMessageRole.USER, message)

        if is_prompt_injection(message):
            refusal = build_refusal("injection", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        if is_sensitive_request(message):
            refusal = build_refusal("sensitive", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        if is_write_request(message):
            refusal = build_refusal("write", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        if is_non_financial(message):
            refusal = build_refusal("non_financial", language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, refusal)
            return self._cached_stream(session.id, refusal, model_name=None)

        context = await self.get_financial_context(db, user_id)
        context_hash = hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        model_key = model or self.primary_model
        cache_key = f"{user_id}:{language}:{normalize_question(message)}:{context_hash}:{model_key}"
        _CACHE.prune()
        cached = _CACHE.get(cache_key)
        if cached:
            cached = ensure_disclaimer(cached, language)
            await self._record_message(db, session, ChatMessageRole.ASSISTANT, cached, model_name="cache")
            return self._cached_stream(session.id, cached, model_name="cache")

        prompt = get_ai_advisor_prompt(context, language)
        history = await self._load_history(db, session.id)
        messages = [{"role": "system", "content": prompt}, *history]
        messages.append({"role": "user", "content": message})

        if not self.api_key:
            raise AIAdvisorError("OpenRouter API key not configured")

        return ChatStream(
            session_id=session.id,
            stream=self._stream_and_store(
                db,
                session,
                messages,
                language,
                cache_key,
                model,
            ),
            model_name=None,
            cached=False,
        )

    async def get_financial_context(self, db: AsyncSession, user_id: UUID) -> dict[str, str]:
        """Build summarized financial context for the advisor."""
        today = date.today()
        start_date = today.replace(day=1)

        context: dict[str, str] = {}

        try:
            balance = await generate_balance_sheet(db, user_id, as_of_date=today)
            total_assets = Decimal(str(balance["total_assets"]))
            total_liabilities = Decimal(str(balance["total_liabilities"]))
            total_equity = Decimal(str(balance["total_equity"]))
            currency = balance.get("currency", settings.base_currency)
        except ReportError:
            total_assets = Decimal("0")
            total_liabilities = Decimal("0")
            total_equity = Decimal("0")
            currency = settings.base_currency

        try:
            income_statement = await generate_income_statement(
                db, user_id, start_date=start_date, end_date=today, currency=currency
            )
            monthly_income = Decimal(str(income_statement["total_income"]))
            monthly_expenses = Decimal(str(income_statement["total_expenses"]))
        except ReportError:
            monthly_income = Decimal("0")
            monthly_expenses = Decimal("0")

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

        txn_base = (
            select(func.count(BankStatementTransaction.id))
            .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
            .where(BankStatement.user_id == user_id)
        )
        total_result = await db.execute(txn_base)
        matched_result = await db.execute(
            txn_base.where(BankStatementTransaction.status == BankStatementTransactionStatus.MATCHED)
        )
        unmatched_result = await db.execute(
            txn_base.where(BankStatementTransaction.status == BankStatementTransactionStatus.UNMATCHED)
        )
        pending_result = await db.execute(
            select(func.count(ReconciliationMatch.id))
            .join(
                BankStatementTransaction,
                ReconciliationMatch.bank_txn_id == BankStatementTransaction.id,
            )
            .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
            .where(BankStatement.user_id == user_id)
            .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        )

        total = total_result.scalar_one()
        matched = matched_result.scalar_one()
        unmatched = unmatched_result.scalar_one()
        pending = pending_result.scalar_one()
        match_rate = float(round((matched / total) * 100, 2)) if total else 0.0

        context.update(
            {
                "total_assets": self._format_money(total_assets, currency),
                "total_liabilities": self._format_money(total_liabilities, currency),
                "equity": self._format_money(total_equity, currency),
                "monthly_income": self._format_money(monthly_income, currency),
                "monthly_expenses": self._format_money(monthly_expenses, currency),
                "top_expenses": top_expenses or "N/A",
                "unmatched_count": str(unmatched),
                "match_rate": f"{match_rate}%",
                "pending_review": str(pending),
            }
        )

        return context

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
            await db.commit()
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
        await db.commit()
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
        await db.commit()
        try:
            await db.refresh(message)
        except Exception:
            logger.warning("Failed to refresh message after commit", exc_info=True)
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
    ) -> AsyncIterator[str]:
        redactor = StreamRedactor()
        chunks: list[str] = []
        model_used: str | None = None

        try:
            async for chunk, model_name in self._stream_openrouter(messages, preferred_model):
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

    def _cached_stream(self, session_id: UUID, response: str, model_name: str | None) -> ChatStream:
        async def generator() -> AsyncIterator[str]:
            for chunk in self._chunk_text(response):
                yield chunk
                await asyncio.sleep(0.01)

        return ChatStream(
            session_id=session_id,
            stream=generator(),
            model_name=model_name,
            cached=True,
        )

    async def _stream_openrouter(
        self, messages: list[dict[str, str]], preferred_model: str | None
    ) -> AsyncIterator[tuple[str, str]]:
        from src.constants.error_ids import ErrorIds
        from src.services.openrouter_streaming import OpenRouterStreamError

        models = [self.primary_model, *self.fallback_models]
        if preferred_model:
            models = [preferred_model, *models]
        last_error: Exception | None = None

        for i, model in enumerate(models):
            try:
                async for chunk in self._stream_model(model, messages):
                    yield chunk, model
                return
            except OpenRouterStreamError as exc:
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

    async def _stream_model(self, model: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        async for chunk in stream_openrouter_chat(
            messages=messages,
            model=model,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=120.0,
        ):
            yield chunk

    def _format_money(self, amount: Decimal, currency: str) -> str:
        quantized = amount.quantize(Decimal("0.01"))
        return f"{currency} {quantized}"

    def _chunk_text(self, text: str, size: int = 48) -> list[str]:
        return [text[i : i + size] for i in range(0, len(text), size)]
