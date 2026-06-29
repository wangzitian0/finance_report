"""Identity request-context binding for structlog (identity-owned; see #1428).

``bind_authenticated_user_context`` binds the authenticated user id into the
structlog contextvars so downstream log lines are attributed to the user. This was
the identity-owned remainder of the former ``src/observability_events.py``, moved
into the package's single home (the module is deleted with zero residue). The
shared structured-logging/redaction helpers live in the ``observability`` package.
"""

from __future__ import annotations

from uuid import UUID

import structlog


def bind_authenticated_user_context(user_id: UUID | str) -> None:
    """Bind the authenticated user id into structlog contextvars."""
    structlog.contextvars.bind_contextvars(user_id=str(user_id))
