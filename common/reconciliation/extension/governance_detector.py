"""Live structural detector for economic-disposition enforcement."""

from __future__ import annotations

import ast
from pathlib import Path

from common.meta.base.detector_runner import (
    all_of,
    missing_fragments,
    read_source,
    requires,
    run_detectors,
)

_MATCHING = "apps/backend/src/reconciliation/extension/matching.py"
_REPOSITORY = "apps/backend/src/reconciliation/extension/repository.py"
_TRANSFER_DETECTION = (
    "apps/backend/src/reconciliation/extension/phases/transfer_detection.py"
)
_TRANSFER_PAIRS = "apps/backend/src/reconciliation/extension/transfer_pairs.py"
_ENTRY_READS = "apps/backend/src/reconciliation/extension/entry_reads.py"
_ORM = "apps/backend/src/reconciliation/orm/reconciliation.py"
_CONTRACT = "common/reconciliation/contract.py"

GOVERNANCE_SOURCE_PATHS = (
    _MATCHING,
    _REPOSITORY,
    _TRANSFER_DETECTION,
    _TRANSFER_PAIRS,
    _ENTRY_READS,
    _ORM,
    _CONTRACT,
)

_WORKER_CONVERGENCE = (
    "select(AtomicTransaction.id)",
    ".with_for_update()",
    "return await self.get_active_match(txn_id)",
)
_DISPOSITION_UNIQUE = (
    "disposition_id: Mapped[UUID]",
    "nullable=False,\n        unique=True",
)


def _normal_candidate_first(repo_root: Path) -> list[str]:
    source = read_source(repo_root, _MATCHING)
    normal = source.find("await run_normal_matching_phase(")
    transfer = source.find("await run_transfer_detection_phase(")
    if normal < 0 or transfer < 0 or normal >= transfer:
        return [f"{_MATCHING}: transfer fallback is not ordered after normal matching"]
    return []


def _currency_explicit(repo_root: Path) -> list[str]:
    tree = ast.parse(read_source(repo_root, _ENTRY_READS), filename=_ENTRY_READS)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    findings: list[str] = []
    for name in ("entry_total_amount", "entry_bank_side_amount"):
        function = functions.get(name)
        if function is None:
            findings.append(f"{_ENTRY_READS}: missing {name}")
            continue
        defaults = dict(
            zip(
                (argument.arg for argument in function.args.kwonlyargs),
                function.args.kw_defaults,
                strict=True,
            )
        )
        if "currency" not in defaults or defaults["currency"] is not None:
            findings.append(
                f"{_ENTRY_READS}: {name} must require keyword-only currency"
            )
    findings.extend(
        missing_fragments(
            repo_root,
            _ENTRY_READS,
            ("line.money.currency == target", "Money.sum(debits, currency=target)"),
        )
    )
    return findings


def _typed_ledger_boundary(repo_root: Path) -> list[str]:
    source = read_source(repo_root, _TRANSFER_DETECTION)
    findings = []
    claim = source.find("await repository.claim_transaction(txn.id)")
    out_command = source.find("await create_transfer_out_entry(")
    in_command = source.find("await create_transfer_in_entry(")
    if (
        claim < 0
        or out_command < 0
        or in_command < 0
        or claim >= min(out_command, in_command)
    ):
        findings.append(
            f"{_TRANSFER_DETECTION}: typed ledger commands are not claim-guarded"
        )
    for constructor in ("JournalEntry(", "JournalLine("):
        if constructor in source:
            findings.append(
                f"{_TRANSFER_DETECTION}: owns forbidden {constructor} mutation"
            )
    return findings


_CHECKS = {
    "normal-candidate-first": _normal_candidate_first,
    "one-active-head": requires(
        _ORM,
        '"uq_reconciliation_matches_active_atomic_txn"',
        '"atomic_txn_id",\n            unique=True',
        "superseded_by_id IS NULL AND status NOT IN ('superseded'::reconciliation_status_enum, 'rejected'::reconciliation_status_enum)",
    ),
    "worker-convergence": requires(_REPOSITORY, *_WORKER_CONVERGENCE),
    "persistent-transfer-pair": all_of(
        requires(
            _ORM,
            "class ReconciliationTransferPair(",
            "class ReconciliationTransferPairLeg(",
            "decision: Mapped[TransferPairDecision]",
            "review_state: Mapped[TransferPairReviewState]",
            "version: Mapped[int]",
            *_DISPOSITION_UNIQUE,
        ),
        requires(
            _TRANSFER_PAIRS,
            "out_user_id != in_user_id",
            "out_direction != TransactionDirection.OUT",
            "in_direction != TransactionDirection.IN",
            "out_currency_code != in_currency_code",
        ),
    ),
    "currency-explicit": _currency_explicit,
    "idempotent-command": all_of(
        requires(_REPOSITORY, *_WORKER_CONVERGENCE),
        requires(
            _TRANSFER_PAIRS,
            "async with db.begin_nested():",
            "except IntegrityError:",
            "continue",
        ),
        requires(_ORM, *_DISPOSITION_UNIQUE),
    ),
    "typed-ledger-boundary": _typed_ledger_boundary,
    "exact-governance-detail": requires(
        _CONTRACT,
        'issue="https://github.com/wangzitian0/finance_report/issues/1994"',
        'id="economic-disposition-atomicity"',
        'required_proof_strength="concurrency"',
        'required_proof_strength="schema"',
        'required_proof_strength="value-oracle"',
        'enforcing_gate="ci.backend_integration"',
        'enforcing_gate="ci.backend"',
    ),
}


def detect_governance(*, repo_root: Path) -> list[dict[str, object]]:
    """Return one independently computed observation per package guarantee."""
    return run_detectors("reconciliation", _CHECKS, repo_root)


__all__ = ["GOVERNANCE_SOURCE_PATHS", "detect_governance"]
