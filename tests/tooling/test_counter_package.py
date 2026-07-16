"""counter package — package-model structural invariant guards.

The ``counter`` package is the first worked example of the package model. These
tests prove its **structural invariants** (declared in
``common/counter/contract.py`` ``invariants`` and resolved by
``check_package_contract`` via ``invariants[].test``): the base/extension/data
layers stay pure (``base`` never reaches the ORM/session or up into
``extension``/``data``), the published language equals ``__all__``, and the
governance gate passes. They
are invariant proofs, NOT AC critical-proofs, so they carry no ``@ac_proof``
(the domain ACs are proven by the tests under ``apps/backend/tests/counter/``).
"""

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
COUNTER = REPO / "apps/backend/src/counter"

# The implementation is importable as ``src.counter`` only with ``apps/backend``
# on the path. Insert it at import time so the published-language test below
# (``import src.counter``) is order-independent — it must not rely on another
# test having triggered the governance gate's sys.path side effect first.
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


def test_AC_counter_1_1_counter_converges_by_layer():
    """Invariant converges-by-layer: counter is structured base/ (pure core) + extension/ (edges)."""
    # base: pure types + ops + the store port.
    assert (COUNTER / "base/types/key.py").exists()
    assert (COUNTER / "base/types/count.py").exists()
    assert (COUNTER / "base/types/events.py").exists()
    assert (COUNTER / "base/ops/increment.py").exists()
    assert (COUNTER / "base/ops/query.py").exists()
    assert (COUNTER / "base/repository.py").exists()
    # extension: the ORM adapter + the async boundary.
    assert (COUNTER / "extension/sql.py").exists()
    assert (COUNTER / "extension/facade/write.py").exists()
    assert not (COUNTER / "extension/api").exists()
    # the retired role dirs are gone.
    assert not (COUNTER / "types").exists() and not (COUNTER / "store").exists()
    exports = (COUNTER / "__init__.py").read_text(encoding="utf-8")
    for name in ("CounterKey", "Count", "Incremented", "increment", "get_count"):
        assert name in exports, f"counter must export {name}"


def test_AC_counter_1_2_base_layer_is_pure():
    """Invariant base-layer-pure: the base/ layer never imports the package's own
    extension/ layer or the ORM — base is the pure, downward-only core.
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted((COUNTER / "base").rglob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            if m.startswith(
                "src.counter.extension"
            )  # base must not reach its own extension
            or "sqlalchemy" in m
            or m == "src.database"
        }
        if bad:
            offenders[str(path.relative_to(COUNTER))] = bad
    assert not offenders, f"counter base/ reaches into extension/ORM: {offenders}"


def test_AC_counter_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.counter as counter_pkg
    from common.counter.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(counter_pkg.__all__)
    assert CONTRACT.name == "counter"
    assert CONTRACT.klass == "middleware"
    assert CONTRACT.implementations["be"] == "apps/backend/src/counter"


def test_AC_counter_1_4_package_contract_gate_passes_for_counter():
    """Invariant passes-own-governance-gate: check_package_contract validates counter (green)."""
    names = {p.name for p in discover_packages(REPO)}
    assert "counter" in names, f"counter not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
