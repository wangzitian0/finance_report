from pathlib import Path

from common.meta.extension.generate_ac_registry import materialized_entries

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


EPIC_021 = "docs/project/EPIC-021.application-ai-advisor.md"
# Migrated from docs/ssot/ai.md into the advisor package readme (migration
# closeout wave 3, #1664); docs/ssot/ai.md is now a pointer stub.
AI_SSOT = "common/advisor/readme.md"


def test_AC21_1_1_ai_advisor_is_application_layer_contract() -> None:
    """AC21.1.1: AI Advisor product value is owned as a read-only application layer."""
    epic = read(EPIC_021)
    ssot = read(AI_SSOT)
    manifest = read("docs/ssot/MANIFEST.yaml")
    registry_entries = {entry["id"]: entry for entry in materialized_entries("feature")}

    assert "Application-Layer AI Advisor" in epic
    assert "read-only application layer" in epic
    assert "deterministic application facts" in ssot
    assert "Application-Layer Advisor Contract" in ssot
    assert "docs/project/EPIC-021.application-ai-advisor.md" in manifest
    assert registry_entries["AC21.1.1"]["epic_name"] == "application-ai-advisor"


def test_AC21_1_2_scale_and_confidence_work_stays_in_existing_epics() -> None:
    """AC21.1.2: Scale coverage and confidence work is routed to existing owned EPICs."""
    epic = read(EPIC_021)
    ssot = read(AI_SSOT)
    root_readme = read("README.md")
    project_readme = read("docs/project/README.md")

    for existing_owner in (
        "EPIC-003 / EPIC-013",
        "EPIC-005 / EPIC-008",
        "EPIC-011 / EPIC-005",
        "#705",
        "#706",
    ):
        assert existing_owner in epic

    assert "report package snapshots and export scale stay in EPIC-005 / EPIC-008" in epic
    assert "manual evidence intake stays in EPIC-011 / EPIC-005" in epic
    assert "source coverage matrix" in ssot
    assert "docs/project/EPIC-021.application-ai-advisor.md" in root_readme
    assert "EPIC-021.application-ai-advisor.md" in project_readme
