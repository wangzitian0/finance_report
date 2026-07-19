"""Unit contract checks for package-facing journal contributions."""

from datetime import date
from uuid import uuid4

import pytest

from src.audit import TraceDecisionRef, VersionedTraceRef
from src.ledger import ResolvedJournalContribution


def test_AC_ledger_80_1_unproven_contribution_cannot_carry_an_authority_decision() -> None:
    """AC-ledger.80.1: unproven package facts cannot retain a DecisionAnchor."""
    decision = TraceDecisionRef(
        decision_id=uuid4(),
        target=VersionedTraceRef("journal_command", "entry-1", "1"),
        assertion=VersionedTraceRef("ledger_authority", "posted", "1"),
    )

    with pytest.raises(ValueError, match="unproven journal contribution cannot have a decision"):
        ResolvedJournalContribution(
            entry_id=uuid4(),
            entry_date=date(2026, 7, 19),
            lines=(),
            state="unproven",
            reason_code="missing_current_decision_anchor",
            decision=decision,
        )
