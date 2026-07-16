"""``extraction.data`` — projection sinks (reserved).

Reserved home for the evidence lineage read-models. The lineage read/write
paths are still entangled with the extension write path (integration
instantiates the lineage reader; materialization reuses an integration
helper), so the physical files currently sit in ``extension/`` and the clean
read-model split remains an unscheduled design option recorded by the contract's
taxonomy-only PROJECTION units.

Per the data-sink rule nothing in ``base/`` or ``extension/`` may import this
layer.
"""

from __future__ import annotations

__all__: list[str] = []
