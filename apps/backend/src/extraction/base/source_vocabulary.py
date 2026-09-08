"""Source-document vocabulary shared by pure rules and persistence adapters.

These enums describe source facts and their review lifecycle. Database mappings
consume them; importing this leaf never requires SQLAlchemy or app settings.
Investment-position and cost-basis vocabulary is deliberately not defined here.
"""

from enum import Enum


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
    RETIRED = "retired"


class TransactionDirection(str, Enum):
    """Transaction flow direction, not economic intent."""

    IN = "IN"
    OUT = "OUT"


class RuleType(str, Enum):
    """Type of classification rule."""

    KEYWORD_MATCH = "keyword_match"
    REGEX_MATCH = "regex_match"
    ML_MODEL = "ml_model"


class ClassificationStatus(str, Enum):
    """Status of transaction classification."""

    DRAFT = "draft"
    APPLIED = "applied"
    SUPERSEDED = "superseded"


class BankStatementStatus(str, Enum):
    """Statement processing status."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETIRED = "retired"


class Stage1Status(str, Enum):
    """Stage 1 review status for statements."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
