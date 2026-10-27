"""Live structural detector for source-fact lifecycle enforcement."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from common.meta.base.detector_runner import (
    all_of,
    read_source,
    requires,
    run_detectors,
)

_VALIDATION = "apps/backend/src/extraction/extension/statement_validation.py"
_SOURCE_LIFECYCLE = "apps/backend/src/extraction/extension/source_lifecycle.py"
_ORM_LAYER1 = "apps/backend/src/extraction/orm/layer1.py"
_ROUTER_STATEMENTS = "apps/backend/src/routers/statements.py"
_BASE_TYPES = "apps/backend/src/extraction/base/types.py"
_CONTRACT = "common/extraction/contract.py"
_TEST_LIFECYCLE = "apps/backend/tests/extraction/test_source_lifecycle.py"

GOVERNANCE_SOURCE_PATHS = (
    _VALIDATION,
    _SOURCE_LIFECYCLE,
    _ORM_LAYER1,
    _ROUTER_STATEMENTS,
    _BASE_TYPES,
    _CONTRACT,
    _TEST_LIFECYCLE,
)


def _delete_statement_hits(
    repo_root: Path, forbidden: tuple[str, ...], label: str, *, casefold: bool = False
) -> list[str]:
    source = read_source(repo_root, _ROUTER_STATEMENTS)
    start = source.find("async def delete_statement(")
    if start < 0:
        return [f"{_ROUTER_STATEMENTS}: missing delete_statement"]
    end = source.find("\nasync def ", start + 1)
    body = source[start:end] if end > 0 else source[start:]
    if casefold:
        body = body.casefold()
    return [
        f"{_ROUTER_STATEMENTS}: delete_statement {label} {word}"
        for word in forbidden
        if word in body
    ]


_CHECKS = {
    "per-currency-approval": requires(
        _VALIDATION,
        "typed_balances = statement.typed_currency_balances()",
        "balance_check(",
        '"balance_valid": all(row["closing_match"] for row in per_currency)',
    ),
    "one-source-identity": all_of(
        requires(
            _ORM_LAYER1,
            'UniqueConstraint("user_id", "file_hash", name="uq_uploaded_documents_user_file_hash")',
        ),
        requires(
            _SOURCE_LIFECYCLE,
            "select(UploadedDocument).where(",
            "UploadedDocument.user_id == command.user_id,",
            "UploadedDocument.file_hash == command.file_hash,",
        ),
    ),
    "session-recovery": requires(
        _SOURCE_LIFECYCLE,
        "async with db.begin_nested():",
        "db.add(candidate)",
        "except IntegrityError:",
        "return winner, False",
    ),
    "append-only-retirement": all_of(
        requires(
            _SOURCE_LIFECYCLE,
            "statement.status = BankStatementStatus.RETIRED",
            "document.status = DocumentStatus.RETIRED",
            ".with_for_update()",
        ),
        requires(
            _ROUTER_STATEMENTS,
            "await retire_statement(",
            "RetireStatementCommand(statement_id=statement_id, user_id=user_id)",
        ),
    ),
    "storage-db-consistency": partial(
        _delete_statement_hits,
        forbidden=("StorageService", "delete_object", "delete_file", "storage.delete"),
        label="contains forbidden",
    ),
    "failure-convergence": all_of(
        requires(
            _ROUTER_STATEMENTS, "reset_for_retry=True", "except StorageError as exc:"
        ),
        requires(
            _SOURCE_LIFECYCLE,
            "if statement is None:",
            'raise ValueError("Statement not found or access denied")',
            "statement.status = BankStatementStatus.RETIRED",
        ),
    ),
    "typed-command-boundary": all_of(
        requires(
            _SOURCE_LIFECYCLE,
            "class SourceIdentityCommand:",
            "user_id: UUID",
            "document_type: DocumentType",
            "if not isinstance(self.user_id, UUID):",
            "if not isinstance(self.document_type, DocumentType):",
        ),
        requires(
            _BASE_TYPES,
            "class RetireStatementCommand:",
            "statement_id: UUID",
            "user_id: UUID",
            "if not isinstance(self.statement_id, UUID):",
        ),
    ),
    "purge-boundary": partial(
        _delete_statement_hits,
        forbidden=("purge", "delete(", "db.delete"),
        label="has physical purge path:",
        casefold=True,
    ),
    "exact-governance-detail": requires(
        _CONTRACT,
        'issue="https://github.com/wangzitian0/finance_report/issues/1995"',
        'id="source-lifecycle-convergence"',
        'required_proof_strength="value-oracle"',
        'required_proof_strength="concurrency"',
        'required_proof_strength="schema"',
        'required_proof_strength="exact"',
        'enforcing_gate="ci.backend"',
    ),
    "counterfactual-lock": requires(
        _TEST_LIFECYCLE,
        "test_AC_extraction_source_lifecycle_10_counterfactual_matrix_is_locked",
        'orphan["declared_balance"] is False',
        "await retire_statement(db, RetireStatementCommand",
        "assert exc.value.status_code == 404",
    ),
}


def detect_governance(*, repo_root: Path) -> list[dict[str, object]]:
    """Return one independently computed observation per package guarantee."""
    return run_detectors("extraction", _CHECKS, repo_root)


__all__ = ["GOVERNANCE_SOURCE_PATHS", "detect_governance"]
