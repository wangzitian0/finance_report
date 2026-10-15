"""AC-llm.12.2, AC-testing.product-gates.7, AC-testing.product-gates.14: journeys that approve a statement own their fixture facts (#2332, #2473).

Each check below pins one defect of the AI/OCR audit replay on staging v0.1.74.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from common.testing.provider_review import _description_key

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E = REPO_ROOT / "tests" / "e2e"
FIXTURES = REPO_ROOT / "common" / "testing" / "fixtures" / "pdf" / "generated"
# The disposition table of CMB keeps one generic fallback row.
GENERIC_DESCRIPTIONS = {_description_key("交易")}


def _tree(name: str) -> ast.Module:
    return ast.parse((E2E / name).read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == name
    )


def _call_names(node: ast.AST) -> list[str]:
    return [
        n.func.id
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]


def _disposition_keys(tree: ast.Module, table: str) -> set[str]:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == table
        ):
            return {
                key.value
                for key in node.value.keys  # type: ignore[attr-defined]
                if isinstance(key, ast.Constant)
            }
    raise AssertionError(f"{table} not found")


@pytest.mark.parametrize(
    ("table", "fixture"),
    [
        ("MARIBANK_DISPOSITIONS", "maribank"),
        ("CMB_DISPOSITIONS", "cmb"),
        ("PINGAN_DISPOSITIONS", "pingan"),
    ],
)
def test_a_committed_fixture_disposition_table_covers_exactly_the_fixture_rows(
    table: str, fixture: str
) -> None:
    expected = json.loads(
        (FIXTURES / f"{fixture}_statement_fixture_expected.json").read_text(
            encoding="utf-8"
        )
    )
    fixture_rows = {
        _description_key(event["description"]) for event in expected["events"]
    }
    keys = {
        _description_key(key)
        for key in _disposition_keys(
            _tree("test_institution_statement_journeys.py"), table
        )
    }

    assert keys - GENERIC_DESCRIPTIONS == fixture_rows


@pytest.mark.parametrize(
    ("journey", "pdf"),
    [
        ("test_maribank_statement_journey", "maribank_statement_fixture.pdf"),
        ("test_cmb_statement_journey", "cmb_statement_fixture.pdf"),
        ("test_pingan_statement_journey", "pingan_statement_fixture.pdf"),
    ],
)
def test_a_committed_fixture_journey_uploads_the_committed_pdf_with_an_envelope(
    journey: str, pdf: str
) -> None:
    node = _function(_tree("test_institution_statement_journeys.py"), journey)
    names = _call_names(node)
    uploaded = [
        arg.value
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "committed_fixture_pdf"
        for arg in call.args
        if isinstance(arg, ast.Constant)
    ]

    assert uploaded == [pdf]
    assert "generated_pdf_path" not in names, (
        "a PDF built at run time picks rows that the disposition table cannot cover"
    )
    assert "_fixture_envelope" in names


def test_the_four_asset_journey_supplies_an_envelope_to_the_approval_harness() -> None:
    journey = next(
        n
        for n in ast.walk(_tree("test_four_asset_net_worth_golden_path.py"))
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "test_four_asset_as_of_net_worth_golden_path"
    )
    approvals = [
        n
        for n in ast.walk(journey)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "approve_statement_with_fixture_review"
    ]

    assert approvals
    assert all(any(kw.arg == "envelope" for kw in call.keywords) for call in approvals)


def test_the_gxs_browser_journey_pins_the_deployment_by_commit() -> None:
    journey = _function(
        _tree("test_gxs_browser_journey.py"), "test_gxs_browser_upload_to_saved_package"
    )
    names = _call_names(journey)

    assert "assert_pinned_deployment" in names
    assert "resolve_expected_commit" in names


def test_the_four_asset_journey_finds_the_bank_line_by_account_not_by_name() -> None:
    """The review harness names the account it creates, so a name lookup finds nothing."""
    journey = next(
        n
        for n in ast.walk(_tree("test_four_asset_net_worth_golden_path.py"))
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "test_four_asset_as_of_net_worth_golden_path"
    )
    by_name_on_bank = [
        n
        for n in ast.walk(journey)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_line_total_by_name"
        and any(isinstance(a, ast.Name) and a.id == "BANK_INSTITUTION" for a in n.args)
    ]

    assert "_line_total_by_account" in _call_names(journey)
    assert by_name_on_bank == []


def test_the_four_asset_journey_reports_on_a_past_month_end_with_a_matching_pdf() -> (
    None
):
    """A holding exists only on or after its snapshot, and the PDF is dated to its month end.

    Reporting on today's date failed on every day except the last day of a month.
    """
    journey = next(
        n
        for n in ast.walk(_tree("test_four_asset_net_worth_golden_path.py"))
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "test_four_asset_as_of_net_worth_golden_path"
    )
    report_date = next(
        n.value
        for n in ast.walk(journey)
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == "report_date"
    )
    # `date.today()` alone is today. A past month end is derived from it by arithmetic.
    assert isinstance(report_date, ast.BinOp), "report_date must be a past month end"
    brokerage_uploads = [
        n
        for n in ast.walk(journey)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_upload_brokerage_pdf"
    ]

    assert brokerage_uploads
    assert all(
        any(
            kw.arg == "period_end"
            and isinstance(kw.value, ast.Name)
            and kw.value.id == "report_date"
            for kw in call.keywords
        )
        for call in brokerage_uploads
    )


#: Intents that fix the direction of the money. The other intents, such as a transfer, accept both.
INTENT_DIRECTION = {
    "income": "IN",
    "expense_refund": "IN",
    "investment_sale": "IN",
    "expense": "OUT",
    "card_repayment": "OUT",
    "investment_purchase": "OUT",
}


def _disposition_intents(tree: ast.Module, table: str) -> dict[str, str]:
    """Description -> intent of one disposition table. The intent is the first call argument."""
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == table
        ):
            return {
                _description_key(key.value): value.args[0].value  # type: ignore[attr-defined]
                for key, value in zip(node.value.keys, node.value.values)  # type: ignore[attr-defined]
                if isinstance(key, ast.Constant)
            }
    raise AssertionError(f"{table} not found")


@pytest.mark.parametrize(
    ("table", "fixture"),
    [
        ("MARIBANK_DISPOSITIONS", "maribank"),
        ("CMB_DISPOSITIONS", "cmb"),
        ("PINGAN_DISPOSITIONS", "pingan"),
    ],
)
def test_AC_testing_product_gates_14_each_fixture_row_has_a_disposition_that_fits_its_direction(
    table: str, fixture: str
) -> None:
    """A disposition whose intent contradicts the row direction fails the approval with HTTP 400 (#2473)."""
    expected = json.loads(
        (FIXTURES / f"{fixture}_statement_fixture_expected.json").read_text(
            encoding="utf-8"
        )
    )
    intents = _disposition_intents(
        _tree("test_institution_statement_journeys.py"), table
    )

    conflicts = [
        f"{event['description']!r} is {event['direction']} but its intent is {intents[_description_key(event['description'])]!r}"
        for event in expected["events"]
        if INTENT_DIRECTION.get(intents[_description_key(event["description"])])
        not in (None, event["direction"])
    ]

    assert expected["events"]
    assert conflicts == []
