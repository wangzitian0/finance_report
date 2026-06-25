"""counter package — package-model structural invariant guards.

The ``counter`` package is the first worked example of the package model. These
tests prove its **structural invariants** (declared in
``common/counter/contract.py`` ``invariants`` and resolved by
``check_package_contract`` via ``invariants[].test``): roles converge, the
layers stay pure (types/ops never reach the ORM/session or up into store/api),
the published language equals ``__all__``, and the governance gate passes. They
are invariant proofs, NOT AC critical-proofs, so they carry no ``@ac_proof``
(the domain ACs are proven by the tests under ``apps/backend/tests/counter/``).
"""

import ast
import sys
from pathlib import Path

from common.meta.check_package_contract import discover_packages, run

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


def test_AC_counter_1_1_counter_converges_by_role():
    """Invariant converges-by-role: counter exposes types (nouns/events), ops, store, api."""
    assert (COUNTER / "types/key.py").exists()
    assert (COUNTER / "types/count.py").exists()
    assert (COUNTER / "types/events.py").exists()
    assert (COUNTER / "ops/increment.py").exists()
    assert (COUNTER / "ops/query.py").exists()
    assert (COUNTER / "store/repository.py").exists()
    assert (COUNTER / "store/sql.py").exists()
    exports = (COUNTER / "__init__.py").read_text(encoding="utf-8")
    for name in ("CounterKey", "Count", "Incremented", "increment", "get_count"):
        assert name in exports, f"counter must export {name}"


def test_AC_counter_1_2_types_never_import_store_api_or_orm():
    """Invariant types-layer-pure: domain types depend on nothing below them (no store/api/ORM).

    The value language must stay free of persistence and transport so it is a
    pure, reusable vocabulary (the DAG points down only).
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted((COUNTER / "types").glob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            if m.startswith("src.counter.store")
            or m.startswith("src.counter.api")
            or m.startswith("src.counter.ops")
            or "sqlalchemy" in m
            or m == "src.database"
        }
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"counter types reach below their layer: {offenders}"


def test_AC_counter_1_3_ops_never_import_the_orm_session_or_api():
    """Invariant ops-layer-pure: ops depend on the store *port* + types only — no ORM/session/api.

    Verbs talk to the ``CounterRepository`` Protocol, never to ``store.sql`` /
    ``store.__init__`` concretes, the ORM, or the api boundary.
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted((COUNTER / "ops").glob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            if m.startswith("src.counter.store.sql")
            or m == "src.counter.store"
            or m.startswith("src.counter.api")
            or "sqlalchemy" in m
            or m == "src.database"
        }
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"counter ops reach into ORM/concretes/api: {offenders}"


def test_AC_counter_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.counter as counter_pkg
    from common.counter.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(counter_pkg.__all__)
    assert CONTRACT.name == "counter"
    assert CONTRACT.klass == "platform"
    assert CONTRACT.implementations["be"] == "apps/backend/src/counter"


def test_AC_counter_1_4_package_contract_gate_passes_for_counter():
    """Invariant passes-own-governance-gate: check_package_contract validates counter (green)."""
    names = {p.name for p in discover_packages(REPO)}
    assert "counter" in names, f"counter not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
