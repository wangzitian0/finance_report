"""Focused unit tests for reconciliation threshold and rerun behavior.

AC4.6.1 AC4.6.2: Score thresholds and amount boundaries are enforced.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))

import src.models._registry  # noqa: E402, F401  -- register all ORM mappers before relationship config
from src.models.reconciliation import (  # noqa: E402
    ReconciliationMatch,
    ReconciliationStatus,
)

# Pre-cache real submodule deps so the isolated reconciliation load (which stubs
# src.services) can still resolve them after the split into reconciliation_config etc.
from src.services import promotion_gate as _promotion_gate  # noqa: E402, F401


def _load_reconciliation_module():
    """Load reconciliation without importing src.services package exports."""
    previous_services = sys.modules.get("src.services")
    previous_accounting = sys.modules.get("src.services.accounting")
    previous_logger = sys.modules.get("src.logger")
    # The processing-account transfer verbs were folded into the ledger package
    # (#1420 slice 3b): reconciliation now imports them from ``src.ledger`` instead
    # of ``src.services.processing_account``, so we stub ``src.ledger`` here.
    previous_ledger = sys.modules.get("src.ledger")
    previous_source_type_priority = sys.modules.get("src.services.source_type_priority")
    previous_statement_summary = sys.modules.get("src.services.statement_summary")

    # A dedicated stub exception (not bare ValueError) so production
    # ``except ValidationError`` blocks catch only this type — an unrelated
    # ValueError must still surface, exactly as it would against the real
    # ``src.ledger.ValidationError``.
    class _StubValidationError(Exception):
        pass

    services_package = ModuleType("src.services")
    services_package.__path__ = []  # type: ignore[attr-defined]
    accounting_module = ModuleType("src.services.accounting")
    accounting_module.ValidationError = _StubValidationError
    accounting_module.validate_journal_balance = Mock()
    logger_module = ModuleType("src.logger")
    logger_module.get_logger = Mock(return_value=Mock())
    ledger_module = ModuleType("src.ledger")
    ledger_module.ValidationError = _StubValidationError
    ledger_module.validate_journal_balance = Mock()
    ledger_module.create_transfer_in_entry = AsyncMock()
    ledger_module.create_transfer_out_entry = AsyncMock()
    ledger_module.detect_transfer_pattern = Mock(return_value=False)
    ledger_module.find_transfer_pairs = AsyncMock(return_value=[])
    source_type_priority_module = ModuleType("src.services.source_type_priority")
    source_type_priority_module.promote_entry_source_type = Mock(return_value=False)
    source_type_priority_module.source_type_rank = Mock(return_value=0)
    statement_summary_module = ModuleType("src.services.statement_summary")
    statement_summary_module.resolve_custody_account_id = AsyncMock(return_value=None)

    sys.modules["src.services"] = services_package
    sys.modules["src.services.accounting"] = accounting_module
    sys.modules["src.logger"] = logger_module
    sys.modules["src.ledger"] = ledger_module
    sys.modules["src.services.source_type_priority"] = source_type_priority_module
    sys.modules["src.services.statement_summary"] = statement_summary_module

    # reconciliation.py was split into focused submodules; load them (in dependency
    # order: config -> scoring -> stats) under their real names so reconciliation's
    # re-export imports resolve inside this isolated environment.
    split_submodules = (
        "reconciliation_config",
        "reconciliation_scoring",
        "reconciliation_stats",
    )
    services_dir = REPO_ROOT / "apps" / "backend" / "src" / "services"
    previous_submodules = {
        name: sys.modules.get(f"src.services.{name}") for name in split_submodules
    }
    try:
        for submodule_name in split_submodules:
            sub_spec = importlib.util.spec_from_file_location(
                f"src.services.{submodule_name}", services_dir / f"{submodule_name}.py"
            )
            assert sub_spec is not None and sub_spec.loader is not None
            sub_module = importlib.util.module_from_spec(sub_spec)
            sys.modules[f"src.services.{submodule_name}"] = sub_module
            sub_spec.loader.exec_module(sub_module)

        spec = importlib.util.spec_from_file_location(
            "_reconciliation_under_test",
            services_dir / "reconciliation.py",
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for submodule_name in split_submodules:
            previous = previous_submodules[submodule_name]
            if previous is None:
                sys.modules.pop(f"src.services.{submodule_name}", None)
            else:
                sys.modules[f"src.services.{submodule_name}"] = previous
        if previous_services is None:
            sys.modules.pop("src.services", None)
        else:
            sys.modules["src.services"] = previous_services
        if previous_accounting is None:
            sys.modules.pop("src.services.accounting", None)
        else:
            sys.modules["src.services.accounting"] = previous_accounting
        if previous_logger is None:
            sys.modules.pop("src.logger", None)
        else:
            sys.modules["src.logger"] = previous_logger
        if previous_ledger is None:
            sys.modules.pop("src.ledger", None)
        else:
            sys.modules["src.ledger"] = previous_ledger
        if previous_source_type_priority is None:
            sys.modules.pop("src.services.source_type_priority", None)
        else:
            sys.modules["src.services.source_type_priority"] = (
                previous_source_type_priority
            )
        if previous_statement_summary is None:
            sys.modules.pop("src.services.statement_summary", None)
        else:
            sys.modules["src.services.statement_summary"] = previous_statement_summary


reconciliation_module = _load_reconciliation_module()
MatchCandidate = reconciliation_module.MatchCandidate
execute_matching = reconciliation_module.execute_matching


class _ScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> _ScalarResult:
        return self

    def __iter__(self):
        return iter(self._items)

    def all(self) -> list[object]:
        return self._items

    def scalar_one_or_none(self) -> object | None:
        if not self._items:
            return None
        return self._items[0]


def _make_pending_txn() -> SimpleNamespace:
    # Mimics a pending Layer-2 AtomicTransaction (no per-row status column).
    return SimpleNamespace(
        id=uuid4(),
        statement_id=uuid4(),
        txn_date=date(2024, 5, 20),
        description="Payroll transfer",
        amount=Decimal("100.00"),
        direction="IN",
    )


def _make_entry() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        entry_date=date(2024, 5, 20),
        memo="Payroll transfer",
    )


def _make_db(*, txn: object, entry: object) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult([txn]),
            _ScalarResult([entry]),
            _ScalarResult([]),
        ]
    )
    db.flush = AsyncMock()
    db.add = Mock()
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "expected_status", "expected_match_count"),
    [
        (85, ReconciliationStatus.AUTO_ACCEPTED, 1),
        (84, ReconciliationStatus.PENDING_REVIEW, 1),
        (60, ReconciliationStatus.PENDING_REVIEW, 1),
        (59, None, 0),
    ],
)
async def test_execute_matching_score_thresholds(
    score: int,
    expected_status: ReconciliationStatus | None,
    expected_match_count: int,
) -> None:
    """AC4.3.1 · AC4.3.2 · Scores map to auto-accept, review, and unmatched bands."""
    txn = _make_pending_txn()
    entry = _make_entry()
    db = _make_db(txn=txn, entry=entry)

    candidate = MatchCandidate(
        journal_entry_ids=[],
        score=score,
        breakdown={"amount": 100.0},
    )

    with (
        patch.object(
            reconciliation_module, "detect_transfer_pattern", return_value=False
        ),
        patch.object(reconciliation_module, "is_entry_balanced", return_value=True),
        patch.object(
            reconciliation_module, "score_pattern", new=AsyncMock(return_value=0.0)
        ),
        patch.object(
            reconciliation_module,
            "calculate_match_score",
            new=AsyncMock(return_value=candidate),
        ),
        patch.object(
            reconciliation_module, "find_transfer_pairs", new=AsyncMock(return_value=[])
        ),
        patch.object(
            reconciliation_module,
            "_get_existing_active_match",
            new=AsyncMock(return_value=None),
        ),
    ):
        matches = await execute_matching(db, user_id=uuid4())

    assert len(matches) == expected_match_count
    # bank-txn.status is no longer mutated under the Layer-2 read path (Stage 3 removes it)

    if expected_status is None:
        db.add.assert_not_called()
        return

    db.add.assert_called_once()
    created_match = db.add.call_args.args[0]
    assert isinstance(created_match, ReconciliationMatch)
    assert created_match.status == expected_status
    assert created_match.match_score == score
    assert matches[0] is created_match


@pytest.mark.asyncio
async def test_execute_matching_rerun_is_idempotent_for_same_match() -> None:
    """AC4.6.2 · Rerunning reconciliation with the same winning entry creates no duplicate match."""
    txn = _make_pending_txn()
    entry = _make_entry()
    db = _make_db(txn=txn, entry=entry)

    existing_match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=92,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    candidate = MatchCandidate(
        journal_entry_ids=[str(entry.id)],
        score=92,
        breakdown={"amount": 100.0},
    )

    with (
        patch.object(
            reconciliation_module, "detect_transfer_pattern", return_value=False
        ),
        patch.object(reconciliation_module, "is_entry_balanced", return_value=True),
        patch.object(
            reconciliation_module, "score_pattern", new=AsyncMock(return_value=0.0)
        ),
        patch.object(
            reconciliation_module,
            "calculate_match_score",
            new=AsyncMock(return_value=candidate),
        ),
        patch.object(
            reconciliation_module, "find_transfer_pairs", new=AsyncMock(return_value=[])
        ),
        patch.object(
            reconciliation_module,
            "_get_existing_active_match",
            new=AsyncMock(return_value=existing_match),
        ),
    ):
        matches = await execute_matching(db, user_id=uuid4())

    assert matches == []
    assert existing_match.status == ReconciliationStatus.AUTO_ACCEPTED
    db.add.assert_not_called()
