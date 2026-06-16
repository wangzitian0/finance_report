"""DB-backed LLM provider configuration (EPIC-023 EPIC B).

These tables hold the *operational* LLM config the SSOT vocabulary
(``docs/ssot/llm.md``) describes: provider instances (with their API key
encrypted at rest) and the scene→model bindings. They are deployment-scoped
(not user-owned) — a single per-deployment configuration, edited via the
``/llm`` API / first-run modal. The Python enums are reused from
``src/llm/common`` so the DB and the runtime contract can never drift.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.llm.common import ProtocolFamily, ReasoningEffort, Scene
from src.models.base import TimestampMixin, UUIDMixin


def _enum_values(enum_cls: type) -> list[str]:
    return [member.value for member in enum_cls]


class LlmProvider(Base, UUIDMixin, TimestampMixin):
    """A configured provider instance; the API key is stored encrypted."""

    __tablename__ = "llm_providers"

    label: Mapped[str] = mapped_column(String(100), nullable=False)
    protocol: Mapped[ProtocolFamily] = mapped_column(
        Enum(
            ProtocolFamily,
            name="llm_protocol_family_enum",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    # Fernet ciphertext + the key fingerprint that sealed it (see src/llm/common/secrets.py).
    # BigInteger: the fingerprint is an unsigned 32-bit value (sha256[:4], up to ~4.3e9)
    # which overflows a signed int32 column.
    api_key_ciphertext: Mapped[str] = mapped_column(String, nullable=False)
    api_key_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    api_base: Mapped[str | None] = mapped_column(String(500), nullable=True)


class LlmSceneBinding(Base, UUIDMixin, TimestampMixin):
    """Which provider+model (and how) a scene resolves to. One row per scene."""

    __tablename__ = "llm_scene_bindings"

    scene: Mapped[Scene] = mapped_column(
        Enum(Scene, name="llm_scene_enum", values_callable=_enum_values),
        nullable=False,
        unique=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    reasoning: Mapped[ReasoningEffort] = mapped_column(
        Enum(ReasoningEffort, name="llm_reasoning_effort_enum", values_callable=_enum_values),
        nullable=False,
        default=ReasoningEffort.NONE,
    )
    prefer_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Comma-separated fallback model ids (kept as text for a simple additive schema).
    fallback_model_ids: Mapped[str] = mapped_column(String, nullable=False, default="")
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
