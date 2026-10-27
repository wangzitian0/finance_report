"""Real-format contract tests for synthetic PDF fixtures (migrated from
EPIC-009 to the `testing` package; see common/testing/contract.py roadmap).

AC-testing.8.1 AC-testing.8.3
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pdfplumber
import pytest
import yaml
from common.testing.fixtures.pdf.generators.dbs_generator import DBSGenerator

REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_FIXTURES = REPO_ROOT / "common" / "testing" / "fixtures" / "pdf"
TEMPLATE_DIR = PDF_FIXTURES / "templates"


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
def test_AC9_8_1_templates_define_sanitized_real_format_contract(template_name: str) -> None:
    """AC9.8.1: Templates carry sanitized source-format contracts without real statement payloads."""
    template = yaml.safe_load((TEMPLATE_DIR / template_name).read_text())
    contract = template["real_format_contract"]

    assert contract["source"] == template["source"]
    assert contract["sensitive_data_policy"] == "sanitized_format_metadata_only"
    assert contract["tolerances"]["page_size_points"] > 0
    assert contract["tolerances"]["column_width_points"] > 0
    assert contract["source_formats"]["date_regex"]
    assert contract["source_formats"]["currency"] == template["text_elements"]["currency"]
    assert "transaction_details" in contract["tables"]

    table_contract = contract["tables"]["transaction_details"]
    template_columns = template["tables"]["transaction_details"]["columns"]
    assert table_contract["columns"] == [column["name"] for column in template_columns]
    assert table_contract["column_widths"] == [column["width"] for column in template_columns]
    assert table_contract["min_rows"] > 0


def test_AC9_8_3_generated_dbs_pdf_matches_template_real_format_contract(
    tmp_path: Path,
) -> None:
    """AC9.8.3: The generated DBS PDF matches page size, headers, markers, key text, and rows."""
    template_path = TEMPLATE_DIR / "dbs_template.yaml"
    template = yaml.safe_load(template_path.read_text())
    contract = template["real_format_contract"]
    table_contract = contract["tables"]["transaction_details"]
    output_path = tmp_path / "dbs.pdf"

    DBSGenerator(template_path).generate(
        output_path, datetime(2025, 1, 1), datetime(2025, 1, 31)
    )

    with pdfplumber.open(output_path) as pdf:
        first_page = pdf.pages[0]
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        tables = [table for page in pdf.pages for table in page.extract_tables()]

    tolerance = contract["tolerances"]["page_size_points"]
    assert abs(first_page.width - template["page"]["width"]) <= tolerance
    assert abs(first_page.height - template["page"]["height"]) <= tolerance
    assert contract["source_formats"]["currency"] in text
    for phrase in contract["key_text"]:
        assert phrase in text

    expected_columns = table_contract["columns"]
    transaction_tables = [
        table
        for table in tables
        if [str(cell or "").strip() for cell in table[0]] == expected_columns
    ]
    assert transaction_tables, f"no table with headers {expected_columns}"
    date_pattern = re.compile(contract["source_formats"]["date_regex"])
    dated_rows = [
        row
        for table in transaction_tables
        for row in table[1:]
        if date_pattern.match(str(row[0] or "").strip())
    ]
    assert len(dated_rows) >= table_contract["min_rows"]
