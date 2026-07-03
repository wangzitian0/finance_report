"""``llm.data`` — projection sinks (reserved).

Reserved home for the package's read models. The first planned occupant is the
**usage rollup** (per-user × per-model × per-day request/token statistics): the
``base`` usage meter already emits the structured ``llm_usage`` log per call,
and the durable rollup that consumes it lands here as a projection — a
package-internal addition (new adapter behind the reserved ``UsageRepository``
port + a read model in this layer), NOT a re-cutover. See
``common/llm/contract.py`` for the reserved units.

Nothing imports this layer yet; per the data-sink rule nothing in ``base/`` or
``extension/`` ever will.
"""

from __future__ import annotations

__all__: list[str] = []
