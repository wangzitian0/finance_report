"""Application-level configuration persisted in the database.

Phase D of the currency strong-type EPIC (#1340) makes the base reporting
currency editable at runtime. ``settings.base_currency`` (``src.config``) is an
env-only default; this single-row, key/value ``app_config`` table lets an
operator override app-level settings (starting with the base currency) without
redeploying. The effective value is "persisted row else env default" — see
``src.config_app.get_effective_base_currency``.

The table is a generic ``key -> value`` store (text columns) so future app-level
settings reuse the same row shape; ``key`` is unique so each setting has exactly
one row.
"""

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UUIDMixin

# Stable key for the base reporting currency row.
BASE_CURRENCY_KEY = "base_currency"


class AppConfig(Base, UUIDMixin, TimestampMixin):
    """A single app-level configuration entry (``key`` -> ``value``)."""

    __tablename__ = "app_config"
    __table_args__ = (UniqueConstraint("key", name="uq_app_config_key"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
