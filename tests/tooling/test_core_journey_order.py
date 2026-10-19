"""AC-testing.journey-board.9: the core_journey corpus runs the journeys that fire a burst of provider calls last (#2534).

The twelve-month journey sends 12 statements in about 5 minutes. The zero-click journey ran right after it
and failed with `intent_missing` or a rate limit, while it passed alone. The corpus now runs the burst journey last.
"""

from __future__ import annotations

from common.testing import staging_ai_ocr_gate_contract as contract


def _files(nodes: list[str]) -> list[str]:
    return [node.split("::", 1)[0] for node in nodes]


def test_AC_testing_journey_board_9_the_burst_journeys_run_last() -> None:
    nodes = contract.core_journey_tests()
    files = _files(nodes)
    burst = [i for i, name in enumerate(files) if name in contract.CORE_JOURNEY_LAST]

    # The twelve-month journey is the burst that failed the zero-click journey.
    assert "tests/e2e/test_twelve_month_journey.py" in contract.CORE_JOURNEY_LAST
    assert burst, "the corpus holds no burst journey, so the list is stale"
    assert burst == list(range(len(nodes) - len(burst), len(nodes)))
    # The zero-click journey that failed after the burst now runs before it.
    zero_click = files.index("tests/e2e/test_zero_click_statement_journey.py")
    assert zero_click < min(burst)


def test_AC_testing_journey_board_9_the_other_journeys_keep_the_alphabetical_order() -> (
    None
):
    nodes = contract.core_journey_tests()
    rest = [n for n in nodes if n.split("::", 1)[0] not in contract.CORE_JOURNEY_LAST]

    assert rest == sorted(rest)


def test_AC_testing_journey_board_9_every_listed_burst_file_is_in_the_corpus() -> None:
    assert set(contract.CORE_JOURNEY_LAST) <= set(_files(contract.core_journey_tests()))
