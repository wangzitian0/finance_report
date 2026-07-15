"""One PII-redacting error-text sanitizer per backend (AC-observability.safe-error-ssot).

The canonical sanitizer is ``src/observability/audit.py::safe_error_message``
(whitespace collapse + PII redaction + length bound). The 2026-07-15 signature
review (#1864) found three naive ``return message[:500]`` copies named
``_safe_error_message`` in routers/extraction plus a truncate-only variant in
telemetry — none redacted PII, so parse/match failure text reached logs and the
``validation_error`` column raw. This gate keeps the copies from coming back.
"""

from __future__ import annotations

from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO / "apps" / "backend" / "src"
CANONICAL = BACKEND_SRC / "observability" / "audit.py"


def _backend_source_files() -> list[Path]:
    return [
        path for path in BACKEND_SRC.rglob("*.py") if "__pycache__" not in path.parts
    ]


@ac_proof(
    proof_id="test_safe_error_message_single_sanitizer",
    ac_ids=["AC-observability.safe-error-ssot.1"],
    ci_tier="pr_ci",
)
def test_AC_safe_error_ssot_1_single_sanitizer_definition():
    """AC-observability.safe-error-ssot.1: no local ``_safe_error_message`` copies."""
    offenders = [
        str(path.relative_to(REPO))
        for path in _backend_source_files()
        if "def _safe_error_message(" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "local _safe_error_message copies bypass PII redaction; import "
        f"src.observability.audit.safe_error_message instead: {offenders}"
    )

    canonical_src = CANONICAL.read_text(encoding="utf-8")
    assert "def safe_error_message(" in canonical_src, (
        "canonical sanitizer missing from src/observability/audit.py"
    )
