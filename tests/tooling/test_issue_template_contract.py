import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


ROOT = Path(__file__).resolve().parents[2]
ISSUE_TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
REQUIRED_FIELD_LABELS = {
    "Phenomenon Description",
    "How to Reproduce",
    "Minimal Fix Recommendation",
    "Why This Fix Works",
    "Acceptance Criteria",
}
KNOWN_LABELS = {
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "infrastructure",
    "invalid",
    "investment-performance",
    "meta",
    "ongoing",
    "priority: critical",
    "priority: high",
    "priority: low",
    "priority: medium",
    "question",
    "surface: accounting",
    "surface: ai-ocr",
    "surface: backend",
    "surface: ci",
    "surface: docs",
    "surface: extraction",
    "surface: frontend",
    "surface: infra",
    "surface: portfolio",
    "surface: reconciliation",
    "surface: reporting",
    "surface: testing",
    "surface: tooling",
    "wontfix",
}


def _load_template(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict), f"{path} must contain a YAML mapping"
    return loaded


def test_AC14_1_11_issue_templates_require_diagnostic_fix_and_acceptance_sections() -> None:
    """AC14.1.11: Issue templates require diagnostic, fix, rationale, and AC fields."""
    template_paths = sorted(ISSUE_TEMPLATE_DIR.glob("*.yml"))
    assert template_paths, "At least one GitHub issue template is expected"

    for template_path in template_paths:
        template = _load_template(template_path)
        labels = set(template.get("labels", []))
        body = template.get("body", [])
        field_labels = {
            field.get("attributes", {}).get("label")
            for field in body
            if isinstance(field, dict)
        }
        required_field_ids = {
            field.get("id")
            for field in body
            if isinstance(field, dict)
            and field.get("attributes", {}).get("label") in REQUIRED_FIELD_LABELS
        }

        assert labels <= KNOWN_LABELS, (
            f"{template_path} uses unknown labels: {sorted(labels - KNOWN_LABELS)}"
        )
        assert REQUIRED_FIELD_LABELS <= field_labels, (
            f"{template_path} is missing required issue sections: "
            f"{sorted(REQUIRED_FIELD_LABELS - field_labels)}"
        )
        assert len(required_field_ids) == len(REQUIRED_FIELD_LABELS), (
            f"{template_path} required sections must use unique field ids"
        )
