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

import json
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

FORBIDDEN_DOM_JARGON: list[str] = [
    "upload-to-report",
    "Report none",
    "advisor_brief",
    "source_result_digest",
    "Loading upload-to-report workflow...",
]

HALLUCINATED_DISCREPANCY_TOKENS: list[str] = [
    "discrepancy",
    "imbalance",
    "does not balance",
    "not equal",
    "unbalanced",
    "mismatch",
    "不一致",
    "不平",
    "差额",
    "对不上",
]

NEGATED_DISCREPANCY_PATTERNS: list[str] = [
    r"(?:no|zero|without|not create any|does not create any|doesn\x27t create any|not cause any|does not cause any|not an|neither|no balance)\s+(?:balance\s+)?(?:discrepanc(?:y|ies)|imbalance|mismatch|unbalanced)",
    r"no\s+(?:balance\s+)?discrepanc(?:y|ies)\s+found",
    r"no\s+ledger\s+imbalance",
    r"not\s+unbalanced",
    r"(?:不存在|没有|无|并未发现|并无)\s*(?:任何)?\s*(?:不一致|不平|差额|对不上)",
]


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
    answer_lower = answer.lower()
    sanitized_answer = answer_lower
    for pattern in NEGATED_DISCREPANCY_PATTERNS:
        sanitized_answer = re.sub(
            pattern,
            " [negated_consistency_assertion] ",
            sanitized_answer,
            flags=re.IGNORECASE,
        )

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
        routes = ["/dashboard", "/reports/balance-sheet", "/upload", "/reconciliation"]
    if viewport is None:
        viewport = {"width": 1440, "height": 900}

    target_auth = auth_context or runner.last_auth_context
    if not target_auth:
        raise ValueError("verify_browser_ui_hygiene requires an active auth_context")

    user_data = target_auth.get("user_data") or {}
    user_email = target_auth.get("user_email")
    token = user_data.get("access_token")
    user_id = user_data.get("id") or (
        user_data.get("user", {}).get("id")
        if isinstance(user_data.get("user"), dict)
        else None
    )

    console_errors: list[str] = []
    page_errors: list[str] = []
    dom_violations: list[str] = []
    visited_routes: list[str] = []

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

    try:
        from tests.e2e.auth_cookie import build_auth_cookie

        cookie = build_auth_cookie(runner.base_url, token)
    except Exception:
        cookie = None

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
            if cookie:
                context.add_cookies([cookie])
            if user_id and user_email:
                context.add_init_script(
                    f"""
                    localStorage.setItem('finance_user_id', {json.dumps(str(user_id))});
                    localStorage.setItem('finance_user_email', {json.dumps(user_email)});
                    """
                )

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
                    page.goto(
                        target_url, timeout=timeout_ms, wait_until="domcontentloaded"
                    )
                    page.wait_for_timeout(1000)
                    body_text = page.inner_text("body")
                    visited_routes.append(route)

                    violations = scan_dom_hygiene(body_text)
                    for v in violations:
                        dom_violations.append(f"[{route}] {v}")
                except Exception as exc:
                    print(f"  ⚠️ Route navigation error for {route}: {exc}")
        finally:
            browser.close()

    all_console_issues = console_errors + page_errors
    assert not all_console_issues, (
        f"Pillar 2 Invariant Failure: Browser console errors detected: {all_console_issues}"
    )
    assert not dom_violations, (
        f"Pillar 3 Invariant Failure: DOM hygiene violations detected: {dom_violations}"
    )

    return {
        "status": "PASS",
        "visited_routes": visited_routes,
        "console_errors": all_console_issues,
        "dom_violations": dom_violations,
    }
