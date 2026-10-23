"""Physical truth oracles for Bench V2 financial scenario benchmarks.

Defines the 4 pillars of benchmark physical verification:
  1. AI Semantic Grounding Oracle: Query AI advisor for net worth and assert
     correct figures with zero hallucinated discrepancy tokens.
  2. Zero Console Error Invariant: Browser checks assert zero console errors
     (catching CSP violations and uncaught exceptions).
  3. DOM Hygiene Scanner: Automated scanner rejects developer jargon in DOM.
  4. Triple Accounting Articulation Invariant: Enforce Assets == Liabilities + Equity
     and Net Worth == Assets - Liabilities == Ending Equity across all cases.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

FORBIDDEN_DOM_JARGON: list[str] = [
    "Report none",
    "advisor_brief",
    "source_result_digest",
    "Loading upload-to-report workflow...",
]

HALLUCINATED_DISCREPANCY_TOKENS: list[str] = [
    "discrepancy",
    "discrepancies",
    "imbalance",
    "does not balance",
    "doesn't balance",
    "doesn\u2019t balance",
    "not equal",
    "unbalanced",
    "mismatch",
    "不一致",
    "不平",
    "差额",
    "对不上",
]

# A negation word starts a word. A letter, a digit or a hyphen before it means that it is
# part of another word: "casino" and "non-zero" are no negation.
_WORD_START = r"(?<![a-z0-9-])"
# A negation word ends a word. "zero-balance" is no negation.
_WORD_END = r"(?![a-z0-9-])"
_ISSUE = (
    r"(?:balance\s+|ledger\s+)?(?:discrepanc(?:y|ies)|imbalance|mismatch|unbalanced)"
)
_ADJECTIVE = (
    r"(?:(?:significant|material|major|apparent|visible|notable|unexplained|"
    r"outstanding|further|other|additional|remaining)\s+)?"
)
_VERB_OBJECT = r"(?:create|cause|result\s+in|lead\s+to|mean|indicate|represent|imply)"
_FIND_VERB = r"(?:find|see|detect|identify|notice|show|reveal)"
# These forms explain a point. They are no verdict on the ledger: "this does not indicate a
# mismatch" (#2633). The section rule below reads a verdict only, never an explanation.
_EXPLANATION_FORMS = (
    rf"not\s+{_VERB_OBJECT}",
    rf"does\s*n[\x27\']t\s+{_VERB_OBJECT}",
    rf"does\s+not\s+{_VERB_OBJECT}",
    rf"cannot\s+{_VERB_OBJECT}",
    r"not\s+an?",
    r"neither",
    r"rather\s+than",
)
_EXPLANATION_PREFIX = "(?:" + "|".join(_EXPLANATION_FORMS) + ")"
_NEGATION_PREFIX = (
    rf"(?:no|zero|without|{_EXPLANATION_PREFIX}|no\s+balance|no\s+ledger"
    rf"|(?:did|do|does)\s*(?:not|n[\x27\']t)\s+{_FIND_VERB}(?:\s+any)?"
    r"|(?:found|find|see|saw|detected)\s+no)"
)

# A review heading is a negation only when the words after it negate (#2484).
_REVIEW_WORD = (
    r"(?:check|verification|audit|review|analysis|analyses|assessment)(?:s|es)?"
)
_HEADING = rf"(?:balance\s+|ledger\s+)?discrepanc(?:y|ies)(?:\s+{_REVIEW_WORD})?"
# These may stand between the heading and the verdict: a qualifier in brackets, the word
# "result", markdown marks (** _ # > |), list marks, a colon and a verb such as "found".
_BETWEEN = (
    r"(?:\s*\([^)]*\))?(?:\s+(?:result|results|status|outcome|summary))?"
    r"[\s:\uff1a\-\u2014\u2013*_#>|\u2022\u00b7]*"
    r"(?:(?:found|shows?|showed|reports?|reported|returned|is|was|came\s+back|and)\s+)*"
)
_CLEAN_VERDICT = (
    r"(?:(?:no|zero|nothing|nil|passed|pass|clear|all\s+clear|balanced|consistent|clean|"
    r"n/a|not\s+applicable|everything\s+(?:balances|matches|agrees|reconciles)|"
    r"all\s+(?:balanced|matched|consistent))"
    rf"{_WORD_END}|none(?![a-z0-9-])(?!\s+of\b)"
    r"|\u2705|\u2713|\u2714|\u2611"
    r"|无|没有|未发现|并未发现|不存在)"
)

NEGATED_DISCREPANCY_PATTERNS: list[str] = [
    rf"{_WORD_START}{_NEGATION_PREFIX}\s*(?:a|an|any)?\s*{_ADJECTIVE}{_ISSUE}",
    rf"{_HEADING}(?={_BETWEEN}{_CLEAN_VERDICT})",
    rf"{_WORD_START}no\s+(?:balance\s+)?discrepanc(?:y|ies)\s+found",
    rf"{_WORD_START}no\s+ledger\s+imbalance",
    rf"{_WORD_START}not\s+unbalanced",
    r"(?:不存在|没有(?:发现|出现)?|无|未(?:发现|见|出现)|并未(?:发现|出现)|并无)"
    r"\s*(?:任何)?\s*(?:不一致|不平|差额|对不上)",
]

# A markdown heading can stand apart from its verdict. The advisor writes the heading, then one
# sentence of prose, then the verdict (#2633). The heading is neutral when all rules hold:
#   1. The heading is a label. It is an ATX line outside a code fence. Its last word is a review
#      noun, or it ends with "?". Its other words are label words. It has no digit, colon, dash,
#      comma, slash or symbol. A heading that ends with a topic word states a finding.
#   2. The section of the heading holds a negated verdict. A section ends at the next ATX heading
#      outside a code fence. An explanation such as "this does not indicate a mismatch" is no verdict.
#   3. No verdict sentence holds a hedge word, and none ends with "?".
#   4. No forbidden token remains in the answer. The final scan checks this rule.
# The verdict marker holds upper-case letters. The scan reads a lower-cased answer. So the text of
# an answer never equals the marker.
_VERDICT_MARKER = "[NEGATED_VERDICT]"
_EXPLANATION_START = re.compile(_EXPLANATION_PREFIX, re.IGNORECASE)
_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_HEADING_MARKS = re.compile(r"^ {0,3}#{1,6}")
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_TOPIC_WORD = re.compile(r"discrepanc(?:y|ies)|imbalances?|mismatch(?:es)?|差额|不一致")
_END_NOUNS = frozenset(
    {
        "check", "checks", "review", "reviews", "verification", "analysis", "analyses",
        "audit", "assessment", "reconciliation", "report", "summary", "result", "results",
        "status",
    }
)  # fmt: skip
_MODIFIER_WORDS = frozenset(
    {"account", "accounts", "accounting", "balance", "ledger", "and", "the", "your"}
)  # fmt: skip
_QUESTION_WORDS = frozenset({"are", "there", "any"})
_LABEL_WORDS = _MODIFIER_WORDS | _END_NOUNS
_END_TERMS_ZH = ("检查", "核对", "校验", "复核", "审核", "对账", "结果", "情况")
_MODIFIER_TERMS_ZH = ("账目", "账务", "余额", "和", "与", "及")
_LABEL_TERMS_ZH = _MODIFIER_TERMS_ZH + _END_TERMS_ZH
_HEADING_END = re.compile(
    r"(?<![a-z])(?:" + "|".join(sorted(_END_NOUNS, key=len, reverse=True)) + r")$"
    r"|(?:" + "|".join(_END_TERMS_ZH) + r")$"
)
# Only these marks may stand in a label heading: space, "&" and markdown bold or italic marks.
# A colon, a dash, a comma, a slash or a symbol splits the heading into a title and a finding.
_HEADING_MARK_ONLY = re.compile(r"[\s&*_]*")
_HEDGE_WORDS = (
    "yet", "save for", "besides", "barring", "mostly", "nevertheless", "beyond", "might",
    "outside", "not true", "false", "untrue", "doubt", "would(?:n't| not) say",
    "(?:does|do)(?:n't| not) mean",
    "but", "however", "except", "exception", "excluding", "although", "though", "unless",
    "whereas", "while", "only", "if", "assuming", "almost", "nearly", "apart from",
    "other than", "aside from", "wrong", "unclear", "unable", "not sure", "cannot confirm",
    "can't confirm",
)  # fmt: skip
_HEDGE_TERMS_ZH = (
    "但", "不过", "(?<!扣)除", "而", "可是", "却", "仅", "只是", "如果", "假如", "假设", "几乎",
    "无法", "虽然", "尽管", "以外", "可能", "并非", "不是", "错误",
)  # fmt: skip
_HEDGE = re.compile(
    r"(?<![a-z])(?:"
    + "|".join(word.replace(" ", r"\s+") for word in _HEDGE_WORDS)
    + r")(?![a-z])"
    r"|"
    + "|".join(_HEDGE_TERMS_ZH)
    # A question is no verdict.
    + r"|\?\s*$"
)
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|[\n。！？；]")
_ABBREVIATION = re.compile(r"\b(?:vs|etc)\.|\b(?:e\.g|i\.e)\.")
_NEGATION_SCAN = re.compile(
    "|".join(f"(?:{pattern})" for pattern in NEGATED_DISCREPANCY_PATTERNS),
    re.IGNORECASE,
)


def _mark_negation(match: re.Match[str]) -> str:
    """Return the marker for a verdict. Return a space for an explanation."""
    is_explanation = _EXPLANATION_START.match(match.group(0)) is not None
    return " " if is_explanation else f" {_VERDICT_MARKER} "


def _is_label_heading(line: str) -> bool:
    """Return True when the heading is a label: topic word, label words and a review noun."""
    text = _HEADING_MARKS.sub("", line).strip().rstrip(" \t#*_:：.。")
    asks = text.endswith("?")
    text = text.rstrip("? ")
    if not _TOPIC_WORD.search(text) or not (asks or _HEADING_END.search(text)):
        return False
    rest = _TOPIC_WORD.sub(" ", text)
    words = _LABEL_WORDS | _QUESTION_WORDS if asks else _LABEL_WORDS
    rest = re.sub(r"[a-z]+", lambda m: " " if m.group(0) in words else m.group(0), rest)
    for term in _LABEL_TERMS_ZH:
        rest = rest.replace(term, " ")
    return _HEADING_MARK_ONLY.fullmatch(rest) is not None


def _has_unhedged_verdict(section_body: str) -> bool:
    """Return True when the section has a negated verdict and no verdict sentence has a hedge word."""
    body = _ABBREVIATION.sub(lambda m: m.group(0)[:-1], section_body)
    verdicts = [s for s in _SENTENCE_END.split(body) if _VERDICT_MARKER in s]
    return bool(verdicts) and not any(_HEDGE.search(s) for s in verdicts)


def _fenced_rows(lines: list[str]) -> list[bool]:
    """Return one flag per line. True means the line is a code fence line or is inside a fence."""
    rows: list[bool] = []
    opener = ""
    for line in lines:
        if opener:
            rows.append(True)
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" "))
            if (
                indent <= 3
                and len(stripped) >= len(opener)
                and set(stripped) == {opener[0]}
            ):
                opener = ""
        else:
            match = _FENCE_OPEN.match(line)
            opener = match.group(1) if match else ""
            rows.append(match is not None)
    return rows


def _neutralize_review_headings(text: str) -> str:
    """Replace the topic word of a label heading when its own section holds an unhedged verdict."""
    lines = text.split("\n")
    fenced = _fenced_rows(lines)
    heading_rows = [
        row
        for row, line in enumerate(lines)
        if not fenced[row] and _ATX_HEADING.match(line)
    ]
    for index, row in enumerate(heading_rows):
        end = heading_rows[index + 1] if index + 1 < len(heading_rows) else len(lines)
        body = "\n".join(lines[i] for i in range(row + 1, end) if not fenced[i])
        if _is_label_heading(lines[row]) and _has_unhedged_verdict(body):
            lines[row] = _TOPIC_WORD.sub(" ", lines[row])
    return "\n".join(lines)


def assert_triple_accounting_articulation(
    bs: dict[str, Any],
    is_stmt: dict[str, Any] | None = None,
    tolerance: Decimal = Decimal("0.05"),
) -> None:
    """Validate Pillar 4: Triple Accounting Articulation Invariant.

    1. Fundamental Equation: Assets == Liabilities + Ending Total Equity (delta == 0.00).
    2. Net Worth Identity: Net Worth == Total Assets - Total Liabilities.
    3. Equity Rollforward: Ending Total Equity == Opening Equity + Net Income + Adjustments.
    4. If Income Statement is provided: bs.net_income == is_stmt.net_income.
    """
    total_assets = Decimal(str(bs["total_assets"]))
    total_liabilities = Decimal(str(bs["total_liabilities"]))
    opening_equity = Decimal(str(bs["total_equity"]))
    bs_net_income = Decimal(str(bs.get("net_income") or "0.00"))
    unrealized_fx = Decimal(str(bs.get("unrealized_fx_gain_loss") or "0.00"))
    cta_adj = Decimal(str(bs.get("cta_adjustment") or "0.00"))
    nw_adj = Decimal(str(bs.get("net_worth_adjustment_gain_loss") or "0.00"))
    equation_delta = Decimal(str(bs.get("equation_delta") or "0.00"))
    is_balanced = bs.get("is_balanced", False)

    # 1. Fundamental balance sheet identity
    ending_total_equity = (
        opening_equity + bs_net_income + unrealized_fx + cta_adj + nw_adj
    )
    net_worth = total_assets - total_liabilities

    assert is_balanced is True, (
        f"Pillar 4 Invariant Failure: Balance Sheet not balanced: is_balanced={is_balanced}, equation_delta={equation_delta}"
    )
    assert abs(equation_delta) <= tolerance, (
        f"Pillar 4 Invariant Failure: Equation delta {equation_delta} exceeds tolerance {tolerance}"
    )

    # 2. Net worth identity
    net_worth_delta = abs(net_worth - ending_total_equity)
    assert net_worth_delta <= tolerance, (
        f"Pillar 4 Invariant Failure: Net Worth ({net_worth}) != Ending Total Equity ({ending_total_equity}), diff={net_worth_delta}"
    )

    # 3. Triple articulation with Income Statement if provided
    if is_stmt is not None:
        is_net_income = Decimal(str(is_stmt["net_income"]))
        ni_diff = abs(bs_net_income - is_net_income)
        assert ni_diff <= tolerance, (
            f"Pillar 4 Invariant Failure: Balance Sheet Net Income ({bs_net_income}) does not match Income Statement Net Income ({is_net_income})"
        )


def assert_ai_advisor_semantic_grounding(
    answer: str,
    expected_figures: list[str],
    forbidden_tokens: list[str] | None = None,
) -> None:
    """Validate Pillar 1: AI Semantic Grounding Oracle.

    Asserts that the AI advisor response contains expected balance numbers
    and zero hallucinated discrepancy or ledger imbalance tokens.
    """
    tokens = (
        forbidden_tokens
        if forbidden_tokens is not None
        else HALLUCINATED_DISCREPANCY_TOKENS
    )
    # One pass over the answer. A look-ahead reads the words of the answer.
    # It does not read the marker of an earlier pattern (#2484).
    # The private markers hold upper-case letters. A lower-cased answer never holds them.
    sanitized_answer = _NEGATION_SCAN.sub(_mark_negation, answer.lower())
    # A heading with prose before its verdict is read per section (#2633).
    sanitized_answer = _neutralize_review_headings(sanitized_answer)

    for token in tokens:
        assert token.lower() not in sanitized_answer, (
            f"Pillar 1 Invariant Failure: AI Advisor hallucinated discrepancy/imbalance token '{token}' in response: {answer}"
        )
    if expected_figures:
        found_any = any(fig in answer for fig in expected_figures)
        assert found_any, (
            f"Pillar 1 Invariant Failure: AI Advisor answer did not contain any expected figures {expected_figures}. Answer: {answer}"
        )


def scan_dom_hygiene(
    text: str,
    forbidden_tokens: list[str] | None = None,
) -> list[str]:
    """Validate Pillar 3: Scan text or DOM content for developer jargon."""
    tokens = forbidden_tokens if forbidden_tokens is not None else FORBIDDEN_DOM_JARGON
    violations: list[str] = []
    text_lower = text.lower()
    for token in tokens:
        if token.lower() in text_lower:
            violations.append(f"Detected forbidden developer jargon: '{token}'")
    return violations


def verify_browser_ui_hygiene(
    runner: ScenarioBenchmarkRunner,
    auth_context: dict[str, Any] | None = None,
    routes: list[str] | None = None,
    viewport: dict[str, int] | None = None,
    timeout_ms: int = 15000,
    allow_skip_if_no_browser: bool = True,
) -> dict[str, Any]:
    """Validate Pillar 2 (Zero Console Error) & Pillar 3 (DOM Hygiene Scanner).

    Uses Playwright to navigate authenticated routes and verifies:
      - Zero console error logs (catching CSP violations and unhandled exceptions)
      - Zero developer jargon in rendered DOM
    """
    if routes is None:
        routes = [
            "/dashboard",
            "/reports?tab=balance-sheet",
            "/reports?tab=income-statement",
            "/reports?tab=cash-flow",
            "/reports",
            "/upload",
            "/reconciliation",
            "/chat",
            "/journal",
            "/settings?tab=accounts",
        ]
    if not routes:
        raise ValueError("verify_browser_ui_hygiene requires at least one route")
    if viewport is None:
        viewport = {"width": 1440, "height": 900}

    target_auth = auth_context or runner.last_auth_context
    if not target_auth:
        raise ValueError("verify_browser_ui_hygiene requires an active auth_context")

    # Validate the auth context before any browser check, so a bad context fails closed
    # whether or not Playwright is installed.
    from tests.e2e.auth_cookie import build_runner_browser_session

    cookie, init_script = build_runner_browser_session(target_auth, runner.base_url)

    console_errors: list[str] = []
    page_errors: list[str] = []
    dom_violations: list[str] = []
    visited_routes: list[str] = []
    route_errors: list[str] = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if allow_skip_if_no_browser:
            print(
                "  ⚠️ Playwright not installed in environment; skipping browser hygiene check"
            )
            return {
                "status": "SKIPPED",
                "reason": "playwright_not_installed",
                "console_errors": [],
                "dom_violations": [],
            }
        raise

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            if allow_skip_if_no_browser:
                print(
                    f"  ⚠️ Playwright chromium launch failed: {exc}; skipping browser hygiene check"
                )
                return {
                    "status": "SKIPPED",
                    "reason": str(exc),
                    "console_errors": [],
                    "dom_violations": [],
                }
            raise

        try:
            context = browser.new_context(viewport=viewport)
            context.add_cookies([cookie])
            context.add_init_script(init_script)

            page = context.new_page()

            def on_console(msg: Any) -> None:
                if msg.type == "error":
                    text = msg.text
                    if "favicon.ico" in text:
                        return
                    console_errors.append(f"[{page.url}] {text}")

            def on_page_error(exc: Any) -> None:
                page_errors.append(f"[{page.url}] {exc}")

            page.on("console", on_console)
            page.on("pageerror", on_page_error)

            for route in routes:
                target_url = f"{runner.base_url}{route}"
                try:
                    response = page.goto(
                        target_url, timeout=timeout_ms, wait_until="domcontentloaded"
                    )
                    status_code = getattr(response, "status", None)
                    if status_code is not None and status_code >= 400:
                        route_errors.append(f"[{route}] HTTP {status_code}")
                        continue
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                    page.wait_for_timeout(500)
                    final_path = urlparse(page.url).path
                    if final_path.startswith("/login") and not route.startswith(
                        "/login"
                    ):
                        route_errors.append(
                            f"[{route}] redirected to {final_path}: the session is not authenticated"
                        )
                        continue
                    body_text = page.inner_text("body")
                    visited_routes.append(route)

                    violations = scan_dom_hygiene(body_text)
                    for v in violations:
                        dom_violations.append(f"[{route}] {v}")
                except Exception as exc:
                    route_errors.append(f"[{route}] navigation failed: {exc}")
        finally:
            browser.close()

    if route_errors:
        raise AssertionError(
            f"Pillar 2/3 Invariant Failure: {len(route_errors)} of {len(routes)} routes were not verified: {route_errors}"
        )
    all_console_issues = console_errors + page_errors
    if all_console_issues:
        raise AssertionError(
            f"Pillar 2 Invariant Failure: Browser console errors detected: {all_console_issues}"
        )
    if dom_violations:
        raise AssertionError(
            f"Pillar 3 Invariant Failure: DOM hygiene violations detected: {dom_violations}"
        )

    return {
        "status": "PASS",
        "visited_routes": visited_routes,
        "route_errors": route_errors,
        "console_errors": all_console_issues,
        "dom_violations": dom_violations,
    }
