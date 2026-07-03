"""Shared extraction constants, date parsing, and ExtractionError."""

from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

from src.observability import get_logger

logger = get_logger(__name__)
CSV_INFERRED_BALANCE_REVIEW_NOTE = (
    "CSV import does not include source statement opening/closing balances; manual review required"
)


# Date formats seen across real bank/brokerage statements, beyond strict ISO.
# Ordered so day-first forms win before the ambiguous US month-first form; this
# preserves the prior CSV parser's resolution while adding non-ISO support (#1086).
_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",  # Chinese bank statements, e.g. 2025年01月15日
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
)


def _tolerant_parse_date(value: str | None) -> date | None:
    """Defensive fallback parser for dates the model didn't normalize to ISO (#1086).

    Primary date normalization is the extraction model's responsibility — the parsing
    prompt instructs it to emit ISO ``YYYY-MM-DD`` for every source format. This
    handles the residual cases where the model still echoes a common non-ISO form
    (Chinese ``YYYY年MM月DD日``, ``DD/MM/YYYY``, ``YYYY.MM.DD``, ``DD Mon YYYY``, ISO
    datetimes). It returns ``None`` for empty/unparseable input so callers decide
    whether a missing date is fatal (a required statement period) or skippable (one
    bad row), instead of a strict ``date.fromisoformat`` aborting the whole document.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "-"}:
        return None
    # Fast path: ISO date, or an ISO datetime whose leading 10 chars are the date.
    iso_candidate = text[:10] if ("T" in text or " " in text) else text
    try:
        return date.fromisoformat(iso_candidate)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class ExtractionError(Exception):
    """Raised when extraction fails."""

    pass


def stream_ai_json(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
    """Thin lazy proxy over ``src.services.ai_streaming.stream_ai_json``.

    Module-level so tests can monkeypatch it (via this module or the modules
    that re-export it), but the import happens on first call — ai_streaming
    pulls the llm package's litellm surface, which minimal tooling envs (that
    import this package root) do not install.
    """
    from src.services import ai_streaming

    return ai_streaming.stream_ai_json(*args, **kwargs)


async def accumulate_stream(*args: Any, **kwargs: Any) -> str:
    """Thin lazy proxy over ``src.services.ai_streaming.accumulate_stream`` (see above)."""
    from src.services import ai_streaming

    return await ai_streaming.accumulate_stream(*args, **kwargs)
