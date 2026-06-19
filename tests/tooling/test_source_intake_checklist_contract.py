"""Source intake checklist contract tests."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "ssot" / "source-coverage-matrix.yaml"
CHECKLIST = (
    ROOT
    / "apps"
    / "frontend"
    / "src"
    / "components"
    / "source-intake"
    / "SourceIntakeChecklist.tsx"
)


def _source_coverage_required_classes() -> list[str]:
    payload = yaml.safe_load(MATRIX.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    required = payload["required_source_classes"]
    assert isinstance(required, list)
    return [str(item) for item in required]


def _extract_string_array(source: str, const_name: str) -> list[str]:
    match = re.search(
        rf"export const {re.escape(const_name)} = \[(.*?)\] as const;",
        source,
        flags=re.DOTALL,
    )
    assert match, f"{const_name} array not found"
    parsed = ast.literal_eval(f"[{match.group(1)}]")
    assert isinstance(parsed, list)
    return [str(item) for item in parsed]


def _extract_source_intake_item_ids(source: str) -> list[str]:
    items_block = re.search(
        r"const SOURCE_INTAKE_ITEMS: SourceIntakeItem\[] = \[(.*?)\];",
        source,
        flags=re.DOTALL,
    )
    assert items_block, "SOURCE_INTAKE_ITEMS block not found"
    return re.findall(r'\bid: "([^"]+)"', items_block.group(1))


def test_AC19_15_issue_1233_source_intake_matches_ssot_matrix() -> None:
    """AC19.15.1 AC19.15.2: Checklist classes must stay aligned with SSOT."""
    ssot_required = _source_coverage_required_classes()
    checklist_source = CHECKLIST.read_text(encoding="utf-8")
    exported_required = _extract_string_array(
        checklist_source,
        "REQUIRED_REPORT_SOURCE_CLASSES",
    )
    rendered_item_ids = _extract_source_intake_item_ids(checklist_source)

    assert exported_required == ssot_required
    assert rendered_item_ids == ssot_required
    assert ssot_required == [
        "bank_statement",
        "brokerage_statement",
        "settlement_note",
        "esop_rsu_plan",
        "property_statement",
        "liability_statement",
        "csv_export",
        "manual_record",
    ]
