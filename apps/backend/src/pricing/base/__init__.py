"""``pricing.base`` — the pure core: subject identity, the append-only observation, resolution.

No ORM, no network I/O, no crawler — importing this never touches a database.
The concrete storage adapter and the crawler/manual/FX/extraction-ingest
domain services (``extension/``, reserved — see ``common/pricing/contract.py``)
build against the ``ObservationRepository`` port declared here.
"""

from __future__ import annotations

from src.pricing.base.errors import (
    InvalidObservationError,
    InvalidSubjectError,
    NoObservationError,
    PricingError,
)
from src.pricing.base.events import PriceObserved
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.repository import ObservationRepository
from src.pricing.base.subject import PriceableSubject, SubjectKind

__all__ = [
    "Authority",
    "InvalidObservationError",
    "InvalidSubjectError",
    "NoObservationError",
    "ObservationRepository",
    "ObservationSource",
    "PriceObservation",
    "PriceObserved",
    "PriceableSubject",
    "PricingError",
    "ResolutionPolicy",
    "SubjectKind",
]
