"""Append-only source-result and reviewer-confirmed statement envelope facts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.platform.orm.base import UserOwnedMixin, UUIDMixin


class StatementExtractionResultRecord(Base, UUIDMixin, UserOwnedMixin):
    """Immutable typed source-result snapshot for one statement parse."""

    __tablename__ = "statement_extraction_results"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "statement_id",
            "content_digest",
            name="uq_statement_extraction_results_statement_digest",
        ),
        UniqueConstraint(
            "user_id",
            "statement_id",
            "id",
            name="uq_statement_extraction_results_identity",
        ),
        CheckConstraint(
            "length(content_digest) = 64",
            name="ck_statement_extraction_results_content_digest_length",
        ),
        CheckConstraint(
            "length(source_content_digest) = 64",
            name="ck_statement_extraction_results_source_digest_length",
        ),
        ForeignKeyConstraint(
            ["user_id", "statement_id"],
            ["statement_summaries.user_id", "statement_summaries.id"],
            name="fk_statement_extraction_results_statement_owner",
            ondelete="RESTRICT",
        ),
        Index(
            "idx_statement_extraction_results_statement_created",
            "user_id",
            "statement_id",
            "created_at",
        ),
    )

    statement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_trace_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewedStatementEnvelope(Base, UUIDMixin, UserOwnedMixin):
    """Immutable human confirmation of one version-pinned statement envelope."""

    __tablename__ = "reviewed_statement_envelopes"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "statement_id",
            "command_digest",
            name="uq_reviewed_statement_envelopes_command",
        ),
        UniqueConstraint(
            "user_id",
            "statement_id",
            "id",
            name="uq_reviewed_statement_envelopes_identity",
        ),
        CheckConstraint(
            "period_start <= period_end",
            name="ck_reviewed_statement_envelopes_period_order",
        ),
        CheckConstraint(
            "length(currency) = 3",
            name="ck_reviewed_statement_envelopes_currency_length",
        ),
        CheckConstraint(
            "length(command_digest) = 64",
            name="ck_reviewed_statement_envelopes_command_digest_length",
        ),
        ForeignKeyConstraint(
            ["user_id", "statement_id", "source_result_id"],
            [
                "statement_extraction_results.user_id",
                "statement_extraction_results.statement_id",
                "statement_extraction_results.id",
            ],
            name="fk_reviewed_statement_envelopes_source_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "statement_id", "supersedes_id"],
            [
                "reviewed_statement_envelopes.user_id",
                "reviewed_statement_envelopes.statement_id",
                "reviewed_statement_envelopes.id",
            ],
            name="fk_reviewed_statement_envelopes_supersedes_owner",
            ondelete="RESTRICT",
        ),
        Index(
            "idx_reviewed_statement_envelopes_current",
            "user_id",
            "statement_id",
            "source_result_id",
            "created_at",
        ),
    )

    statement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    source_result_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    command_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    review_trace_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _reject_mutation(_mapper, _connection, target) -> None:
    raise ValueError(f"Reviewed statement envelope facts are append-only; mutation of {target.id} is forbidden")


for _model in (StatementExtractionResultRecord, ReviewedStatementEnvelope):
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)


_CREATE_APPEND_ONLY_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION reject_reviewed_statement_envelope_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'Reviewed statement envelope facts are append-only';
    END;
    $$ LANGUAGE plpgsql
    """
).execute_if(dialect="postgresql")
_CREATE_RESULT_APPEND_ONLY_TRIGGER = DDL(
    """
    CREATE TRIGGER statement_extraction_results_append_only
    BEFORE UPDATE OR DELETE ON statement_extraction_results
    FOR EACH ROW EXECUTE FUNCTION reject_reviewed_statement_envelope_mutation()
    """
).execute_if(dialect="postgresql")
_CREATE_ENVELOPE_APPEND_ONLY_TRIGGER = DDL(
    """
    CREATE TRIGGER reviewed_statement_envelopes_append_only
    BEFORE UPDATE OR DELETE ON reviewed_statement_envelopes
    FOR EACH ROW EXECUTE FUNCTION reject_reviewed_statement_envelope_mutation()
    """
).execute_if(dialect="postgresql")

event.listen(StatementExtractionResultRecord.__table__, "after_create", _CREATE_APPEND_ONLY_FUNCTION)
event.listen(StatementExtractionResultRecord.__table__, "after_create", _CREATE_RESULT_APPEND_ONLY_TRIGGER)
event.listen(ReviewedStatementEnvelope.__table__, "after_create", _CREATE_ENVELOPE_APPEND_ONLY_TRIGGER)
