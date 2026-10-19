"""AC-testing.benchmarks.10: the Bench V2 AI advisor oracle (Pillar 1) reads the words after a heading (#2484).

Pillar 1 fails an advisor answer that reports a discrepancy or a ledger imbalance. It passes an
answer that only negates one. The oracle is a keyword check. It reads the first words after a
heading. It does not read a clause that contradicts them.

The earlier oracle passed every answer with the words "discrepancy check", whatever followed.
This file has three groups of tests:
- Rule tests. Each rule has a test that fails when the rule is removed.
- A labeled corpus of 62 advisor answers in English and Chinese. The label says what the oracle must do.
  One answer is a real advisor answer from a staging run (2026-10-09, run 37968832947).
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
    return error.value.args[0].split("token '")[1].split("'")[0]


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
