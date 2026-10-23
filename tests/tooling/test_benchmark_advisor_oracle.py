"""AC-testing.benchmarks.10: the Bench V2 AI advisor oracle (Pillar 1) reads the words after a heading (#2484).

Pillar 1 fails an advisor answer that reports a discrepancy or a ledger imbalance. It passes an
answer that only negates one. The oracle is a keyword check. It reads the first words after a
heading. It does not read a clause that contradicts them.

The earlier oracle passed every answer with the words "discrepancy check", whatever followed.
AC-testing.benchmarks.17 and 18 (#2633) add the section rule. A markdown label heading is neutral
when the section of the heading holds a negated verdict with no hedge word. AC 17 holds the
accepted shapes. AC 18 holds the bounds: a heading that states a finding, an explanation, a hedge
word, a verdict in another section and a claim in the section stay failures. Real advisor answer H01
comes from run 39755911927. Mutated claims F01 to F75 must fail.

This file has three groups of tests:
- Rule tests. Each rule has a test that fails when the rule is removed.
- A labeled corpus of 165 advisor answers in English and Chinese. The label says what the oracle must do.
  One answer is a real advisor answer from a staging run (2026-10-09, run 37968832947).
  One answer is the real failing answer of #2633 (2026-10-22, run 39755911927).
- Known limits. A limit is a corpus answer that the oracle judges wrongly. It has a strict xfail.
  When a change fixes a limit, the strict xfail fails. Then move the entry to the passing list.
"""

from __future__ import annotations

import pytest

from common.testing.benchmarks.oracles import assert_ai_advisor_semantic_grounding

FIGURES = ["24,200"]


def passes(answer: str) -> bool:
    try:
        assert_ai_advisor_semantic_grounding(answer, FIGURES)
    except AssertionError:
        return False
    return True


def failed_token(answer: str) -> str:
    with pytest.raises(AssertionError, match=r"token '([^']+)'") as error:
        assert_ai_advisor_semantic_grounding(answer, FIGURES)
    # A token can hold an apostrophe: "doesn't balance". Cut at the end of the quoted token.
    return error.value.args[0].split("token '")[1].split("' in response:")[0]


def net(text: str) -> str:
    return f"Net worth: SGD 24,200.00\n{text}\n"


# ------------------------------------------------------------------- rule tests


@pytest.mark.parametrize(
    "heading",
    [
        "### Discrepancy Check \u2014 No Imbalances Found \u2705",
        "### Discrepancy Check: Passed",
        "Discrepancy review - none found",
        "Ledger discrepancy analysis: zero items",
        "Discrepancy Verification \u2713",
        "**Discrepancy Check:** None found.",
        "### Discrepancy Check \u2714",
        "### Discrepancy Check: All clear \u2705",
        "Discrepancy check: Balanced \u2705",
        "| Discrepancy check | \u2705 None |",
        "### Discrepancy Check (Balance Sheet vs Ledger): No discrepancies",
        "Discrepancy check result: no discrepancies.",
        "### Discrepancy Checks: None",
        "Discrepancy check\uff1a\u65e0",
        "The discrepancy check found nothing.",
        "I ran a discrepancy check and everything balances.",
        "Discrepancy check: Not applicable \u2014 there are no discrepancies.",
    ],
)
def test_AC_testing_benchmarks_10_a_heading_with_a_clean_verdict_passes(
    heading: str,
) -> None:
    assert passes(net(heading))


@pytest.mark.parametrize(
    "heading",
    [
        "### Discrepancy Check: assets exceed liabilities by 2,900",
        "### Discrepancy Check \u2014 Assets and liabilities differ by 120.00",
        "Discrepancy review: the totals differ",
        "Discrepancy Analysis shows SGD 8,749.25 unexplained",
        "### Discrepancies Review: assets exceed liabilities plus equity by SGD 2,900",
        "Discrepancy check: Not balanced, assets exceed liabilities by SGD 2,900",
        "Discrepancy check \u2014 clear imbalance of SGD 2,900 between assets and liabilities.",
        "Discrepancy review: none of the transfers were matched, so SGD 2,900 is unreconciled.",
        "Discrepancy analysis: zero-balance accounts excluded; assets exceed liabilities by SGD 2,900.",
    ],
)
def test_AC_testing_benchmarks_10_a_heading_that_reports_a_finding_fails(
    heading: str,
) -> None:
    assert not passes(net(heading))


def test_AC_testing_benchmarks_10_a_plural_finding_names_the_plural_token() -> None:
    assert (
        failed_token(
            net("I found two discrepancies: the brokerage account is SGD 40.00 short.")
        )
        == "discrepancies"
    )


def test_AC_testing_benchmarks_10_a_negation_does_not_hide_a_second_discrepancy() -> (
    None
):
    answer = (
        "Net worth: SGD 24,200.00. No balance discrepancies found in the bank accounts. "
        "However, the brokerage statement has a discrepancy of SGD 40.00."
    )
    assert failed_token(answer) == "discrepancy"


@pytest.mark.parametrize(
    "sentence",
    [
        "The casino discrepancy is SGD 40.00.",
        "The casino discrepancy found in March is SGD 40.00.",
        "There is a non-zero discrepancy of SGD 2,900.",
        "The ledger shows a nonzero discrepancy of SGD 2,900.",
    ],
)
def test_AC_testing_benchmarks_10_a_negation_word_inside_another_word_is_no_negation(
    sentence: str,
) -> None:
    assert not passes(net(sentence))


@pytest.mark.parametrize(
    "sentence",
    [
        "I did not find any discrepancy between the two methods.",
        "No significant discrepancies were found.",
        "_No discrepancy._ Both methods agree.",
        "This is a data-quality matter rather than a ledger imbalance.",
        "\u7ecf\u6838\u5bf9\uff0c\u6ca1\u6709\u53d1\u73b0\u4efb\u4f55\u5dee\u989d\u3002",
        "\u672a\u53d1\u73b0\u4efb\u4f55\u4e0d\u4e00\u81f4 \u2705",
    ],
)
def test_AC_testing_benchmarks_10_a_plain_negation_passes(sentence: str) -> None:
    assert passes(net(sentence))


def test_AC_testing_benchmarks_10_an_answer_without_the_expected_figure_fails() -> None:
    with pytest.raises(AssertionError, match="did not contain any expected figures"):
        assert_ai_advisor_semantic_grounding(
            "### Discrepancy Check: Passed\nAll accounts agree.", FIGURES
        )


# ----------------------------------------------------------------- labeled corpus

REAL_STAGING_ANSWER = """## Your Current Net Worth

**Net Worth: SGD 24,200.00**

## Balance Consistency Check \u2705

Good news \u2014 your books are fully consistent. Here's the verification:

**Check 1: Balance Sheet Equation**
- Total Assets (SGD 24,200.00) \u2212 Total Liabilities (SGD 0.00) = **SGD 24,200.00**
- Reported Net Worth = **SGD 24,200.00** \u2714 Matches

**Check 2: Equity Roll-Forward**
- Opening Equity (SGD 15,450.75) + Cumulative Net Income (SGD 8,749.25) = **SGD 24,200.00**
- Reported Net Worth = **SGD 24,200.00** \u2714 Matches

Both methods arrive at the same figure, and this balance sheet carries a **DETERMINISTIC confidence tier**, meaning it reflects fully verified application state. **No discrepancies found.**

## One Data Quality Note (Not a Balance Issue)

While your balance sheet is consistent, you do have **24 unmatched transactions** and a **0.0% reconciliation match rate**. This is a transaction-matching/data-quality matter rather than a ledger imbalance \u2014 but clearing those matches would strengthen the evidence behind your numbers.

## Suggested Next Step

Your report package is currently in **Ready** state with no blockers. You can review it via: **Open report package** (`/reports/package`)

The above analysis is for reference only.
"""

# ------------------------------------------- heading, prose, verdict (#2633)

# The advisor answer of run 39755911927 (Deploy Staging v0.2.26, job 119752716450, Case 1).
# Every figure ties and the answer says "no discrepancies found". The earlier oracle failed it:
# a full sentence stands between the heading and the verdict, in the same section.
REAL_FAILING_ANSWER_2633 = """# Net Worth & Balance Check

## Your Current Net Worth

**Net worth: SGD 24,200.00**

- Total assets: SGD 24,200.00
- Total liabilities: SGD 0.00
- Net worth = Total assets − Total liabilities = SGD 24,200.00 − SGD 0.00 = **SGD 24,200.00** ✓

## Balance Discrepancy Check

I verified the accounting consistency of your records, and **everything balances perfectly — no discrepancies found**:

| Check | Result |
|---|---|
| Opening equity (SGD 15,450.75) + Cumulative net income (SGD 8,749.25) | = SGD 24,200.00 ✓ |
| Net worth vs. Assets − Liabilities | Consistent ✓ |
| Unmatched transactions | 0 |
| Reconciliation match rate | 100.0% |
| Transactions pending review | 0 |
| Balance sheet confidence tier | DETERMINISTIC |

## Summary

Your ledger is fully reconciled: your equity components (opening equity plus cumulative net income of SGD 15,450.75 + SGD 8,749.25) exactly equal your net worth of SGD 24,200.00, and all recorded transactions have been matched. There are no blocking issues flagged in your advisor facts, so your report package is currently marked as **Ready** if you'd like to generate a full report.

The above analysis is for reference only.
"""

VERDICT_SENTENCE = (
    "I verified the accounting consistency of your records, and "
    "**everything balances perfectly — no discrepancies found**:"
)


def mutate(answer: str, old: str, new: str) -> str:
    """Replace one part of an answer. A part that is missing fails the test, so no mutant is a copy."""
    assert old in answer, old
    return answer.replace(old, new, 1)


# A clean answer: a review heading, then prose, then a clean verdict in the same section.
HEADING_PROSE_CLEAN: list[tuple[str, str]] = [
    ("H01", REAL_FAILING_ANSWER_2633),
    (
        "H02",
        "Net worth: SGD 24,200.00\n\n"
        "## Ledger Discrepancy Review\n\n"
        "I compared total assets, total liabilities and the equity roll-forward for all four months.\n"
        "Every figure ties to SGD 24,200.00, and **there are no discrepancies**.\n\n"
        "## Summary\n\nYour report package is ready.\n",
    ),
    (
        "H03",
        "Net worth: SGD 24,200.00\n\n"
        "### Are there any balance discrepancies?\n\n"
        "Good news. I computed net worth in two ways, and both give SGD 24,200.00. "
        "There are no discrepancies between the balance sheet and the ledger.\n",
    ),
    (
        "H04",
        "净资产：SGD 24,200.00\n\n"
        "## 账目差额检查\n\n"
        "我已核对您全部四个月的记录，资产、负债和权益都能相互对上。**没有发现任何差额**。\n\n"
        "## 小结\n\n您的报告包已就绪。\n",
    ),
    (
        "H05",
        "净资产：SGD 24,200.00\n\n"
        "### 余额不一致核对\n\n"
        "经逐项核对，期初权益加累计净利润等于净资产，资产减负债也等于净资产。结论：未发现任何不一致。\n",
    ),
    (
        "H06",
        "Net worth: SGD 24,200.00\n\n"
        "## Ledger Imbalance Check\n\n"
        "| Check | Result |\n|---|---|\n"
        "| Assets − Liabilities | SGD 24,200.00 |\n"
        "| Equity roll-forward | SGD 24,200.00 |\n\n"
        "Both rows agree, so there is no imbalance in your ledger.\n",
    ),
]

# A mutated claim. The oracle must fail it. The third field is the first token that the oracle names.
HEADING_PROSE_FINDING: list[tuple[str, str, str]] = [
    (
        "F01",
        mutate(
            REAL_FAILING_ANSWER_2633,
            VERDICT_SENTENCE,
            "I verified the accounting consistency of your records, and **found a discrepancy of SGD 2,900.00**:",
        ),
        "discrepancy",
    ),
    (
        "F02",
        mutate(
            REAL_FAILING_ANSWER_2633,
            "The above analysis is for reference only.",
            "The equity roll-forward shows a mismatch of SGD 2,900.00.",
        ),
        "mismatch",
    ),
    (
        "F03",
        mutate(
            REAL_FAILING_ANSWER_2633,
            "The above analysis is for reference only.",
            "Your brokerage account doesn't balance by SGD 40.00.",
        ),
        "doesn't balance",
    ),
    (
        "F04",
        mutate(
            REAL_FAILING_ANSWER_2633,
            VERDICT_SENTENCE,
            "I verified the accounting consistency of your records. "
            "**Assets exceed liabilities plus equity by SGD 2,900.00**:",
        ),
        "discrepancy",
    ),
    (
        "F05",
        mutate(
            REAL_FAILING_ANSWER_2633,
            "everything balances perfectly — no discrepancies found",
            "your books do not reconcile — discrepancies found",
        ),
        "discrepancy",
    ),
    (
        "F06",
        mutate(
            REAL_FAILING_ANSWER_2633,
            "everything balances perfectly — no discrepancies found",
            "everything is badly off",
        ),
        "discrepancy",
    ),
    (
        "F07",
        mutate(
            REAL_FAILING_ANSWER_2633,
            "## Summary",
            "## Brokerage Account\n\nThe brokerage account is unbalanced by SGD 40.00.\n\n## Summary",
        ),
        "unbalanced",
    ),
    (
        "F08",
        "Net worth: SGD 24,200.00\n\n"
        "## Balance Discrepancy Check\n\n"
        "Assets exceed liabilities plus equity by SGD 2,900.00.\n\n"
        "## Bank Accounts\n\nNo discrepancies found in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F09",
        "Net worth: SGD 24,200.00\n\n"
        "## Bank Accounts\n\nNo discrepancies found in the bank accounts.\n\n"
        "## Balance Discrepancy Check\n\n"
        "Assets exceed liabilities plus equity by SGD 2,900.00.\n",
        "discrepancy",
    ),
    (
        "F10",
        "Net worth: SGD 24,200.00\n\n"
        "## Balance Discrepancy Check\n\n"
        "Assets exceed liabilities plus equity by SGD 2,900.00.\n\n"
        "### Bank accounts\n\nNo discrepancies found in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F11",
        "Net worth: SGD 24,200.00\n\n"
        "### Discrepancy Check\n"
        "No discrepancies found in assets, but liabilities show a mismatch of SGD 2,900.00.\n",
        "mismatch",
    ),
    (
        "F12",
        "Net worth: SGD 24,200.00\n\n"
        "## Balance Discrepancy Check\n\n"
        "I reviewed every account. There are no discrepancies in assets, "
        "but liabilities show a mismatch of SGD 2,900.00.\n",
        "discrepancy",
    ),
    (
        "F13",
        "Net worth: SGD 24,200.00\n\n"
        "## Balance Discrepancy Check\n\n"
        "I reviewed every account. There are no discrepancies in assets, "
        "but liabilities are SGD 2,900.00 short.\n",
        "discrepancy",
    ),
    (
        "F14",
        "Net worth: SGD 24,200.00\n\n"
        "## Balance Discrepancy Check\n\n"
        "I reviewed every account. There are no discrepancies, except in the brokerage account.\n",
        "discrepancy",
    ),
    (
        "F15",
        "Net worth: SGD 24,200.00\n\n"
        "## Balance Discrepancy Check\n\n"
        "I reviewed every account. There are no discrepancies if you ignore the brokerage account.\n",
        "discrepancy",
    ),
    (
        "F16",
        "净资产：SGD 24,200.00\n\n"
        "## 账目差额检查\n\n"
        "我已核对全部记录。资产没有发现任何差额，但是负债多出 SGD 2,900。\n",
        "差额",
    ),
    (
        "F17",
        "Net worth: SGD 24,200.00\n\n"
        "## Discrepancy of SGD 2,900.00 Found\n\n"
        "I confirm that there are no discrepancies in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F18",
        "Net worth: SGD 24,200.00\n\n"
        "## Discrepancy Found in Brokerage\n\n"
        "I confirm that there are no discrepancies in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F19",
        "净资产：SGD 24,200.00\n\n## 账目差额检查\n\n我已核对您的记录。资产比负债加权益多 SGD 2,900。\n",
        "差额",
    ),
    (
        "F20",
        "净资产：SGD 24,200.00\n\n## 账目差额检查\n\n经核对，存在差额 SGD 2,900，账目不平。\n",
        "不平",
    ),
    (
        "F21",
        "净资产：SGD 24,200.00\n\n"
        "## 账目差额检查\n\n没有发现任何差额。\n\n"
        "## 券商账户\n\n券商账户与对账单不一致，相差 SGD 40.00。\n",
        "不一致",
    ),
]

# Review round 1 of PR #2638 found false passes. The rows below close them. Each label word,
# each end noun and each hedge word has one row, so a mutation that drops a word turns a row red.
NET = "Net worth: SGD 24,200.00\n\n"
NET_ZH = "净资产：SGD 24,200.00\n\n"
PROSE_EN = "I compared the totals for all four months. There are no discrepancies."
PROSE_ZH = "我已核对全部记录，**没有发现任何差额**。"
LABEL_HEADINGS_EN = [
    "## Accounts Discrepancy Verification",
    "## Accounting Imbalance Analysis",
    "## Ledger Mismatch Audit",
    "## Balance Discrepancy Assessment",
    "## Account Reconciliation Discrepancy Report",
    "## Discrepancy Summary",
    "## Discrepancy Check Results",
    "## Discrepancy Status",
    "## The Ledger and Account Discrepancy Reviews",
    "## Your Balance Discrepancy Checks",
    "## Discrepancy Analyses",
    "## Discrepancy Check Result",
    "## Are there any discrepancies?",
    "## **Balance Discrepancy Check**",
    "## Balance Discrepancy Check:",
    "### Balance Discrepancy Check ###",
]
LABEL_HEADINGS_ZH = [
    "## 账务差额校验",
    "## 对账差额复核",
    "## 差额审核结果",
    "## 账目与余额差额核对",
    "## 账目和余额不一致情况",
    "## 差额及不一致检查",
]
HEADING_PROSE_CLEAN += [
    (f"H{number:02d}", f"{NET}{heading}\n\n{PROSE_EN}\n")
    for number, heading in enumerate(LABEL_HEADINGS_EN, start=7)
] + [
    (f"H{number:02d}", f"{NET_ZH}{heading}\n\n{PROSE_ZH}\n")
    for number, heading in enumerate(
        LABEL_HEADINGS_ZH, start=7 + len(LABEL_HEADINGS_EN)
    )
]

REVIEWED = "## Balance Discrepancy Check\n\nI reviewed every account. "
REVIEWED_ZH = "## 账目差额检查\n\n我已核对全部记录。"
# One sentence per hedge word. A hedge word in the verdict sentence keeps the heading a failure.
HEDGED_VERDICTS_EN = [
    "There are no discrepancies in assets, but liabilities are SGD 2,900.00 short.",
    "There are no discrepancies in assets, however liabilities are SGD 2,900.00 short.",
    "There are no discrepancies, except in the brokerage account.",
    "With the exception of the brokerage account, there are no discrepancies.",
    "Excluding the brokerage account, there are no discrepancies.",
    "Although liabilities look odd, there are no discrepancies.",
    "There are no discrepancies, though the brokerage feed is late.",
    "There are no discrepancies unless the statement changes.",
    "There are no discrepancies in assets, whereas liabilities are SGD 2,900.00 short.",
    "There are no discrepancies, while the brokerage account is SGD 40.00 short.",
    "There are no discrepancies in the bank accounts only.",
    "There are no discrepancies if you ignore the brokerage account.",
    "Assuming the statements are complete, there are no discrepancies.",
    "There are almost no discrepancies.",
    "There are nearly no discrepancies.",
    "Apart from the brokerage account, there are no discrepancies.",
    "Other than the brokerage account, there are no discrepancies.",
    "Aside from the brokerage account, there are no discrepancies.",
    "It would be wrong to say that there are no discrepancies.",
    "It is unclear whether there are no discrepancies.",
    "I am unable to say that there are no discrepancies.",
    "I am not sure that there are no discrepancies.",
    "I cannot confirm that there are no discrepancies.",
    "I can't confirm that there are no discrepancies.",
    "Is it true that there are no discrepancies?",
    "There is no mismatch vs. the statement, but the cash account is SGD 40.00 short.",
]
HEDGED_VERDICTS_ZH = [
    "资产没有发现任何差额，但负债多出 SGD 2,900。",
    "资产没有发现任何差额，不过负债多出 SGD 2,900。",
    "除券商账户外，没有发现任何差额。",
    "资产没有发现任何差额，而负债多出 SGD 2,900。",
    "资产没有发现任何差额，可是负债多出 SGD 2,900。",
    "资产没有发现任何差额，负债却多出 SGD 2,900。",
    "仅银行账户没有发现任何差额。",
    "资产没有发现任何差额，只是负债多出 SGD 2,900。",
    "如果忽略券商账户，没有发现任何差额。",
    "假设对账单完整，没有发现任何差额。",
    "几乎没有发现任何差额。",
    "我无法确认没有发现任何差额。",
]
HEADING_PROSE_FINDING += [
    # A heading that states a finding stays a failure, whatever the section says.
    (
        "F22",
        f"{NET}## There Is a Discrepancy\n\nThe bank accounts show no mismatch.\n",
        "discrepancy",
    ),
    (
        "F23",
        f"{NET}## Result: Imbalance\n\nThere are no discrepancies in the bank accounts.\n",
        "imbalance",
    ),
    (
        "F24",
        f"{NET}## Final Status: Mismatch\n\nThere are no discrepancies in the bank accounts.\n",
        "mismatch",
    ),
    (
        "F25",
        f"{NET}## Discrepancy Found\n\nThere are no discrepancies in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F26",
        f"{NET}## Discrepancy ⚠️\n\nThere are no mismatches in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F27",
        f"{NET}## Balance ❌ Discrepancy Check\n\nThere are no mismatches in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F28",
        f"{NET}## Balance Discrepancy 2900 Check\n\nThere are no mismatches in the bank accounts.\n",
        "discrepancy",
    ),
    (
        "F29",
        f"{NET_ZH}## 结论：账目不一致\n\n银行账户没有发现任何差额。\n",
        "不一致",
    ),
    (
        "F30",
        f"{NET_ZH}## 账目与余额不一致\n\n银行账户没有发现任何差额。\n",
        "不一致",
    ),
    # A heading that holds a negation and a second claim stays a failure.
    (
        "F31",
        f"{NET}## No Discrepancies and Imbalance Check\n\nThe bank accounts show no mismatch.\n",
        "imbalance",
    ),
    # An explanation is no verdict on the ledger.
    (
        "F32",
        f"{NET}{REVIEWED}This does not indicate a mismatch in the bank feed.\n",
        "discrepancy",
    ),
    (
        "F33",
        f"{NET}{REVIEWED}This is a data-quality matter rather than a ledger imbalance.\n",
        "discrepancy",
    ),
    # The private marker of the oracle in the answer text is no verdict.
    (
        "F35",
        f"{NET}{REVIEWED}Assets exceed liabilities plus equity by SGD 2,900.00 [negated_verdict]\n",
        "discrepancy",
    ),
    # A heading in a code fence is no heading.
    (
        "F34",
        f"{NET}```\n## Balance Discrepancy Check\nthere are no discrepancies\n```\n",
        "discrepancy",
    ),
]
HEADING_PROSE_FINDING += [
    (f"F{number}", f"{NET}{REVIEWED}{sentence}\n", "discrepancy")
    for number, sentence in enumerate(HEDGED_VERDICTS_EN, start=36)
] + [
    (f"F{number}", f"{NET_ZH}{REVIEWED_ZH}{sentence}\n", "差额")
    for number, sentence in enumerate(
        HEDGED_VERDICTS_ZH, start=36 + len(HEDGED_VERDICTS_EN)
    )
]
HEADING_PROSE_FINDING += [
    # A heading that states the finding before its label words stays a failure.
    (
        "F73",
        f"{NET}## Assets Exceed Liabilities Discrepancy Check\n\n{PROSE_EN}\n",
        "discrepancy",
    ),
    # A verdict inside a code fence is no verdict.
    (
        "F74",
        f"{NET}## Balance Discrepancy Check\n\n```\nthere are no discrepancies\n```\n",
        "discrepancy",
    ),
    # A heading inside a code fence is no heading, also when a verdict follows the fence.
    (
        "F75",
        f"{NET}```\n## Balance Discrepancy Check\n```\nThere are no discrepancies.\n",
        "discrepancy",
    ),
]


def test_AC_testing_benchmarks_17_the_real_answer_of_run_39755911927_passes() -> None:
    """AC-testing.benchmarks.17: the correct advisor answer of the failed staging run passes."""
    assert passes(REAL_FAILING_ANSWER_2633)


@pytest.mark.parametrize(
    ("case_id", "answer"),
    HEADING_PROSE_CLEAN,
    ids=[row[0] for row in HEADING_PROSE_CLEAN],
)
def test_AC_testing_benchmarks_17_a_clean_verdict_in_the_section_of_the_heading_passes(
    case_id: str, answer: str
) -> None:
    assert passes(answer), case_id


@pytest.mark.parametrize(
    ("case_id", "answer", "token"),
    HEADING_PROSE_FINDING,
    ids=[row[0] for row in HEADING_PROSE_FINDING],
)
def test_AC_testing_benchmarks_18_a_mutated_claim_still_fails_and_names_its_token(
    case_id: str, answer: str, token: str
) -> None:
    """AC-testing.benchmarks.18: each mutated claim fails and the message names the first token."""
    assert failed_token(answer) == token, case_id


CORPUS: list[tuple[str, str, str]] = [
    (
        "E01",
        "CLEAN",
        "## Your Current Net Worth\n**Net Worth: SGD 24,200.00**\n### Discrepancy Check — No Imbalances Found ✅\nBoth calculation methods arrive at the same figure.",
    ),
    (
        "E02",
        "CLEAN",
        "**Net Worth:** SGD 24,200.00\n\n**Discrepancy Check:** None found. Assets minus liabilities equals equity.",
    ),
    (
        "E03",
        "CLEAN",
        "**Net Worth:** SGD 24,200.00\n\n**Discrepancy Check**\n- No discrepancies found between the balance sheet and the ledger.",
    ),
    (
        "E04",
        "CLEAN",
        "Net worth: SGD 24,200.00\n\nDiscrepancy check:\n- No discrepancies between assets and equity.\n- Both methods give SGD 24,200.00.",
    ),
    (
        "E05",
        "CLEAN",
        "| Item | Result |\n|---|---|\n| Net worth | SGD 24,200.00 |\n| Discrepancy check | ✅ None |",
    ),
    (
        "E06",
        "CLEAN",
        "### Discrepancy Check: All clear ✅\nNet worth is SGD 24,200.00.",
    ),
    (
        "E07",
        "CLEAN",
        "Net worth: SGD 24,200.00\n### Discrepancy Check ✔\nAssets = Liabilities + Equity.",
    ),
    ("E08", "CLEAN", "Net worth: SGD 24,200.00\nDiscrepancy check: Balanced ✅"),
    (
        "E09",
        "FINDING",
        "Net worth: SGD 24,200.00\n### Discrepancy Check: assets exceed liabilities plus equity by SGD 2,900",
    ),
    (
        "E10",
        "FINDING",
        "Net worth: SGD 24,200.00\n### Discrepancy Check: assets exceed equity by SGD 2,900 ✅ flagged for review",
    ),
    (
        "E12",
        "FINDING",
        "Your net worth is SGD 24,200.00. No discrepancies were found in the bank accounts, but there is a mismatch of SGD 40.00 in the brokerage account.",
    ),
    (
        "E15",
        "FINDING",
        "Net worth: SGD 24,200.00. I found two discrepancies: the brokerage account is SGD 40.00 short, and the credit card is SGD 80.00 over the statement.",
    ),
    (
        "E16",
        "FINDING",
        "## Net Worth: SGD 24,200.00\n## Discrepancies\n- Brokerage account: SGD 40.00 short\n- Credit card: SGD 80.00 over",
    ),
    (
        "E17",
        "FINDING",
        "Net worth: SGD 24,200.00. There is a non-zero discrepancy of SGD 2,900 between assets and liabilities plus equity.",
    ),
    (
        "E18",
        "FINDING",
        "Net worth: SGD 24,200.00. The ledger shows a nonzero discrepancy of SGD 2,900.",
    ),
    (
        "E19",
        "FINDING",
        "Net worth: SGD 24,200.00. The casino discrepancy found in March is SGD 40.00.",
    ),
    (
        "E20",
        "FINDING",
        "Net worth: SGD 24,200.00. The casino discrepancy is SGD 40.00.",
    ),
    ("E21", "CLEAN", "Net worth: SGD 24,200.00. Liabilities are zero. No imbalance."),
    (
        "E22",
        "FINDING",
        "Net worth: SGD 24,200.00\nDiscrepancy review: none of the transfers were matched, so SGD 2,900 is unreconciled.",
    ),
    (
        "E23",
        "FINDING",
        "Net worth: SGD 24,200.00\nDiscrepancy analysis: zero-balance accounts excluded; assets exceed liabilities plus equity by SGD 2,900.",
    ),
    (
        "E24",
        "CLEAN",
        "NET WORTH: SGD 24,200.00. DISCREPANCY CHECK: PASSED. NO IMBALANCE DETECTED.",
    ),
    (
        "E25",
        "FINDING",
        "NET WORTH: SGD 24,200.00. DISCREPANCY CHECK: FAILED — the ledger is off by SGD 2,900.",
    ),
    (
        "E26",
        "CLEAN",
        "Net worth: SGD 24,200.00. No significant discrepancies were found.",
    ),
    (
        "E27",
        "CLEAN",
        "Net worth: SGD 24,200.00. I did not find any discrepancy between the two methods.",
    ),
    ("E28", "CLEAN", REAL_STAGING_ANSWER),
    (
        "E29",
        "FINDING",
        "Net worth: SGD 24,200.00. Your balance sheet doesn't balance: assets exceed liabilities plus equity by SGD 2,900.",
    ),
    ("E30", "CLEAN", "Net worth: SGD 24,200.00. _No discrepancy._ Both methods agree."),
    ("E31", "CLEAN", "Net worth: SGD 24,200.00\n### Discrepancy Checks: None\n"),
    (
        "E32",
        "CLEAN",
        "**Net Worth: SGD 24,200.00**\n**Balance Consistency Check — No Discrepancies Found ✓**\n**A Quick Observation on Data Quality (Not a Discrepancy):**\nThis doesn't create an imbalance in your net worth calculation.",
    ),
    (
        "E33",
        "CLEAN",
        "Net worth: SGD 24,200.00\nDiscrepancy check: Not applicable — there are no discrepancies.",
    ),
    (
        "E34",
        "CLEAN",
        "Net worth: SGD 24,200.00\n### Discrepancy Check (Balance Sheet vs Ledger): No discrepancies",
    ),
    (
        "E36",
        "FINDING",
        "Net worth: SGD 24,200.00\nDiscrepancy check — clear imbalance of SGD 2,900 between assets and liabilities.",
    ),
    (
        "E37",
        "CLEAN",
        "Net worth: SGD 24,200.00.\n**Discrepancy check:** ✅ No discrepancies found.",
    ),
    ("E38", "CLEAN", "Net worth: SGD 24,200.00\n- Discrepancy check: ✔ none"),
    ("E39", "CLEAN", "Net worth: SGD 24,200.00. Discrepancy check passed."),
    ("E40", "CLEAN", "Net worth: SGD 24,200.00. The discrepancy check found nothing."),
    (
        "E41",
        "CLEAN",
        "Net worth: SGD 24,200.00. I ran a discrepancy check and everything balances.",
    ),
    (
        "E42",
        "CLEAN",
        "Net worth: SGD 24,200.00. Discrepancy check result: no discrepancies.",
    ),
    (
        "E43",
        "FINDING",
        "Net worth: SGD 24,200.00. The discrepancy check shows assets exceed liabilities plus equity by SGD 2,900.",
    ),
    (
        "E44",
        "FINDING",
        "Net worth: SGD 24,200.00. The discrepancy review flagged SGD 2,900.",
    ),
    ("E45", "CLEAN", "**Net Worth:** SGD 24,200.00\n**Balance Discrepancy:** None"),
    (
        "E46",
        "FINDING",
        "Net worth: SGD 24,200.00. There is not a discrepancy in the bank account, but there is an imbalance of SGD 40.00 in the brokerage account.",
    ),
    (
        "E47",
        "CLEAN",
        "Net worth: SGD 24,200.00\n### Discrepancy Check\n\nNo discrepancies found.",
    ),
    (
        "E48",
        "CLEAN",
        "Net worth: SGD 24,200.00\n### Discrepancy Check\n* No discrepancies found.",
    ),
    (
        "E49",
        "FINDING",
        "Net worth: SGD 24,200.00\n### Discrepancy Check\n- ⚠️ Assets exceed liabilities plus equity by SGD 2,900.",
    ),
    ("C01", "CLEAN", "您的净资产为 SGD 24,200.00。经核对，资产负债平衡，没有差额。"),
    ("C02", "CLEAN", "净资产：SGD 24,200.00\n### 差异检查：未发现任何不一致 ✅"),
    ("C03", "CLEAN", "净资产：SGD 24,200.00。没有发现任何差额。"),
    (
        "C04",
        "FINDING",
        "净资产：SGD 24,200.00。资产与负债加权益之间存在差额 SGD 2,900，账目不平。",
    ),
    (
        "C06",
        "FINDING",
        "净资产：SGD 24,200.00\n### 核对结果：两种方法对不上，相差 SGD 2,900",
    ),
    (
        "C07",
        "FINDING",
        "净资产 SGD 24,200.00。银行账户没有差额，但券商账户不一致，相差 SGD 40.00。",
    ),
    ("C08", "CLEAN", "净资产为 SGD 24,200.00。Discrepancy Check：无。"),
    ("C09", "CLEAN", "净资产 SGD 24,200.00。✅ 无差额，账目一致。"),
    ("C11", "CLEAN", "净资产 SGD 24,200.00\n**Discrepancy Check:** 无差额 ✅"),
    (
        "C12",
        "FINDING",
        "净资产 SGD 24,200.00\n### Discrepancy Check：资产比负债加权益多 SGD 2,900",
    ),
]
CORPUS += [(case_id, "CLEAN", answer) for case_id, answer in HEADING_PROSE_CLEAN]
CORPUS += [(case_id, "FINDING", answer) for case_id, answer, _ in HEADING_PROSE_FINDING]


KNOWN_LIMITS = [
    pytest.param(
        "E11",
        "FINDING",
        "Net worth: SGD 24,200.00\n### Discrepancy Check ✓\nAssets exceed liabilities plus equity by SGD 2,900.",
        marks=pytest.mark.xfail(
            strict=True,
            reason="A check mark after a heading counts as a clean verdict, even when the next line reports a finding.",
        ),
    ),
    pytest.param(
        "E13",
        "FINDING",
        "Your net worth is SGD 24,200.00. No discrepancies were found, but the brokerage account is SGD 40.00 short of its statement balance.",
        marks=pytest.mark.xfail(
            strict=True,
            reason="A clean sentence followed by a contrary clause with no token word is not read.",
        ),
    ),
    pytest.param(
        "E14",
        "FINDING",
        "Net worth: SGD 24,200.00. There is no discrepancy between the balance sheet and the ledger; however, the income statement and the cash flow statement differ by SGD 120.00.",
        marks=pytest.mark.xfail(
            strict=True,
            reason="A clean sentence followed by a contrary clause with no token word is not read.",
        ),
    ),
    pytest.param(
        "E35",
        "FINDING",
        "Net worth: SGD 24,200.00\nDiscrepancy Check: Passed, except the brokerage account differs by SGD 40.00.",
        marks=pytest.mark.xfail(
            strict=True, reason="A clean verdict followed by 'except ...' is not read."
        ),
    ),
    pytest.param(
        "E50",
        "FINDING",
        "Net worth: SGD 24,200.00\n### Discrepancy Check: No — assets exceed liabilities plus equity by SGD 2,900.",
        marks=pytest.mark.xfail(
            strict=True,
            reason="A clean word followed by a dash and a finding is not read.",
        ),
    ),
    pytest.param(
        "C05",
        "CLEAN",
        "您的净资产（总资产与总负债的差额）为 SGD 24,200.00，不存在任何不一致。",
        marks=pytest.mark.xfail(
            strict=True,
            reason="The Chinese token for 'difference' also appears in neutral text.",
        ),
    ),
    pytest.param(
        "C10",
        "FINDING",
        "净资产 SGD 24,200.00。**差异检查：** 资产比负债加权益多 SGD 2,900，存在两处差异。",
        marks=pytest.mark.xfail(
            strict=True, reason="A Chinese finding without a token word is not read."
        ),
    ),
    pytest.param(
        "E51",
        "FINDING",
        "Net worth: SGD 24,200.00\n\n## Balance Discrepancy Check\n\nThere are no discrepancies in the bank accounts. The brokerage account is SGD 40.00 short.\n",
        marks=pytest.mark.xfail(
            strict=True,
            reason="The section rule reads a clean sentence. It does not read a later sentence in the same section that has no token word (#2633).",
        ),
    ),
    pytest.param(
        "E52",
        "CLEAN",
        "Net worth: SGD 24,200.00\n\n**Balance Discrepancy Check**\n\nI verified your records. There are no discrepancies.\n",
        marks=pytest.mark.xfail(
            strict=True,
            reason="The section rule reads markdown headings that start with '#'. It does not read a bold line as a heading (#2633).",
        ),
    ),
    pytest.param(
        "E53",
        "FINDING",
        mutate(
            REAL_FAILING_ANSWER_2633,
            "| Net worth vs. Assets − Liabilities | Consistent ✓ |",
            "| Net worth vs. Assets − Liabilities | Off by SGD 2,900.00 ✗ |",
        ),
        marks=pytest.mark.xfail(
            strict=True,
            reason="A table row under a neutral heading can report a finding with no token word. The section rule does not read figures (#2633).",
        ),
    ),
]


@pytest.mark.parametrize(
    ("case_id", "truth", "answer"), CORPUS, ids=[row[0] for row in CORPUS]
)
def test_AC_testing_benchmarks_10_the_oracle_gives_the_label_of_the_answer(
    case_id: str, truth: str, answer: str
) -> None:
    assert passes(answer) is (truth == "CLEAN"), case_id


@pytest.mark.parametrize(("case_id", "truth", "answer"), KNOWN_LIMITS)
def test_AC_testing_benchmarks_10_a_known_limit_is_still_a_limit(
    case_id: str, truth: str, answer: str
) -> None:
    assert passes(answer) is (truth == "CLEAN"), case_id
