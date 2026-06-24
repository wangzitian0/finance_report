"""CounterKey validation — the package's self-owned SSOT term (EPIC-025 AC-counter.1.1)."""

import pytest
from common.testing.ac_proof import ac_proof

from src.counter import CounterKey, InvalidCounterKeyError

pytestmark = pytest.mark.no_db


@ac_proof(proof_id="test_counter_key_valid", ac_ids=["AC-counter.1.1"], ci_tier="pr_ci")
def test_counter_key_accepts_valid():
    """AC-counter.1.1: valid lowercase dotted 'domain.action' keys construct."""
    for value in ("report.generated", "statement.uploaded", "a.b.c", "user.signed_in"):
        assert str(CounterKey(value)) == value


@ac_proof(proof_id="test_counter_key_invalid", ac_ids=["AC-counter.1.1"], ci_tier="pr_ci")
def test_counter_key_rejects_invalid():
    """AC-counter.1.1: malformed keys are unrepresentable (InvalidCounterKeyError)."""
    invalid = [
        "",  # empty
        "report",  # not dotted (no namespace)
        "Report.Generated",  # uppercase
        "report..generated",  # empty segment
        ".report",  # leading dot
        "report.",  # trailing dot
        "report generated",  # space
        "report-generated",  # hyphen, not dotted
        "1report.generated",  # segment must start with a letter
    ]
    for value in invalid:
        with pytest.raises(InvalidCounterKeyError):
            CounterKey(value)


@ac_proof(proof_id="test_counter_key_value_object", ac_ids=["AC-counter.1.1"], ci_tier="pr_ci")
def test_counter_key_is_frozen_value_object():
    """AC-counter.1.1: keys are equal/hashable by value and immutable."""
    a, b = CounterKey("report.generated"), CounterKey("report.generated")
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    with pytest.raises(Exception):
        a.value = "other.key"  # type: ignore[misc]
