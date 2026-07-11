from decimal import Decimal
from pathlib import Path

from tools._lib.fixtures.personal_report_package import REPRESENTATIVE_PACKAGE_FIXTURE
from tools._lib.fixtures.portfolio_audit_package import PORTFOLIO_AUDIT_FIXTURE

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _matrix() -> dict:
    """Build the critical-proof matrix payload in-memory.

    The matrix is a derived (not committed) view of the one AC-keyed graph, so
    tests read the freshly-built payload instead of a checked-in YAML file.
    """
    from common.testing.ac_graph import build_ac_graph
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_ac_graph(ROOT))


def test_AC8_13_83_representative_package_fixture_contract_defines_exact_outputs() -> (
    None
):
    """AC-testing.product-gates.8: AC8.13.83: Personal package fixture contract covers representative sources and exact outputs."""
    fixture = REPRESENTATIVE_PACKAGE_FIXTURE

    assert fixture.bank.institution == "Personal Report Package Bank"
    assert fixture.bank.csv_path.as_posix().endswith("vision_hard_gate_statement.csv")
    assert fixture.brokerage.source == "moomoo"
    assert fixture.brokerage.institution == "Moomoo Personal Package"

    component_types = {
        component.component_type for component in fixture.manual_components
    }
    assert component_types == {
        "property_value",
        "mortgage_balance",
        "esop",
        "rsu",
        "stock_options",
    }
    assert {component.source for component in fixture.restricted_components} == {
        "ACME ESOP",
        "ACME RSU",
        "ACME Options",
    }

    expected = fixture.expected_outputs
    assert expected.transaction_count > 0
    assert expected.bank_cash == expected.income - expected.expenses
    assert expected.restricted_fair_value_total == Decimal("156000.00")
    assert expected.manual_liability_total == Decimal("360000.00")
    assert expected.manual_asset_total == Decimal("1256000.00")
    assert expected.net_worth_adjustment_gain_loss == Decimal("896000.00")

    assert {
        "balance_sheet.total_assets",
        "income_statement.total_income",
        "income_statement.total_expenses",
        "cash_flow.net_cash_flow",
        "annualized_income_long_term.annualized_total",
    } <= fixture.required_traceability_line_ids
    assert {
        "basis-of-preparation",
        "reporting-period-and-currency",
        "valuation-basis",
        "investment-market-data",
        "source-confidence-review",
        "restricted-asset-treatment",
    } <= fixture.required_note_ids


def test_AC8_13_84_personal_package_e2e_consumes_representative_fixture_contract() -> (
    None
):
    """AC-testing.product-gates.9: AC8.13.84: Package E2E consumes the shared representative fixture contract."""
    journey = read("tests/e2e/test_personal_financial_report_package.py")

    assert "from tools._lib.fixtures.personal_report_package import" in journey
    assert "REPRESENTATIVE_PACKAGE_FIXTURE" in journey
    assert "PROPERTY_VALUE = Decimal" not in journey
    assert "MORTGAGE_BALANCE = Decimal" not in journey
    assert "ESOP_VALUE = Decimal" not in journey
    assert "_fixture_totals(" not in journey


def test_AC8_13_85_personal_package_macro_proof_is_promoted_after_fixture_contract() -> (
    None
):
    """AC-testing.product-gates.10: AC8.13.85: Package macro proof is covered by the representative fixture ACs."""
    matrix = _matrix()
    outcomes = {outcome["id"]: outcome for outcome in matrix["outcomes"]}
    proofs = {proof["id"]: proof for proof in matrix["proofs"]}

    outcome = outcomes["personal-financial-report-package"]
    assert outcome["status"] == "covered"
    assert outcome["issue"] == "#567"

    proof = proofs["personal-financial-report-package-post-merge"]
    assert proof["issue"] == "#573"
    # AC17.12.1-3 migrated to the portfolio package roadmap as
    # AC-portfolio.fixtures.1-3 (migration closeout, #1663 / #1717).
    assert {
        "AC-testing.product-gates.8",
        "AC-testing.product-gates.9",
        "AC-testing.product-gates.10",
        "AC-portfolio.fixtures.1",
        "AC-portfolio.fixtures.2",
        "AC-portfolio.fixtures.3",
    } <= set(proof["ac_ids"])


def test_AC8_13_87_personal_package_fixture_pins_brokerage_dividend_and_market_price_outputs() -> (
    None
):
    """AC-testing.product-gates.11: AC8.13.87: Audit-grade package fixture pins investment expected outputs."""
    fixture = REPRESENTATIVE_PACKAGE_FIXTURE
    expected = fixture.expected_outputs

    assert (
        expected.brokerage_market_value
        == PORTFOLIO_AUDIT_FIXTURE.report_package_market_value_sgd
    )
    assert expected.brokerage_position_count == len(
        PORTFOLIO_AUDIT_FIXTURE.report_package_positions
    )
    assert (
        expected.dividend_income
        == PORTFOLIO_AUDIT_FIXTURE.expected_activity_totals.dividend_income_sgd
    )
    assert expected.market_price == Decimal("12.50")
    assert expected.market_price_date.isoformat() == "2026-05-31"


def test_AC8_13_88_personal_package_e2e_consumes_audit_grade_expected_outputs() -> None:
    """AC-testing.product-gates.12: AC8.13.88: Package E2E consumes audit-grade expected outputs from the fixture."""
    journey = read("tests/e2e/test_personal_financial_report_package.py")

    assert "expected.brokerage_market_value" in journey
    assert "expected.brokerage_position_count" in journey
    assert "expected.dividend_income" in journey
    assert "expected.market_price" in journey
    assert "expected.market_price_date" in journey
    assert "manual_override_basis" in journey
    assert "_has_price_source_link" in journey
    assert "latest_price_date = date.fromisoformat(" in journey
    assert 'schedule["data_freshness"]["latest_price_date"]' in journey
    assert "latest_price_date >= expected.market_price_date" in journey
    assert "assert _has_dynamic_traceability_identifiers(traceability)" in journey


def test_AC8_14_3_personal_package_has_deterministic_source_trust_mirror() -> None:
    """AC-testing.trust-mirrors.3: AC8.14.3: Package LLM/OCR critical proof has a deterministic source-trust mirror."""
    matrix = _matrix()
    proofs = {proof["id"]: proof for proof in matrix["proofs"]}

    post_merge = proofs["personal-financial-report-package-post-merge"]
    mirror = proofs[post_merge["mirror_proof_id"]]
    expected_sources = {
        "bank_statement",
        "brokerage_statement",
        "property_statement",
        "liability_statement",
        "esop_rsu_plan",
        "csv_export",
        "manual_record",
    }

    assert post_merge["trust_mode"] == "llm_ocr_post_merge"
    assert mirror["trust_mode"] == "deterministic_pr"
    assert mirror["ci_tier"] == "pr_ci"
    assert expected_sources <= set(mirror["source_classes"])
    assert "AC-testing.trust-mirrors.3" in mirror["ac_ids"]
