from __future__ import annotations

from collections.abc import Callable

CHECKPOINT_PROPERTY_PREFIX = "checkpoint."
CHECKPOINT_REACHED = "reached"


def checkpoint(
    record_property: Callable[[str, object], None], checkpoint_id: str
) -> None:
    record_property(f"{CHECKPOINT_PROPERTY_PREFIX}{checkpoint_id}", CHECKPOINT_REACHED)
