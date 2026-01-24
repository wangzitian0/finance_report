"""Layer 1: Raw Files - Document metadata registry for 4-layer architecture."""

from enum import Enum

from sqlalchemy import Enum as SQLEnum, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class DocumentType(str, Enum):
    """Document type classification."""

    BANK_STATEMENT = "bank_statement"
    BROKERAGE_STATEMENT = "brokerage_statement"
    ESOP_GRANT = "esop_grant"
    PROPERTY_APPRAISAL = "property_appraisal"


class DocumentStatus(str, Enum):
    """Document processing status."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadedDocument(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 1: Immutable document metadata registry.

    This table stores metadata for all uploaded documents (bank statements,
    brokerage statements, ESOP grants, property appraisals). Files are stored
    in MinIO/S3 and referenced by file_path.

    Design Constraints:
    - Append-only: Once created, records are never modified
    - Deduplication: file_hash prevents duplicate uploads per user
    - Schema Stability: Designed to be stable forever (only add fields)
    """

    __tablename__ = "uploaded_documents"
    __table_args__ = (UniqueConstraint("user_id", "file_hash", name="uq_uploaded_documents_user_file_hash"),)

    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="MinIO object key")
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="SHA256 for deduplication")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="User-provided filename")

    document_type: Mapped[DocumentType] = mapped_column(
        SQLEnum(
            DocumentType,
            name="document_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        comment="Document classification",
    )

    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(
            DocumentStatus,
            name="document_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=DocumentStatus.UPLOADED,
        comment="Processing status",
    )

    extraction_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="AI extraction logs, confidence scores",
    )

    def __repr__(self) -> str:
        return f"<UploadedDocument {self.original_filename} ({self.document_type.value})>"
