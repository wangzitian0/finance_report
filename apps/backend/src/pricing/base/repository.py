"""``ObservationRepository`` — the port the pure resolver depends on (mechanism B).

The concrete adapter (querying the legacy ``FxRate``/``StockPrice``/
``ManualValuationSnapshot``/``MarketDataOverride`` tables during the
transition, and eventually a unified observation store) lives in
``extension/``. Declaring the port here lets ``resolve()`` be written and
tested against a fake, without waiting on the storage migration.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from src.pricing.base.observation import PriceObservation
from src.pricing.base.subject import PriceableSubject


class ObservationRepository(Protocol):
    """Read port: candidate observations for a subject as of (at most) a date.

    ``user_id`` scopes the user-owned observation sources (manual valuations,
    overrides) to that user's own rows; global sources (crawled FX rates,
    crawled security prices) are unaffected by it. ``user_id=None`` returns
    only the global sources — never another user's manual data. A caller that
    passes a wrong/omitted ``user_id`` gets a smaller, never a LARGER, result
    set: no cross-tenant leak is representable through this signature.
    """

    async def candidates(
        self, subject: PriceableSubject, as_of: date, user_id: UUID | None = None
    ) -> list[PriceObservation]:
        """Every observation known for ``subject`` with ``as_of`` on or before the given date."""
        ...
