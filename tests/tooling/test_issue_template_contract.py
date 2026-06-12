import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


ROOT = Path(__file__).resolve().parents[2]
ISSUE_TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"

# Files in ISSUE_TEMPLATE/ that are configuration, not issue forms.
NON_TEMPLATE_FILES = {"config.yml"}

KNOWN_LABELS = {
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "idea",
    "incident",
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

# The taxonomy is the point: each issue type carries a different *core* contract.
# A template must declare every listed field id as a `validations.required: true`
# form field (it may add more). Keyed by template filename.
REQUIRED_FIELD_IDS = {
    "issue.yml": {"problem", "repro", "severity"},
    "task.yml": {"goal", "anchor", "ac"},
    "idea.yml": {"idea", "problem"},
    "incident.yml": {"summary", "impact", "root_cause", "followups"},
}


def _load_template(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict), f"{path} must contain a YAML mapping"
    return loaded


def _required_field_ids(body: list) -> set:
    return {
        field.get("id")
        for field in body
        if isinstance(field, dict)
        and field.get("validations", {}).get("required") is True
    }


def test_AC14_1_11_issue_templates_carry_their_type_required_fields() -> None:
    """AC14.1.11: each issue type's template carries the required fields for that
    type (issue: diagnosis; task: goal + anchor + AC; idea: problem; incident:
    impact + root cause + follow-ups). config.yml is the chooser config, not a
    template, and is skipped."""
    template_paths = sorted(
        path
        for path in ISSUE_TEMPLATE_DIR.glob("*.yml")
        if path.name not in NON_TEMPLATE_FILES
    )
    assert template_paths, "At least one GitHub issue template is expected"

    for template_path in template_paths:
        template = _load_template(template_path)
        assert template.get("name") and template.get("description"), (
            f"{template_path} must declare name + description"
        )
        body = template.get("body", [])
        assert isinstance(body, list) and body, f"{template_path} must have a body"

        labels = set(template.get("labels", []))
        assert labels <= KNOWN_LABELS, (
            f"{template_path} uses unknown labels: {sorted(labels - KNOWN_LABELS)}"
        )

        expected = REQUIRED_FIELD_IDS.get(template_path.name)
        assert expected is not None, (
            f"{template_path.name} has no required-field contract; add it to "
            "REQUIRED_FIELD_IDS so the type's expectations are explicit."
        )
        required_ids = _required_field_ids(body)
        assert expected <= required_ids, (
            f"{template_path} is missing required fields for its type: "
            f"{sorted(expected - required_ids)}"
        )
