"""Real-format contract tests for synthetic PDF fixtures (migrated from
EPIC-009 to the `testing` package; see common/testing/contract.py roadmap).

AC-testing.8.1
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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
