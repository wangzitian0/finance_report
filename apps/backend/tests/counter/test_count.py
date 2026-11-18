import pytest
from src.counter import Count, NegativeCountError

pytestmark = pytest.mark.no_db


def test_count_accepts_zero_and_positive():
    assert (int(Count(0)), int(Count(7)), Count(5)) == (0, 7, Count(5)) and Count(3) < Count(4)


@pytest.mark.parametrize("bad", [-1, True])
def test_count_rejects_negative(bad):
    with pytest.raises(NegativeCountError):
        Count(bad)
