"""portfolio package — package-model structural invariant guards (#1422, PR1 commit 1).

These tests prove the structural invariants declared in
``common/portfolio/contract.py`` for the pure ``base/`` layer shipped this
commit: the layers converge, base stays pure, the published language equals
``__all__``, and the governance gate passes. They are invariant proofs, NOT
AC critical-proofs (the domain ACs land in the contract roadmap in a later
commit once the physical fold is done, per this repo's established
precedent — see #1548).
"""

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
PORTFOLIO = REPO / "apps/backend/src/portfolio"

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


def test_AC_portfolio_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.portfolio as portfolio_pkg

    from common.portfolio.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(portfolio_pkg.__all__)
    assert CONTRACT.name == "portfolio"
    assert CONTRACT.implementations["be"] == "apps/backend/src/portfolio"


def test_AC_portfolio_1_2_converges_by_layer():
    """Invariant converges-by-layer: base/errors.py (real) + extension/ + data/ (reserved)."""
    assert (PORTFOLIO / "base" / "errors.py").exists()
    assert (PORTFOLIO / "extension" / "__init__.py").exists()
    assert (PORTFOLIO / "data" / "__init__.py").exists()


def test_AC_portfolio_1_3_base_layer_is_pure():
    """Invariant base-layer-pure: base/ imports no own extension/data, no ORM, no network client."""
    for py in (PORTFOLIO / "base").rglob("*.py"):
        for mod in _imported_modules(py):
            assert not mod.startswith("src.portfolio.extension"), (
                f"{py.name} imports extension ({mod}) from base/"
            )
            assert not mod.startswith("src.portfolio.data"), (
                f"{py.name} imports data ({mod}) from base/"
            )
            assert not mod.startswith(("src.database", "sqlalchemy")), (
                f"{py.name} reaches the ORM from base/"
            )
            assert mod not in {"httpx", "litellm", "aiohttp"}, (
                f"{py.name} reaches a network client from base/"
            )


def test_AC_portfolio_1_4_package_contract_gate_passes():
    """Invariant passes-own-governance-gate: the gate validates portfolio with no violations."""
    packages = discover_packages(REPO)
    assert any(p.contract.name == "portfolio" for p in packages), (
        "portfolio not discovered"
    )
    ok, messages = run(REPO)
    portfolio_errors = [m for m in messages if "[portfolio]" in m]
    assert not portfolio_errors, f"gate violations for portfolio: {portfolio_errors}"
    assert ok, "check_package_contract failed overall"
