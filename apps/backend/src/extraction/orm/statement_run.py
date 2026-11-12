"""One attempt to extract or classify a statement (#2994).

A run row holds its inputs (actor, trigger, hints, model, prompt) and its state. The inputs never change
after creation. A partial unique index keeps at most one requested or running run per statement. The
state module `extraction/extension/statement_runs.py` is the only code that changes the state columns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.extraction.base.run_vocabulary import (
    ACTIVE_RUN_STATES,
    ERROR_MESSAGE_MAX_LENGTH,
    RunActorKind,
    RunKind,
    RunState,
    RunTrigger,
)
from src.platform.orm.base import UUIDMixin


def _enum(enum_class, name: str) -> SQLEnum:
    return SQLEnum(enum_class, name=name, values_callable=lambda obj: [member.value for member in obj])


_ACTIVE_PREDICATE = "state IN (" + ", ".join(f"'{state.value}'" for state in sorted(ACTIVE_RUN_STATES)) + ")"


class StatementRun(Base, UUIDMixin):
    """Immutable inputs and mutable state of one extraction or classification attempt."""

    __tablename__ = "statement_runs"
    __table_args__ = (
        UniqueConstraint("statement_id", "seq", name="uq_statement_runs_statement_seq"),
        # A statement has at most one active run. The index is the guard: no pre-check read, no lock.
        Index(
            "uq_statement_runs_one_active",
            "statement_id",
            unique=True,
            postgresql_where=text(_ACTIVE_PREDICATE),
        ),
        # The composite keys prove at the database boundary that a run, its statement and its result
        # belong to one tenant and one statement.
        ForeignKeyConstraint(
            ["user_id", "statement_id"],
            ["statement_summaries.user_id", "statement_summaries.id"],
            name="fk_statement_runs_statement_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "statement_id", "extraction_result_id"],
            [
                "statement_extraction_results.user_id",
                "statement_extraction_results.statement_id",
                "statement_extraction_results.id",
            ],
            name="fk_statement_runs_result_owner",
        ),
        ForeignKeyConstraint(
            ["parent_run_id"],
            ["statement_runs.id"],
            name="fk_statement_runs_parent",
            ondelete="SET NULL",
        ),
    )

    # A plain foreign key, as in `BankCustodyBinding`: UserOwnedMixin cascades, and the cascade ratchet admits no new
    # user cascade. Deleting a statement removes its runs through `fk_statement_runs_statement_owner`.
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    statement_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="1-based attempt number within the statement")
    kind: Mapped[RunKind] = mapped_column(_enum(RunKind, "statement_run_kind_enum"), nullable=False)
    state: Mapped[RunState] = mapped_column(_enum(RunState, "statement_run_state_enum"), nullable=False)
    actor_kind: Mapped[RunActorKind] = mapped_column(
        _enum(RunActorKind, "statement_run_actor_kind_enum"),
        nullable=False,
        comment="Set from the authenticated principal, never from the request body",
    )
    trigger: Mapped[RunTrigger] = mapped_column(_enum(RunTrigger, "statement_run_trigger_enum"), nullable=False)
    parent_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Inputs. They never change after creation.
    hints: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    extraction_result_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        String(ERROR_MESSAGE_MAX_LENGTH), nullable=True, comment="Redacted by the caller"
    )
