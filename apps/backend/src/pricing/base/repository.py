"""``ObservationRepository`` — the port the pure resolver depends on (mechanism B).

The concrete adapter (querying the legacy ``FxRate``/``StockPrice``/
``ManualValuationSnapshot``/``MarketDataOverride`` tables during the
transition, and eventually a unified observation store) lives in
``extension/`` — reserved for a later commit (P2) once fx.py's and
market_data's logic actually moves in. Declaring the port now lets
``resolve()`` be written and tested against a fake today, without waiting on
the storage migration.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from src.pricing.base.observation import PriceObservation
from src.pricing.base.subject import PriceableSubject


class ObservationRepository(Protocol):
    """Read port: candidate observations for a subject as of (at most) a date."""

    async def candidates(self, subject: PriceableSubject, as_of: date) -> list[PriceObservation]:
        """Every observation known for ``subject`` with ``as_of`` on or before the given date."""
        ...
