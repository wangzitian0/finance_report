"""Real-format contract tests for synthetic PDF fixtures (migrated from
EPIC-009 to the `testing` package; see common/testing/contract.py roadmap).

AC-testing.8.1 AC-testing.8.2 AC-testing.8.3
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from common.testing.fixtures.pdf.generators.dbs_generator import DBSGenerator
from common.testing.fixtures.pdf.validators.pdf_validator import PDFValidator

REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_FIXTURES = REPO_ROOT / "common" / "testing" / "fixtures" / "pdf"
TEMPLATE_DIR = PDF_FIXTURES / "templates"


class _FakePdf:
    def __init__(self, pages: list[object]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakePdf:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _load_template(name: str = "dbs_template.yaml") -> dict:
    return yaml.safe_load((TEMPLATE_DIR / name).read_text())


@pytest.mark.parametrize(
    "template_name",
    [
        "dbs_template.yaml",
        "cmb_template.yaml",
        "mari_template.yaml",
        "moomoo_template.yaml",
        "futu_template.yaml",
        "pingan_template.yaml",
    ],
)
def test_AC9_8_1_templates_define_sanitized_real_format_contract(
    template_name: str,
) -> None:
    """AC9.8.1: Templates carry sanitized source-format contracts without real statement payloads."""
    template = yaml.safe_load((TEMPLATE_DIR / template_name).read_text())
    contract = template["real_format_contract"]

    assert contract["source"] == template["source"]
    assert contract["sensitive_data_policy"] == "sanitized_format_metadata_only"
    assert contract["tolerances"]["page_size_points"] > 0
    assert contract["tolerances"]["column_width_points"] > 0
    assert contract["source_formats"]["date_regex"]
    assert (
        contract["source_formats"]["currency"] == template["text_elements"]["currency"]
    )
    assert "transaction_details" in contract["tables"]

    table_contract = contract["tables"]["transaction_details"]
    template_columns = template["tables"]["transaction_details"]["columns"]
    assert table_contract["columns"] == [column["name"] for column in template_columns]
    assert table_contract["column_widths"] == [
        column["width"] for column in template_columns
    ]
    assert table_contract["min_rows"] > 0


def test_AC9_8_2_validator_rejects_missing_or_drifting_real_format_contract() -> None:
    """AC9.8.2: Validator fails missing contracts and mismatched template geometry."""
    validator = PDFValidator()
    template = yaml.safe_load((TEMPLATE_DIR / "dbs_template.yaml").read_text())

    valid = validator.validate_real_format_contract(template)
    assert valid["success"] is True
    assert valid["errors"] == []

    missing_contract = dict(template)
    missing_contract.pop("real_format_contract")
    missing = validator.validate_real_format_contract(missing_contract)
    assert missing["success"] is False
    assert "real_format_contract is required" in missing["errors"]

    drifting = yaml.safe_load(yaml.safe_dump(template))
    drifting["real_format_contract"]["tables"]["transaction_details"]["columns"][0] = (
        "Posting Date"
    )
    drift_result = validator.validate_real_format_contract(drifting)
    assert drift_result["success"] is False
    assert any("column names drift" in error for error in drift_result["errors"])


def test_AC9_8_2_validator_rejects_malformed_real_format_contract_fields() -> None:
    """AC9.8.2: Validator rejects malformed real-format metadata fields."""
    template = _load_template()
    contract = template["real_format_contract"]
    contract["source"] = "wrong-source"
    contract["sensitive_data_policy"] = "raw_statement_payload"
    contract["tolerances"]["page_size_points"] = 0
    contract["tolerances"]["column_width_points"] = -1
    contract["source_formats"]["date_regex"] = "["
    contract["source_formats"]["currency"] = "USD"
    contract["tables"]["transaction_details"]["column_widths"][0] = 1
    contract["tables"]["transaction_details"]["min_rows"] = 0

    result = PDFValidator().validate_real_format_contract(template)

    assert result["success"] is False
    assert any("source mismatch" in error for error in result["errors"])
    assert any("sanitized_format_metadata_only" in error for error in result["errors"])
    assert any("tolerances.page_size_points" in error for error in result["errors"])
    assert any("tolerances.column_width_points" in error for error in result["errors"])
    assert any("date_regex is invalid" in error for error in result["errors"])
    assert any("currency drift" in error for error in result["errors"])
    assert any("column widths drift" in error for error in result["errors"])
    assert any("min_rows must be positive" in error for error in result["errors"])


def test_AC9_8_2_validator_rejects_missing_required_contract_sections() -> None:
    """AC9.8.2: Validator rejects missing date and table sections."""
    missing_date = _load_template()
    missing_date["real_format_contract"]["source_formats"]["date_regex"] = ""

    date_result = PDFValidator().validate_real_format_contract(missing_date)

    assert date_result["success"] is False
    assert any("date_regex is required" in error for error in date_result["errors"])

    missing_table = _load_template()
    missing_table["real_format_contract"]["tables"].pop("transaction_details")

    table_result = PDFValidator().validate_real_format_contract(missing_table)

    assert table_result["success"] is False
    assert table_result["errors"] == [
        "real_format_contract tables.transaction_details is required"
    ]


def test_AC9_8_3_generated_pdf_matches_template_real_format_contract(
    tmp_path: Path,
) -> None:
    """AC9.8.3: Generated PDFs satisfy page, table, date, currency, and key-text contract checks."""
    output_path = tmp_path / "dbs.pdf"
    template = yaml.safe_load((TEMPLATE_DIR / "dbs_template.yaml").read_text())

    DBSGenerator(TEMPLATE_DIR / "dbs_template.yaml").generate(
        output_path,
        datetime(2025, 1, 1),
        datetime(2025, 1, 31),
    )

    result = PDFValidator().validate_generated_pdf_against_real_format_contract(
        output_path, template
    )

    assert result["success"] is True
    assert result["errors"] == []


def test_AC9_8_3_generated_pdf_validator_surfaces_real_format_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.8.3: Generated-PDF validation reports page, text, header, and row drift."""
    template = _load_template()
    page = SimpleNamespace(
        width=900.0,
        height=1000.0,
        extract_text=lambda: "Account Summary",
        extract_tables=lambda: [
            [],
            [["Only Date"], ["01 Jan 2025"]],
            [["Posting Date", "Narrative", "Debit"], ["not-a-date", "Coffee", "1.00"]],
        ],
    )
    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        lambda _path: _FakePdf([page]),
    )

    result = PDFValidator().validate_generated_pdf_against_real_format_contract(
        Path("generated.pdf"),
        template,
    )

    assert result["success"] is False
    assert any("page width" in error for error in result["errors"])
    assert any("page height" in error for error in result["errors"])
    assert any("currency marker" in error for error in result["errors"])
    assert any("missing key text phrase" in error for error in result["errors"])
    assert any("rows below real-format minimum" in error for error in result["errors"])


def test_AC9_8_3_generated_pdf_validator_rejects_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.8.3: Generated-PDF validation fails invalid templates, empty PDFs, and parser errors."""
    validator = PDFValidator()
    invalid_template = _load_template()
    invalid_template.pop("real_format_contract")

    invalid_result = validator.validate_generated_pdf_against_real_format_contract(
        Path("generated.pdf"),
        invalid_template,
    )

    assert invalid_result["success"] is False
    assert invalid_result["errors"] == ["real_format_contract is required"]

    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        lambda _path: _FakePdf([]),
    )

    empty_result = validator.validate_generated_pdf_against_real_format_contract(
        Path("empty.pdf"),
        _load_template(),
    )

    assert empty_result["success"] is False
    assert empty_result["errors"] == ["PDF has no pages"]

    def raise_open(_path: Path) -> object:
        raise RuntimeError("parse failed")

    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        raise_open,
    )

    error_result = validator.validate_generated_pdf_against_real_format_contract(
        Path("bad.pdf"),
        _load_template(),
    )

    assert error_result["success"] is False
    assert error_result["errors"] == ["Validation error: parse failed"]


def test_AC9_8_3_real_format_header_matching_and_table_errors() -> None:
    """AC9.8.3: Validator helpers reject mismatched headers and empty tables."""
    validator = PDFValidator()

    assert (
        validator._header_matches(["Date"], ["Transaction Date", "Description"])
        is False
    )
    assert (
        validator._header_matches(["Posting", "Narrative"], ["Date", "Description"])
        is False
    )

    empty_table = validator._validate_table([], {"columns": [{"name": "Date"}]})
    assert empty_table["success"] is False
    assert empty_table["errors"] == ["Table is empty or has no data rows"]
