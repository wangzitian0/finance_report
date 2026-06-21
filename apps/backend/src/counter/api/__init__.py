"""Counter boundary (the thin async read for insight-report generation).

``read_count`` bridges an ``AsyncSession`` to the domain ``Count``. It is the
only role that combines the session with the domain; it stays minimal by design
(no HTTP route until a transport need is real).
"""

from __future__ import annotations

from src.counter.api.insight import read_count

__all__ = ["read_count"]
