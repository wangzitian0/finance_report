"""AC-llm.10.7 (#1597): downstream must not know whether the LLM is real or frozen.

The cassette decision lives entirely inside the llm layer. Outside the layer (and
its own tests), no code may reference the cassette machinery or its layer-owned
knobs — the #1570 failure class (a process-level mode env silently skipping every
replay test for months) becomes structurally impossible to reintroduce.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The layer itself + the layer's own tests + the two sanctioned bootstrap points.
_ALLOWED = (
    "apps/backend/src/llm/",
    "apps/backend/tests/llm/",
    # the test HARNESS engages the layer exactly once (and maps --llm-record to
    # the refresh knob); individual tests still cannot tell real from frozen.
    "apps/backend/tests/conftest.py",
    # the llm package's formal contract home (its roadmap ACs describe the layer).
    "common/llm/",
    # the sanctioned corpus-recording operator tool (cassette PRODUCTION, like
    # `make llm-record` — not downstream consumption).
    "tools/_lib/record_hf_cassettes.py",
    # governance INTROSPECTION: the authority classifier detects LLM-band tests
    # by recognising these very tokens — it reads names, it never uses the layer.
    "common/authority/authority_classifier.py",
    "tests/tooling/test_authority_classifier.py",
    # facade->litellm WIRE-integration tests (mock below the transport; use the
    # layer's LIVE seam to reach their stubs).
    "apps/backend/tests/ai/test_ai_streaming.py",
    # this gate itself names the banned tokens.
    "tests/tooling/test_llm_cassette_boundary.py",
)

# Symbols + layer-owned env names that downstream code must never reference.
_BANNED = (
    "CassetteMode",
    "current_mode",
    "CassetteRecorder",
    "cassette_completion",
    "LLM_CASSETTE_MODE",
    "LLM_CASSETTE_ENGAGE",
    "LLM_CASSETTE_REFRESH",
    "LLM_LIVE",
    "src.llm.extension.cassette",
)

_SCAN_ROOTS = ("apps/backend/src", "apps/backend/tests", "tests", "common", "tools")


def test_AC_llm_10_7_no_cassette_knowledge_outside_the_layer() -> None:
    """AC-llm.10.7: zero cassette symbols/knobs outside the llm layer."""
    hits: list[str] = []
    for base in _SCAN_ROOTS:
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if any(rel.startswith(a) or rel == a for a in _ALLOWED):
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in _BANNED:
                if token in text:
                    hits.append(f"{rel}: {token}")
    assert hits == [], (
        "downstream code references the cassette layer's internals/knobs "
        f"(the layer decides per request; downstream must not know): {hits}"
    )
