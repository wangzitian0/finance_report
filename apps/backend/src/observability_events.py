"""Identity request-context binding for structlog (identity-owned; see #1428).

The shared structured-logging/redaction helpers that used to live here have moved
to the ``observability`` package (``src.observability``). Only identity's
request-context binding remains, to be folded into identity by #1428 — at which
point this module is deleted with zero residue.
"""

from __future__ import annotations

from uuid import UUID

import structlog


def bind_authenticated_user_context(user_id: UUID | str) -> None:
    """Bind the authenticated user id into structlog contextvars."""
    structlog.contextvars.bind_contextvars(user_id=str(user_id))
