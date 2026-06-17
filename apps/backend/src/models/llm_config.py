"""DB-backed LLM provider configuration (EPIC-023 EPIC B / PR4).

These tables hold the *operational* LLM config the SSOT vocabulary
(``docs/ssot/llm.md``) describes: provider instances (with their API key
encrypted at rest) and the scene→model bindings. The Python enums are reused
from ``src/llm/common`` so the DB and the runtime contract can never drift.

Since PR4 they are **per-user with a deployment default** (EPIC-023 AC23.4):
``user_id`` is nullable — ``NULL`` rows are the deployment default (the original
deployment-scoped behaviour), non-null rows belong to that user. Config resolves
a user's rows first, then the deployment default, then the env fallback.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.llm.common import ProtocolFamily, ReasoningEffort, Scene
from src.models.base import TimestampMixin, UUIDMixin


def _enum_values(enum_cls: type) -> list[str]:
    return [member.value for member in enum_cls]


class LlmProvider(Base, UUIDMixin, TimestampMixin):
    """A configured provider instance; the API key is stored encrypted.

    ``user_id`` scopes the provider: ``NULL`` is the deployment default, a
    non-null id is owned by that user (EPIC-023 AC23.4).
    """

    __tablename__ = "llm_providers"

    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
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
    """Which provider+model (and how) a scene resolves to.

    One binding per scene *within a scope*: partial unique indexes enforce one
    row per ``(user_id, scene)`` for user-owned bindings and one row per
    ``scene`` for the deployment default (``user_id IS NULL``).
    """

    __tablename__ = "llm_scene_bindings"

    __table_args__ = (
        Index(
            "uq_llm_scene_bindings_user_scene",
            "user_id",
            "scene",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_llm_scene_bindings_default_scene",
            "scene",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scene: Mapped[Scene] = mapped_column(
        Enum(Scene, name="llm_scene_enum", values_callable=_enum_values),
        nullable=False,
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
