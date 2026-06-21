"""Ratio adoption guards for percentage call-sites (EPIC-012 AC12.9, #1200).

The Ratio base package shipped in #1199. These tests keep the follow-up
migration honest: business percentages should use ``Ratio`` for the percent
boundary instead of hand-rolled ``* 100`` / ``quantize(0.01)`` math.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]

BACKEND_RATIO_ADOPTION_FILES = [
    Path("apps/backend/src/services/performance.py"),
    Path("apps/backend/src/services/portfolio.py"),
    Path("apps/backend/src/services/allocation.py"),
    Path("apps/backend/src/services/performance_report.py"),
    Path("apps/backend/src/services/reporting.py"),
    Path("apps/backend/src/services/reconciliation_stats.py"),
]

FRONTEND_RATIO_ADOPTION_FILES = [
    Path("apps/frontend/src/lib/portfolioPerformance.ts"),
    Path("apps/frontend/src/lib/confidence.ts"),
    Path("apps/frontend/src/lib/attention.ts"),
    Path("apps/frontend/src/components/portfolio/PerformanceCard.tsx"),
    Path("apps/frontend/src/components/portfolio/InvestmentPerformanceSchedule.tsx"),
    Path("apps/frontend/src/components/portfolio/HoldingsTable.tsx"),
    Path("apps/frontend/src/app/(main)/portfolio/page.tsx"),
    Path("apps/frontend/src/app/(main)/portfolio/[ticker]/page.tsx"),
]


def _read(path: Path) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_ratio_backend_adoption",
    ac_ids=["AC12.9.3"],
    ci_tier="pr_ci",
    issue="#1200",
)
def test_AC12_9_3_backend_percentage_call_sites_route_through_ratio():
    """AC12.9.3: targeted backend percentage files use Ratio, not manual percent math."""
    for path in BACKEND_RATIO_ADOPTION_FILES:
        src = _read(path)
        assert "from src.ratio import Ratio" in src, f"{path} must import Ratio"
        assert (
            "Ratio.fraction(" in src
            or "Ratio.fraction_or_zero(" in src
            or "Ratio.from_percent(" in src
        ), f"{path} must route percentages through Ratio"

    forbidden = [
        '* Decimal("100")',
        '* Decimal("100"))',
        '* Decimal("100"))',
        "* 100, 2",
        "* 100)).",
        '.quantize(Decimal("0.01")',
    ]
    for path in BACKEND_RATIO_ADOPTION_FILES:
        src = _read(path)
        for pattern in forbidden:
            assert pattern not in src, (
                f"{path} still hand-rolls a percent boundary with {pattern!r}"
            )


@ac_proof(
    proof_id="test_ratio_backend_adoption_keeps_ratio_typed",
    ac_ids=["AC12.9.3"],
    ci_tier="pr_ci",
    issue="#1200",
)
def test_AC12_9_3_backend_adoption_keeps_ratio_typed_until_boundary():
    """AC12.9.3: adoption code should not construct Ratio and unwrap it on the same expression."""
    inline_boundary = re.compile(
        r"Ratio(?:\.fraction|\.from_percent)?\([^()\n]*\)\.to_percent\("
    )
    for path in BACKEND_RATIO_ADOPTION_FILES + [
        Path("apps/backend/src/routers/portfolio.py")
    ]:
        src = _read(path)
        assert not inline_boundary.search(src), (
            f"{path} constructs Ratio and immediately unwraps it to Decimal"
        )

    portfolio = _read(Path("apps/backend/src/services/portfolio.py"))
    # the local _ratio_or_zero helper is retired in favour of the base-package
    # zero-denominator fallback (EPIC-012 AC12.33, #1253)
    assert "Ratio.fraction_or_zero(" in portfolio
    assert "def _ratio_or_zero(" not in portfolio
    assert "def _percent_or_zero(" not in portfolio

    reconciliation = _read(Path("apps/backend/src/services/reconciliation_stats.py"))
    assert "Decimal(matched)" not in reconciliation
    assert "Decimal(total)" not in reconciliation


@ac_proof(
    proof_id="test_ratio_frontend_adoption",
    ac_ids=["AC12.9.3"],
    ci_tier="pr_ci",
    issue="#1200",
)
def test_AC12_9_3_frontend_percentage_call_sites_use_ratio_helpers():
    """AC12.9.3: targeted frontend percentage files use ratio formatting helpers."""
    helper_import = "@/lib/ratio/format"
    for path in FRONTEND_RATIO_ADOPTION_FILES:
        src = _read(path)
        assert helper_import in src, f"{path} must use the shared ratio format helpers"

    forbidden_by_file = {
        Path("apps/frontend/src/lib/portfolioPerformance.ts"): ["multiplyAmount("],
        Path("apps/frontend/src/lib/confidence.ts"): [
            "* 100).toFixed",
            "proportion * 100",
        ],
        Path("apps/frontend/src/lib/attention.ts"): ["Math.round("],
    }
    for path, patterns in forbidden_by_file.items():
        src = _read(path)
        for pattern in patterns:
            assert pattern not in src, (
                f"{path} still hand-rolls percentage formatting with {pattern!r}"
            )
