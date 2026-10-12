"""Mark a core-journey checkpoint as proven in the JUnit record (#2370).

AC-testing.journey-board.5 keeps these marks and the checkpoint map in step.

Call ``checkpoint`` right after the assertions that prove the checkpoint. The
journey board reads these JUnit properties. The order of the calls must equal
the ``reaches`` order in ``common/testing/data/core-journey-checkpoints.json``.
"""

from __future__ import annotations

from collections.abc import Callable

from common.testing.journey_board import CHECKPOINT_PROPERTY_PREFIX, CHECKPOINT_REACHED


def checkpoint(
    record_property: Callable[[str, object], None], checkpoint_id: str
) -> None:
    record_property(f"{CHECKPOINT_PROPERTY_PREFIX}{checkpoint_id}", CHECKPOINT_REACHED)
