from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_application_ai_advisor_epic021_product_owner_contract() -> None:
    """EPIC-021 / AC21.1.1 AC21.1.2: Advisor value layer has a product E2E owner."""
    epic = read("docs/project/EPIC-021.application-ai-advisor.md")
    # Migrated from docs/ssot/ai.md into the advisor package readme (migration
    # closeout wave 3, #1664); docs/ssot/ai.md is now a pointer stub.
    ssot = read("common/advisor/readme.md")

    assert "Advisor Brief" in epic
    assert "deterministic application facts" in ssot
    assert "not the source of record" in epic
