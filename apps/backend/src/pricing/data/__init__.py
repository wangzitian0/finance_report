"""``pricing.data`` — projection sinks (reserved).

Reserved for the latest-price-per-subject view and the staleness view that
portfolio/reporting/reconciliation will read. Per the data-sink rule nothing
in ``base/`` or ``extension/`` will ever import this layer.
"""

from __future__ import annotations

__all__: list[str] = []
