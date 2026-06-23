"""App-level configuration accessors (#1340, Phase D).

The base reporting currency is normally the env-only ``settings.base_currency``
default. Phase D persists an optional override in the ``app_config`` table so an
operator can change it at runtime. ``get_effective_base_currency`` is the single
accessor every caller should use: it returns the persisted override if present,
otherwise falls back to ``settings.base_currency``.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.app_config import BASE_CURRENCY_KEY, AppConfig
from src.money import Currency


async def get_effective_base_currency(db: AsyncSession) -> str:
    """Return the effective base currency: persisted override else env default.

    The persisted value is written pre-validated/normalized, so it is returned
    as-is; the env default is normalized through ``Currency`` for consistency.
    """
    result = await db.execute(select(AppConfig.value).where(AppConfig.key == BASE_CURRENCY_KEY))
    persisted = result.scalar_one_or_none()
    if persisted is not None:
        return persisted
    return Currency(settings.base_currency).code


async def set_base_currency(db: AsyncSession, code: str) -> str:
    """Persist (upsert) the base-currency override and return the stored value.

    ``code`` must already be a valid, normalized ISO 4217 code (the request
    schema validates it). The single ``app_config`` row keyed by
    ``BASE_CURRENCY_KEY`` is created or updated in place.
    """
    normalized = Currency(code).code
    result = await db.execute(select(AppConfig).where(AppConfig.key == BASE_CURRENCY_KEY))
    row = result.scalar_one_or_none()
    if row is None:
        db.add(AppConfig(key=BASE_CURRENCY_KEY, value=normalized))
    else:
        row.value = normalized
    await db.commit()
    return normalized
