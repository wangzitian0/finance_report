"""Physical truth oracles for Bench V2 financial scenario benchmarks."""

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

DEFAULT_BENCHMARK_UI_ROUTES: list[str] = [
    "/",
    "/chat",
    "/audit",
    "/more",
    "/upload",
    "/portfolio",
    "/reports",
    "/reports?tab=balance-sheet",
    "/reports?tab=income-statement",
    "/reports?tab=cash-flow",
    "/reports?tab=package",
    "/reconciliation",
    "/journal",
    "/settings",
]

DEFAULT_BENCHMARK_UI_VIEWPORTS: list[dict[str, int]] = [
    {"width": 1440, "height": 900},
    {"width": 390, "height": 844},
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

_WORD_START = r"(?<![a-z0-9-])"
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
_NEGATION_PREFIX = (
    r"(?:no|zero|without"
    rf"|not\s+{_VERB_OBJECT}|does\s*n[\x27\']t\s+{_VERB_OBJECT}|does\s+not\s+{_VERB_OBJECT}"
    rf"|cannot\s+{_VERB_OBJECT}|not\s+a|not\s+an|neither|no\s+balance|no\s+ledger"
    rf"|rather\s+than|(?:did|do|does)\s*(?:not|n[\x27\']t)\s+{_FIND_VERB}(?:\s+any)?"
    r"|(?:found|find|see|saw|detected)\s+no)"
)
_REVIEW_WORD = (
    r"(?:check|verification|audit|review|analysis|analyses|assessment)(?:s|es)?"
)
_HEADING = rf"(?:balance\s+|ledger\s+)?discrepanc(?:y|ies)(?:\s+{_REVIEW_WORD})?"
_BETWEEN = (
    r"(?:\s*\([^)]*\))?(?:\s+(?:result|results|status|outcome|summary))?"
    r"[\s:\uff1a\-\u2014\u2013*_#>|\u2022\u00b7]*"
    r"(?:(?:i|we)\s+(?:verified|checked|confirmed)\s+[^.!?\n:;]*?(?:,\s*and\s+|\s*[—–-]\s*)\**[\s*_#>|\u2022\u00b7]*)?"
    r"(?:(?:found|shows?|showed|reports?|reported|returned|is|was|came\s+back|and)\s+)*"
)
_CLEAN_VERDICT = (
    r"(?:(?:no|zero|nothing|nil|passed|pass|clear|all\s+clear|balanced|consistent|clean|"
    r"n/a|not\s+applicable|everything\s+(?:balances|matches|agrees|reconciles)|"
    r"both\s+(?:reconcile|balance|match|agree)(?:\s+perfectly)?|"
    r"all\s+(?:balanced|matched|consistent))"
    rf"{_WORD_END}|none(?![a-z0-9-])(?!\s+of\b)"
    r"|\u2705|\u2713|\u2714|\u2611"
    r"|无|没有|未发现|并未发现|不存在)"
)

NEGATED_DISCREPANCY_PATTERNS: list[str] = [
    rf"{_WORD_START}{_NEGATION_PREFIX}\s*(?:a|an|any)?\s*{_ADJECTIVE}{_ISSUE}",
    rf"{_HEADING}(?={_BETWEEN}{_CLEAN_VERDICT})",
    rf"{_WORD_START}no\s+(?:balance\s+)?discrepanc(?:y|ies)\s+(?:(?:was|were)\s+)?found",
    rf"{_WORD_START}no\s+ledger\s+imbalance",
    rf"{_WORD_START}not\s+unbalanced",
    r"(?:不存在|没有(?:发现|出现)?|无|未(?:发现|见|出现)|并未(?:发现|出现)|并无)"
    r"\s*(?:任何)?\s*(?:不一致|不平|差额|对不上)",
]


def _dec(d: dict[str, Any], key: str, default: str = "0.00") -> Decimal:
    return Decimal(str(d.get(key) if key in d and d.get(key) is not None else default))


def assert_triple_accounting_articulation(
    bs: dict[str, Any],
    is_stmt: dict[str, Any] | None = None,
    tolerance: Decimal = Decimal("0.05"),
) -> None:
    net_worth = Decimal(str(bs["total_assets"])) - Decimal(str(bs["total_liabilities"]))
    bs_ni = _dec(bs, "net_income")
    ending_equity = (
        Decimal(str(bs["total_equity"]))
        + bs_ni
        + _dec(bs, "unrealized_fx_gain_loss")
        + _dec(bs, "cta_adjustment")
        + _dec(bs, "net_worth_adjustment_gain_loss")
    )
    equation_delta = _dec(bs, "equation_delta")
    is_balanced = bs.get("is_balanced", False)

    assert is_balanced is True, (
        f"Pillar 4 Invariant Failure: Balance Sheet not balanced: is_balanced={is_balanced}, equation_delta={equation_delta}"
    )
    assert abs(equation_delta) <= tolerance, (
        f"Pillar 4 Invariant Failure: Equation delta {equation_delta} exceeds tolerance {tolerance}"
    )
    nw_delta = abs(net_worth - ending_equity)
    assert nw_delta <= tolerance, (
        f"Pillar 4 Invariant Failure: Net Worth ({net_worth}) != Ending Total Equity ({ending_equity}), diff={nw_delta}"
    )
    if is_stmt is not None:
        is_ni = Decimal(str(is_stmt["net_income"]))
        assert abs(bs_ni - is_ni) <= tolerance, (
            f"Pillar 4 Invariant Failure: Balance Sheet Net Income ({bs_ni}) does not match Income Statement Net Income ({is_ni})"
        )


def assert_ai_advisor_semantic_grounding(
    answer: str,
    expected_figures: list[str],
    forbidden_tokens: list[str] | None = None,
) -> None:
    tokens = (
        forbidden_tokens
        if forbidden_tokens is not None
        else HALLUCINATED_DISCREPANCY_TOKENS
    )
    sanitized = re.sub(
        "|".join(f"(?:{p})" for p in NEGATED_DISCREPANCY_PATTERNS),
        " [negated_consistency_assertion] ",
        answer.lower(),
        flags=re.IGNORECASE,
    )
    for token in tokens:
        assert token.lower() not in sanitized, (
            f"Pillar 1 Invariant Failure: AI Advisor hallucinated discrepancy/imbalance token '{token}' in response: {answer}"
        )
    if expected_figures:
        assert any(fig in answer for fig in expected_figures), (
            f"Pillar 1 Invariant Failure: AI Advisor answer did not contain any expected figures {expected_figures}. Answer: {answer}"
        )


def scan_dom_hygiene(text: str, forbidden_tokens: list[str] | None = None) -> list[str]:
    tokens = forbidden_tokens if forbidden_tokens is not None else FORBIDDEN_DOM_JARGON
    low = text.lower()
    return [
        f"Detected forbidden developer jargon: '{t}'"
        for t in tokens
        if t.lower() in low
    ]


def _skipped(reason: str) -> dict[str, Any]:
    return {
        "status": "SKIPPED",
        "reason": reason,
        "console_errors": [],
        "dom_violations": [],
    }


def verify_browser_ui_hygiene(
    runner: ScenarioBenchmarkRunner,
    auth_context: dict[str, Any] | None = None,
    routes: list[str] | None = None,
    viewport: dict[str, int] | None = None,
    timeout_ms: int = 15000,
    allow_skip_if_no_browser: bool = True,
    viewports: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    routes = list(DEFAULT_BENCHMARK_UI_ROUTES) if routes is None else routes
    if not routes:
        raise ValueError("verify_browser_ui_hygiene requires at least one route")
    active_viewports = (
        list(viewports)
        if viewports is not None
        else (
            [viewport] if viewport is not None else list(DEFAULT_BENCHMARK_UI_VIEWPORTS)
        )
    )
    target_auth = auth_context or runner.last_auth_context
    if not target_auth:
        raise ValueError("verify_browser_ui_hygiene requires an active auth_context")

    from tests.e2e.auth_cookie import build_runner_browser_session

    cookie, init_script = build_runner_browser_session(target_auth, runner.base_url)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if allow_skip_if_no_browser:
            return _skipped("playwright_not_installed")
        raise

    console_errors: list[str] = []
    page_errors: list[str] = []
    dom_violations: list[str] = []
    visited_routes: list[str] = []
    route_errors: list[str] = []
    failed_routes: set[str] = set()

    def record_route_error(route: str, msg: str) -> None:
        if route not in failed_routes:
            failed_routes.add(route)
            route_errors.append(f"[{route}] {msg}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            if allow_skip_if_no_browser:
                return _skipped(str(exc))
            raise
        try:
            for vp in active_viewports:
                vp_label = f"{vp['width']}x{vp['height']}"
                context = browser.new_context(viewport=vp)
                context.add_cookies([cookie])
                context.add_init_script(init_script)
                page = context.new_page()
                page.on(
                    "console",
                    lambda msg, p=page: console_errors.append(f"[{p.url}] {msg.text}")
                    if msg.type == "error" and "favicon.ico" not in msg.text
                    else None,
                )
                page.on(
                    "pageerror",
                    lambda exc, p=page: page_errors.append(f"[{p.url}] {exc}"),
                )

                for route in routes:
                    try:
                        resp = page.goto(
                            f"{runner.base_url}{route}",
                            timeout=timeout_ms,
                            wait_until="domcontentloaded",
                        )
                        sc = getattr(resp, "status", None)
                        if sc is not None and sc >= 400:
                            record_route_error(route, f"HTTP {sc}")
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
                            record_route_error(
                                route,
                                f"redirected to {final_path}: the session is not authenticated",
                            )
                            continue
                        eval_fn = getattr(page, "evaluate", None)
                        if callable(eval_fn):
                            dims = eval_fn(
                                "() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })"
                            )
                            if isinstance(dims, dict):
                                sw = int(dims.get("scrollWidth", vp["width"]))
                                iw = int(dims.get("innerWidth", vp["width"]))
                                if sw > iw:
                                    record_route_error(
                                        route,
                                        f"horizontal overflow at {vp_label}: scrollWidth={sw} > innerWidth={iw}",
                                    )
                                    continue
                        body_text = page.inner_text("body")
                        if route not in visited_routes:
                            visited_routes.append(route)
                        for v in scan_dom_hygiene(body_text):
                            entry = f"[{route}] {v}"
                            if entry not in dom_violations:
                                dom_violations.append(entry)
                    except Exception as exc:
                        record_route_error(route, f"navigation failed: {exc}")
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
        "viewports_verified": [
            f"{vp['width']}x{vp['height']}" for vp in active_viewports
        ],
        "route_errors": route_errors,
        "console_errors": all_console_issues,
        "dom_violations": dom_violations,
    }
