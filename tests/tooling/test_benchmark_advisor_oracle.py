"""AC-testing.benchmarks.10: the Bench V2 AI advisor oracle (Pillar 1) judges the words after a heading (#2484).

Before this change, any answer with the words "discrepancy check" passed Pillar 1,
whatever followed them. A heading that reported a finding was treated as a heading
that negated one. Each test below fails on that behavior or guards against fixing it too far.
"""

from __future__ import annotations

import pytest

from tools._lib.benchmarks.oracles import assert_ai_advisor_semantic_grounding

FIGURES = ["24,200"]


@pytest.mark.parametrize(
    "heading",
    [
        "### Discrepancy Check — No Imbalances Found ✅",
        "### Discrepancy Check: Passed",
        "Discrepancy review - none found",
        "Ledger discrepancy analysis: zero items",
        "Discrepancy Verification ✓",
    ],
)
def test_AC_testing_benchmarks_10_a_heading_that_negates_the_discrepancy_passes(
    heading: str,
) -> None:
    assert_ai_advisor_semantic_grounding(
        f"Net worth: SGD 24,200.00\n{heading}\nBoth methods agree.", FIGURES
    )


@pytest.mark.parametrize(
    "heading",
    [
        "### Discrepancy Check: assets exceed liabilities by 2,900",
        "### Discrepancy Check — Assets and liabilities differ by 120.00",
        "Discrepancy review: the totals differ",
        "Discrepancy Analysis shows SGD 8,749.25 unexplained",
    ],
)
def test_AC_testing_benchmarks_10_a_heading_that_reports_a_finding_fails(
    heading: str,
) -> None:
    with pytest.raises(AssertionError, match="token 'discrepancy'"):
        assert_ai_advisor_semantic_grounding(
            f"Net worth: SGD 24,200.00\n{heading}\n", FIGURES
        )


def test_AC_testing_benchmarks_10_a_negation_does_not_hide_a_second_discrepancy() -> (
    None
):
    answer = (
        "Net worth: SGD 24,200.00. No balance discrepancies found in the bank accounts. "
        "However, the brokerage statement has a discrepancy of SGD 40.00."
    )
    with pytest.raises(AssertionError, match="token 'discrepancy'"):
        assert_ai_advisor_semantic_grounding(answer, FIGURES)


def test_AC_testing_benchmarks_10_an_answer_without_the_expected_figure_fails() -> None:
    with pytest.raises(AssertionError, match="did not contain any expected figures"):
        assert_ai_advisor_semantic_grounding(
            "### Discrepancy Check: Passed\nAll accounts agree.", FIGURES
        )


def test_AC_testing_benchmarks_10_a_negation_word_inside_another_word_is_no_negation() -> (
    None
):
    with pytest.raises(AssertionError, match="token 'discrepancy'"):
        assert_ai_advisor_semantic_grounding(
            "Net worth: SGD 24,200.00. The casino discrepancy is SGD 40.00.", FIGURES
        )
