"""Per-request context carrying memoized user settings and request-scoped state."""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config_app import get_effective_base_currency


@dataclass
class RequestContext:
    """Request-scoped container holding the active session, user id, and memoized lookups."""

    db: AsyncSession
    user_id: UUID
    _base_currency: str | None = field(default=None, init=False, repr=False)

    async def get_base_currency(self) -> str:
        """Return the caller's effective base currency, querying at most once per request."""
        if self._base_currency is None:
            self._base_currency = await get_effective_base_currency(self.db, user_id=self.user_id)
        return self._base_currency


__all__ = ["RequestContext"]
