"""``PriceObservation`` — the append-only aggregate root, plus its value objects.

Per boundary ruling 2 (#1610): an observation is never mutated or deleted in
place. A correction is a NEW observation with higher (or equal, later-dated)
authority; the resolver (``base/resolve.py``) picks among candidates, it never
edits one. ``MarketDataOverride`` dissolves into ``ObservationSource.OVERRIDE``
— an override is just a high-authority observation, not a different mechanism.

Per boundary ruling 3: ``as_of`` (which day the value belongs to) and
``observed_at`` (when this fact was learned) are independent. A backfilled
observation has ``observed_at`` later than its ``as_of``; this is normal, not
an error — the bitemporal split is what lets a frozen ``ReportSnapshot`` stay
reproducible even after later corrections arrive (AC-pricing.bitemporal.1).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import IntEnum, StrEnum
from uuid import UUID, uuid4

from src.pricing.base.errors import InvalidObservationError
from src.pricing.base.subject import PriceableSubject


def pricing_valuation_lineage_id(
    *,
    subject: PriceableSubject,
    source: str,
    as_of: date,
) -> str:
    """Stable identity for one corrigible user-owned valuation fact.

    This is an identity key only. It is deliberately not a trust conclusion:
    the matching TraceRecord decision is required separately.
    """
    payload = {
        "as_of": as_of.isoformat(),
        "source": source,
        "subject_key": subject.key,
        "subject_kind": subject.kind.value,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"manual-valuation:{digest}"


class ObservationSource(StrEnum):
    """Where an observation came from — also the tie-break axis alongside authority."""

    CRAWLER = "crawler"
    MANUAL = "manual"
    OVERRIDE = "override"
    STATEMENT = "statement"


class Authority(IntEnum):
    """Higher wins when two observations for the same (subject, as_of) disagree.

    A user-entered override is deliberately the highest: it is an explicit,
    reviewed correction. A crawled price is the lowest: unattended, unreviewed.
    """

    CRAWLER = 0
    STATEMENT = 1
    MANUAL = 2
    OVERRIDE = 3


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One immutable fact: ``subject`` was worth ``value`` as of ``as_of``.

    ``value`` is a plain ``Decimal`` (never ``float`` — the standing red line)
    denominated in ``currency`` (``None`` for a subject whose value is
    inherently unitless, e.g. a ratio). Construction validates finiteness and
    positivity; an invalid value is unrepresentable.
    """

    subject: PriceableSubject
    value: Decimal
    as_of: date
    observed_at: datetime
    source: ObservationSource
    authority: Authority
    currency: str | None = None
    id: UUID = field(default_factory=uuid4)
    # Stable identity of a corrigible observation lineage. It is populated by
    # pricing's storage adapter and lets the decision layer supersede a prior
    # version without treating a row id, source label, or latest timestamp as
    # authority.
    lineage_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, Decimal):
            raise InvalidObservationError(f"observation value must be a Decimal, got {type(self.value).__name__}")
        if not self.value.is_finite():
            raise InvalidObservationError("observation value must be finite")
        if self.value <= 0:
            raise InvalidObservationError("observation value must be positive")
        if self.observed_at.tzinfo is None:
            raise InvalidObservationError(
                "observed_at must be timezone-aware — a naive datetime would raise "
                "TypeError the moment resolve() compares it against an aware one"
            )
