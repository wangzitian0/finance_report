"""extraction package — package-model structural invariant guards (#1421 Stage-2 cutover).

These tests prove the structural invariants declared in
``common/extraction/contract.py``: the layers converge (the old
``services/extraction`` + flat service-module homes are gone), base stays pure
(no own extension/data, no ORM, no network client), the published language
equals ``__all__``, and the governance gate passes. They are invariant proofs,
NOT AC critical-proofs, so they carry no ``@ac_proof`` (the domain ACs live in
the contract roadmap and are proven by ``apps/backend/tests/extraction/``).
"""

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
EXTRACTION = REPO / "apps/backend/src/extraction"

_BACKEND_ROOT = str(REPO / "apps" / "backend")
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _imported_modules(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_AC_extraction_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.extraction as extraction_pkg

    from common.extraction.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(extraction_pkg.__all__)
    assert CONTRACT.name == "extraction"
    assert CONTRACT.klass == "core"
    assert CONTRACT.implementations["be"] == "apps/backend/src/extraction"


def test_AC_extraction_1_2_converges_by_layer():
    """Invariant converges-by-layer: base/extension/data — old homes emptied."""
    assert (EXTRACTION / "base/validation.py").exists()
    for mod in (
        "service.py",
        "_base.py",
        "_brokerage.py",
        "_coerce.py",
        "_csv.py",
        "_llm_led_gate.py",
        "_media.py",
        "_ocr.py",
        "deduplication.py",
        "brokerage_positions.py",
        "statement_summary.py",
        "currency_resolution.py",
        "evidence_graph_integration.py",
        "evidence_lineage.py",
        "evidence_graph_materialization.py",
        "prompts/statement.py",
        "prompts/csv_mapping.py",
    ):
        assert (EXTRACTION / "extension" / mod).exists(), f"missing extension/{mod}"
    assert (EXTRACTION / "data/__init__.py").exists()
    # the pre-cutover homes are gone (zero residue)
    services = REPO / "apps/backend/src/services"
    assert not (services / "extraction").exists()
    for stray in (
        "validation.py",
        "deduplication.py",
        "brokerage_positions.py",
        "statement_summary.py",
        "currency_resolution.py",
        "evidence_graph_integration.py",
        "evidence_lineage.py",
        "evidence_graph_materialization.py",
    ):
        assert not (services / stray).exists(), f"old home leftover: services/{stray}"
    prompts = REPO / "apps/backend/src/prompts"
    assert not (prompts / "statement.py").exists()
    assert not (prompts / "csv_mapping.py").exists()


def test_AC_extraction_1_3_base_layer_is_pure():
    """Invariant base-layer-pure: base/ imports no own extension/data, ORM, or network client."""
    for py in (EXTRACTION / "base").rglob("*.py"):
        for mod in _imported_modules(py):
            assert not mod.startswith("src.extraction.extension"), (
                f"{py.name} imports extension ({mod}) from base/"
            )
            assert not mod.startswith("src.extraction.data"), (
                f"{py.name} imports data ({mod}) from base/"
            )
            assert not mod.startswith(("src.database", "sqlalchemy")), (
                f"{py.name} reaches the ORM from base/"
            )
            assert mod not in {"httpx", "litellm", "aiohttp"}, (
                f"{py.name} reaches a network client from base/"
            )


def test_AC_extraction_1_4_package_contract_gate_passes():
    """Invariant passes-own-governance-gate: the gate validates extraction with no violations."""
    packages = discover_packages(REPO)
    assert any(p.contract.name == "extraction" for p in packages), (
        "extraction not discovered"
    )
    ok, messages = run(REPO)
    extraction_errors = [m for m in messages if "[extraction]" in m]
    assert not extraction_errors, f"gate violations: {extraction_errors}"
    assert ok, "check_package_contract failed overall"
