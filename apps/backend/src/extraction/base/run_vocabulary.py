"""Vocabulary of a statement run: one attempt to extract or classify one statement (#2994).

The definitions depend only on the standard library. The ORM maps them to PostgreSQL enums.
"""

from __future__ import annotations

from enum import StrEnum

ERROR_MESSAGE_MAX_LENGTH = 500


class RunKind(StrEnum):
    """What the run does."""

    EXTRACT = "extract"
    CLASSIFY = "classify"


class RunState(StrEnum):
    """Where the run is. A run only moves forward: requested, running, then one terminal state."""

    REQUESTED = "requested"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunActorKind(StrEnum):
    """Who asked for the run. The authenticated principal decides it, never the request body."""

    USER = "user"
    AI = "ai"
    SYSTEM = "system"


class RunTrigger(StrEnum):
    """Why the run exists."""

    UPLOAD = "upload"
    RERUN = "rerun"
    AUTO_CLASSIFY = "auto_classify"
    AUTO_RETRY = "auto_retry"
    BACKFILL = "backfill"


ACTIVE_RUN_STATES: frozenset[RunState] = frozenset({RunState.REQUESTED, RunState.RUNNING})
TERMINAL_RUN_STATES: frozenset[RunState] = frozenset({RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED})
