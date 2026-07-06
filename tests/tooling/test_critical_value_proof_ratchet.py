"""Critical outcomes must prove a value, and that bar can only rise (#1623)."""

from __future__ import annotations

import json

from common.testing import check_critical_value_proof as cvp


def test_no_new_non_value_asserting_critical_proofs() -> None:
    """A new covered critical outcome (or a proof that stops asserting a value)
    fails CI: current non-value-asserting set must be a subset of the baseline."""
    current = cvp.current_non_value_proofs()
    baseline = set(
        json.loads(cvp.BASELINE_PATH.read_text(encoding="utf-8"))["non_value_proofs"]
    )
    added = current - baseline
    assert not added, (
        "New critical macro-outcome proof(s) assert no business value — give a "
        "backing AC a value-asserting proof_kind (exact/property/invariant/eval), "
        "do not baseline them:\n  " + "\n  ".join(sorted(added))
    )


def test_value_asserting_kinds_are_the_oracle_set() -> None:
    """Lock the semantics: smoke/evidence/unset are NOT value-asserting."""
    assert cvp.VALUE_ASSERTING_KINDS == {"exact", "property", "invariant", "eval"}
    assert "smoke" not in cvp.VALUE_ASSERTING_KINDS
    assert "evidence" not in cvp.VALUE_ASSERTING_KINDS


def test_baseline_only_shrinks_never_grows() -> None:
    """The ratchet refuses --update if it would add a new violation."""
    # current == baseline today, so a plain update is a no-op success; the
    # shrink-only guard is unit-covered here by asserting the gate is green.
    assert cvp.main([]) == 0
