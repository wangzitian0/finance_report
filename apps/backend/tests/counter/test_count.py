
import pytest
from src.counter import Count, NegativeCountError

pytestmark = pytest.mark.no_db


def test_count_accepts_zero_and_positive():
    assert int(Count(0)) == 0
    assert int(Count(7)) == 7
    assert Count(3) < Count(4)
    assert Count(5) == Count(5)


def test_count_rejects_negative():
    with pytest.raises(NegativeCountError):
        Count(-1)
    with pytest.raises(NegativeCountError):
        Count(True)
