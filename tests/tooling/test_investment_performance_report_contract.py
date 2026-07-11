from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract() -> None:
    """AC-portfolio.report-schedule.2: AC17.10.1 AC17.10.2: EPIC-017 owns the investment performance schedule API contract."""
    epic = read("docs/project/EPIC-017.portfolio-management.md")
    # Migrated from docs/ssot/reporting.md into the reporting package readme
    # (migration closeout wave 3, #1664); docs/ssot/reporting.md is now a
    # pointer stub.
    reporting = read("common/reporting/readme.md")

    for text in (epic, reporting):
        assert "GET /api/portfolio/performance/report-schedule" in text
        assert "period_start" in text
        assert "period_end" in text
        assert "as_of_date" in text
        assert "currency" in text

    for field in [
        "xirr",
        "time_weighted_return",
        "money_weighted_return",
        "realized_pnl",
        "unrealized_pnl",
        "dividend_income",
        "dividend_yield",
        "holdings",
        "allocation",
        "data_freshness",
        "stale_holdings",
        "source_links",
        "notes",
    ]:
        assert field in epic
        assert field in reporting


def test_AC5_8_1_personal_report_package_consumes_investment_schedule_contract() -> None:
    """AC-reporting.package-investment.1: AC5.8.1: EPIC-005 owns package consumption of the investment performance schedule."""
    epic = read("docs/project/EPIC-005.reporting-visualization.md")
    user_guide = read("docs/user-guide/reports.md")

    for text in (epic, user_guide):
        assert "investment-performance" in text
        assert "GET /api/portfolio/performance/report-schedule" in text
        assert "investment_performance" in text
        assert "report section" in text
        assert "source_links" in text
        assert "notes" in text
