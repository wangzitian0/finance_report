'AC-testing.journey-board.5'; from __future__ import annotations; from collections.abc import Callable; from common.testing.journey_board import CHECKPOINT_PROPERTY_PREFIX, CHECKPOINT_REACHED
def checkpoint(record_property: Callable[[str, object], None], checkpoint_id: str) -> None: record_property(f'{CHECKPOINT_PROPERTY_PREFIX}{checkpoint_id}', CHECKPOINT_REACHED)
