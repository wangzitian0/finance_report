"""pricing package — package-model structural invariant guards (#1610, PR1 commit 1).

These tests prove the structural invariants declared in
``common/pricing/contract.py`` for the pure ``base/`` layer shipped this
commit: the layers converge, base stays pure, the published language equals
``__all__``, observations are append-only by construction (frozen dataclass,
no update/delete method exists), ``audit.money.convert`` takes a rate as an
argument (never looks up one), and the governance gate passes. They are
invariant proofs, NOT AC critical-proofs (the domain ACs land in the
contract roadmap in a later commit and are proven under
``apps/backend/tests/pricing/``).
"""

import ast
import inspect
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
PRICING = REPO / "apps/backend/src/pricing"

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


def test_AC_pricing_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.pricing as pricing_pkg

    from common.pricing.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(pricing_pkg.__all__)
    assert CONTRACT.name == "pricing"
    assert CONTRACT.implementations["be"] == "apps/backend/src/pricing"


def test_AC_pricing_1_2_converges_by_layer():
    """Invariant converges-by-layer: base/ (real) + extension/resolve.py (real) + data/ (reserved)."""
    for mod in (
        "subject.py",
        "observation.py",
        "policy.py",
        "events.py",
        "errors.py",
        "repository.py",
    ):
        assert (PRICING / "base" / mod).exists(), f"missing base/{mod}"
    assert not (PRICING / "base/resolve.py").exists(), (
        "resolve() is a DOMAIN_SERVICE — KIND_LAYER places it in extension/, not base/"
    )
    assert (PRICING / "extension/resolve.py").exists()
    assert (PRICING / "data/__init__.py").exists()


def test_AC_pricing_1_3_base_layer_is_pure():
    """Invariant base-layer-pure: base/ imports no own extension/data, no ORM, no network client."""
    for py in (PRICING / "base").rglob("*.py"):
        for mod in _imported_modules(py):
            assert not mod.startswith("src.pricing.extension"), (
                f"{py.name} imports extension ({mod}) from base/"
            )
            assert not mod.startswith("src.pricing.data"), (
                f"{py.name} imports data ({mod}) from base/"
            )
            assert not mod.startswith(("src.database", "sqlalchemy")), (
                f"{py.name} reaches the ORM from base/"
            )
            assert mod not in {"httpx", "litellm", "aiohttp"}, (
                f"{py.name} reaches a network client from base/"
            )


def test_AC_pricing_1_4_observations_are_append_only_by_construction():
    """Invariant observations-are-append-only: PriceObservation is frozen, no mutator method."""
    from src.pricing.base.observation import PriceObservation

    assert PriceObservation.__dataclass_params__.frozen, (
        "PriceObservation must be a frozen dataclass"
    )
    mutators = {
        name
        for name, member in inspect.getmembers(
            PriceObservation, predicate=inspect.isfunction
        )
        if name.startswith(("set_", "update", "delete", "mutate"))
    }
    assert not mutators, (
        f"PriceObservation must expose no mutator methods, found: {mutators}"
    )


def test_AC_pricing_1_5_audit_convert_takes_rate_as_argument():
    """Invariant audit-never-looks-up-a-rate: convert()'s signature takes a rate, does no lookup."""
    import inspect as _inspect

    from src.audit.money.convert import convert

    sig = _inspect.signature(convert)
    assert "rate" in sig.parameters, (
        "audit.money.convert must accept a rate argument (it never looks one up)"
    )
    source = _inspect.getsource(convert)
    assert "select(" not in source and "session" not in source.lower(), (
        "audit.money.convert must do no database lookup"
    )


def test_AC_pricing_1_6_package_contract_gate_passes():
    """Invariant passes-own-governance-gate: the gate validates pricing with no violations."""
    packages = discover_packages(REPO)
    assert any(p.contract.name == "pricing" for p in packages), "pricing not discovered"
    ok, messages = run(REPO)
    pricing_errors = [m for m in messages if "[pricing]" in m]
    assert not pricing_errors, f"gate violations for pricing: {pricing_errors}"
    assert ok, "check_package_contract failed overall"
