"""Product E2E owner for EPIC-023 (LLM provider abstraction).

Mirrors the EPIC-021 owner pattern: a marker-`e2e` contract test that anchors the
EPIC to its shipped surface. PR1 ships the *contract* (`src/llm/base`, formerly `src/llm/common`) and the
secret cipher, so the owner asserts that the EPIC doc, the SSOT vocabulary, and
the code module express the three orthogonal axes and the single-pass secret
rotation that the litellm migration (PR2/PR3) builds on.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_llm_provider_abstraction_epic023_product_owner_contract() -> None:
    """EPIC-023 / AC-llm.1.1 AC-llm.1.3: the LLM abstraction has a product E2E owner.

    Anchors the EPIC to (a) the SSOT vocabulary of its three orthogonal axes and
    (b) the secret-rotation contract, so a drift in either surface fails here.
    """
    # The LLM SSOT is internalized into the `llm` package (migration-standard
    # step 3); the package readme is the single owner of the axes/rotation prose.
    ssot = read("common/llm/readme.md")
    types_src = read("apps/backend/src/llm/base/types.py")
    secrets_src = read("apps/backend/src/llm/base/secrets.py")

    # Axis 1 — exactly the three universally-compatible protocol families.
    for family in (
        "openai-compatible",
        "anthropic-compatible",
        "openrouter-compatible",
    ):
        assert family in ssot
        assert family in types_src

    # Axis 3 — the fixed scenes are named in both the SSOT and the code enum.
    for scene in ("extraction.ocr", "extraction.vision", "advisor.chat"):
        assert scene in ssot
        assert scene in types_src

    # Binding is the configurable scene x model surface.
    assert "SceneBinding" in types_src
    assert "Scene × Model" in ssot or "scene->model" in ssot or "scene → model" in ssot

    # Secret encryption is single-pass rotation over a project-level key.
    assert "MultiFernet" in secrets_src
    assert "LLM_ENCRYPTION_KEYS" in ssot
    assert "rotation" in ssot.lower()
    # The rotation contract migrated into the llm package with its ACs (#1591).
    llm_contract = read("common/llm/contract.py")
    assert "single-pass" in llm_contract.lower()
    assert "one pass" in ssot.lower()
