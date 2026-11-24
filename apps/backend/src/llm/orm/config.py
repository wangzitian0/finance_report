"""Legacy tables of the per-user LLM configuration (EPIC-023, deleted by #2953).

``llm_providers`` and ``llm_scene_bindings`` held provider instances (API key
encrypted at rest) and scene-to-model bindings. No code reads or writes them since
stage 2 of #2953: the three model roles come from the environment. Both tables
hold no row on staging or production (checked 2026-11-24). Stage 3 of #2953 drops
the tables and the columns ``prefer_free`` and ``fallback_model_ids``; it is
owner-reserved. These models stay until that migration lands.
"""

from __future__ import annotations

import enum
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.llm.base import ProtocolFamily, ReasoningEffort, Scene
from src.platform.orm.base import TimestampMixin, UUIDMixin


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
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
    # Fernet ciphertext + the key fingerprint that sealed it. No code reads or writes it (#2953); stage 3 drops it.
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
