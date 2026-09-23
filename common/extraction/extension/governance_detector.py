"""Live structural detector for source-fact lifecycle enforcement."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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


def _source(repo_root: Path, relative: str) -> str:
    return (repo_root / relative).read_text(encoding="utf-8")


def _contains(repo_root: Path, relative: str, fragments: tuple[str, ...]) -> list[str]:
    source = " ".join(_source(repo_root, relative).split())
    return [
        f"{relative}: missing {fragment}"
        for fragment in fragments
        if " ".join(fragment.split()) not in source
    ]


def _per_currency_approval(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _VALIDATION,
        (
            "typed_balances = statement.typed_currency_balances()",
            "balance_check(",
            '"balance_valid": all(row["closing_match"] for row in per_currency)',
        ),
    )


def _one_source_identity(repo_root: Path) -> list[str]:
    findings = _contains(
        repo_root,
        _ORM_LAYER1,
        (
            'UniqueConstraint("user_id", "file_hash", name="uq_uploaded_documents_user_file_hash")',
        ),
    )
    findings.extend(
        _contains(
            repo_root,
            _SOURCE_LIFECYCLE,
            (
                "select(UploadedDocument).where(",
                "UploadedDocument.user_id == command.user_id,",
                "UploadedDocument.file_hash == command.file_hash,",
            ),
        )
    )
    return findings


def _session_recovery(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _SOURCE_LIFECYCLE,
        (
            "async with db.begin_nested():",
            "db.add(candidate)",
            "except IntegrityError:",
            "return winner, False",
        ),
    )


def _append_only_retirement(repo_root: Path) -> list[str]:
    findings = _contains(
        repo_root,
        _SOURCE_LIFECYCLE,
        (
            "statement.status = BankStatementStatus.RETIRED",
            "document.status = DocumentStatus.RETIRED",
            ".with_for_update()",
        ),
    )
    findings.extend(
        _contains(
            repo_root,
            _ROUTER_STATEMENTS,
            (
                "await retire_statement(",
                "RetireStatementCommand(statement_id=statement_id, user_id=user_id)",
            ),
        )
    )
    return findings


def _storage_db_consistency(repo_root: Path) -> list[str]:
    source = _source(repo_root, _ROUTER_STATEMENTS)
    findings = []
    delete_fn_idx = source.find("async def delete_statement(")
    if delete_fn_idx < 0:
        return [f"{_ROUTER_STATEMENTS}: missing delete_statement"]
    next_fn_idx = source.find("\nasync def ", delete_fn_idx + 1)
    delete_fn_body = (
        source[delete_fn_idx:next_fn_idx] if next_fn_idx > 0 else source[delete_fn_idx:]
    )
    for forbidden in (
        "StorageService",
        "delete_object",
        "delete_file",
        "storage.delete",
    ):
        if forbidden in delete_fn_body:
            findings.append(
                f"{_ROUTER_STATEMENTS}: delete_statement contains forbidden {forbidden}"
            )
    return findings


def _failure_convergence(repo_root: Path) -> list[str]:
    findings = _contains(
        repo_root,
        _ROUTER_STATEMENTS,
        (
            "reset_for_retry=True",
            "except StorageError as exc:",
        ),
    )
    findings.extend(
        _contains(
            repo_root,
            _SOURCE_LIFECYCLE,
            (
                "if statement is None:",
                'raise ValueError("Statement not found or access denied")',
                "statement.status = BankStatementStatus.RETIRED",
            ),
        )
    )
    return findings


def _typed_command_boundary(repo_root: Path) -> list[str]:
    findings = _contains(
        repo_root,
        _SOURCE_LIFECYCLE,
        (
            "class SourceIdentityCommand:",
            "user_id: UUID",
            "document_type: DocumentType",
            "if not isinstance(self.user_id, UUID):",
            "if not isinstance(self.document_type, DocumentType):",
        ),
    )
    findings.extend(
        _contains(
            repo_root,
            _BASE_TYPES,
            (
                "class RetireStatementCommand:",
                "statement_id: UUID",
                "user_id: UUID",
                "if not isinstance(self.statement_id, UUID):",
            ),
        )
    )
    return findings


def _purge_boundary(repo_root: Path) -> list[str]:
    source = _source(repo_root, _ROUTER_STATEMENTS)
    findings = []
    delete_fn_idx = source.find("async def delete_statement(")
    if delete_fn_idx < 0:
        return [f"{_ROUTER_STATEMENTS}: missing delete_statement"]
    next_fn_idx = source.find("\nasync def ", delete_fn_idx + 1)
    delete_fn_body = (
        source[delete_fn_idx:next_fn_idx] if next_fn_idx > 0 else source[delete_fn_idx:]
    )
    for forbidden in ("purge", "delete(", "db.delete"):
        if forbidden in delete_fn_body.casefold():
            findings.append(
                f"{_ROUTER_STATEMENTS}: delete_statement has physical purge path: {forbidden}"
            )
    return findings


def _exact_governance_detail(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _CONTRACT,
        (
            'issue="https://github.com/wangzitian0/finance_report/issues/1995"',
            'id="source-lifecycle-convergence"',
            'required_proof_strength="value-oracle"',
            'required_proof_strength="concurrency"',
            'required_proof_strength="schema"',
            'required_proof_strength="exact"',
            'enforcing_gate="ci.backend"',
            'enforcing_gate="ci.backend_integration"',
        ),
    )


def _counterfactual_lock(repo_root: Path) -> list[str]:
    return _contains(
        repo_root,
        _TEST_LIFECYCLE,
        (
            "test_AC_extraction_source_lifecycle_10_counterfactual_matrix_is_locked",
            'orphan["declared_balance"] is False',
            "await retire_statement(db, RetireStatementCommand",
            "assert exc.value.status_code == 404",
        ),
    )


_CHECKS: tuple[tuple[str, Callable[[Path], list[str]]], ...] = (
    ("per-currency-approval", _per_currency_approval),
    ("one-source-identity", _one_source_identity),
    ("session-recovery", _session_recovery),
    ("append-only-retirement", _append_only_retirement),
    ("storage-db-consistency", _storage_db_consistency),
    ("failure-convergence", _failure_convergence),
    ("typed-command-boundary", _typed_command_boundary),
    ("purge-boundary", _purge_boundary),
    ("exact-governance-detail", _exact_governance_detail),
    ("counterfactual-lock", _counterfactual_lock),
)


def detect_governance(*, repo_root: Path) -> list[dict[str, object]]:
    """Return one independently computed observation per package guarantee."""
    observations = []
    for guarantee_id, check in _CHECKS:
        try:
            findings = check(repo_root)
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings = [
                f"{guarantee_id}: source inspection failed ({type(exc).__name__}): {exc}"
            ]
        observations.append(
            {
                "guarantee_id": f"extraction/{guarantee_id}",
                "current": len(findings),
                "target": 0,
                "findings": findings,
            }
        )
    return observations


__all__ = ["GOVERNANCE_SOURCE_PATHS", "detect_governance"]
