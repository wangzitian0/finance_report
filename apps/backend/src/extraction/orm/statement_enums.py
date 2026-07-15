from enum import StrEnum

"""Statement lifecycle enums.

These outlive the legacy ``bank_statements`` table (EPIC-011 Stage 3): they are
reused by ``StatementSummary`` (the DWD conform) and many consumers, so they live
in their own module that does not depend on the soon-to-be-removed ORM model.
"""


class BankStatementStatus(StrEnum):
    """Statement processing status."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    APPROVED = "approved"
    REJECTED = "rejected"


class Stage1Status(StrEnum):
    """Stage 1 review status for statements."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
