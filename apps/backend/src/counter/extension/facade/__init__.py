"""Counter facade — thin programmatic reads/writes over an ``AsyncSession``.

``read_count`` bridges a session to a domain ``Count`` (the read for insight
reports). ``record_increment`` is the atomic write: it bumps the tally and
enqueues ``Incremented`` into the platform outbox in the same transaction. The facade
is the only role that combines the session with the domain verbs and the platform
bus; it stays minimal by design (no HTTP route until a transport need is real).
"""

from __future__ import annotations

from src.counter.extension.facade.insight import read_count
from src.counter.extension.facade.write import record_increment

__all__ = ["read_count", "record_increment"]
