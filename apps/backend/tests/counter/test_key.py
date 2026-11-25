import pytest
from src.counter import CounterKey, InvalidCounterKeyError

pytestmark = pytest.mark.no_db


def test_counter_key_accepts_valid():
    assert all(
        (
            str(CounterKey(value)) == value
            for value in ("report.generated", "statement.uploaded", "a.b.c", "user.signed_in")
        )
    )


def test_counter_key_rejects_invalid():
    invalid = [
        "",
        "report",
        "Report.Generated",
        "report..generated",
        ".report",
        "report.",
        "report generated",
        "report-generated",
        "1report.generated",
    ]
    for value in invalid:
        with pytest.raises(InvalidCounterKeyError):
            CounterKey(value)


def test_counter_key_is_frozen_value_object():
    a, b = (CounterKey("report.generated"), CounterKey("report.generated"))
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    with pytest.raises(Exception):
        a.value = "other.key"
