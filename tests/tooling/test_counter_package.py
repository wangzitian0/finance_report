"""counter package + package-model governance guards (EPIC-025 AC-counter.1.x).

The ``counter`` package is the first worked example of the package model. These
guards keep its shape honest — roles converge (types/ops never reach down into
the ORM/session or up into store/api wiring), only ``__all__`` is public — and
assert that the computed governance gate (``check_package_contract``) passes for
counter, so the contract and the live package can never silently drift.
"""

import ast
import sys
from pathlib import Path

from common.governance.check_package_contract import discover_packages, run
from common.testing.ac_proof import ac_proof

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


@ac_proof(
    proof_id="test_counter_converges_by_role", ac_ids=["AC-counter.1.1"], ci_tier="pr_ci"
)
def test_AC25_6_1_counter_converges_by_role():
    """AC-counter.1.1: counter exposes types (nouns/events), ops (verbs), store, api."""
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


@ac_proof(proof_id="test_counter_types_pure", ac_ids=["AC-counter.1.2"], ci_tier="pr_ci")
def test_AC25_6_2_types_never_import_store_api_or_orm():
    """AC-counter.1.2: domain types depend on nothing below them (no store/api/ORM/session).

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


@ac_proof(proof_id="test_counter_ops_pure", ac_ids=["AC-counter.1.3"], ci_tier="pr_ci")
def test_AC25_6_3_ops_never_import_the_orm_session_or_api():
    """AC-counter.1.3: ops depend on the store *port* + types only — no ORM/session/api.

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


@ac_proof(proof_id="test_counter_only_all_public", ac_ids=["AC-counter.1.1"], ci_tier="pr_ci")
def test_AC25_6_1_only_all_is_the_published_language():
    """AC-counter.1.1: the package's contract.interface equals its __init__.__all__."""
    import src.counter as counter_pkg
    from common.counter.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(counter_pkg.__all__)
    assert CONTRACT.name == "counter"
    assert CONTRACT.klass == "platform"
    assert CONTRACT.implementations["be"] == "apps/backend/src/counter"


@ac_proof(
    proof_id="test_counter_contract_gate_passes",
    ac_ids=["AC-counter.1.4"],
    ci_tier="pr_ci",
)
def test_AC25_6_4_package_contract_gate_passes_for_counter():
    """AC-counter.1.4: check_package_contract discovers and validates counter (green)."""
    names = {p.name for p in discover_packages(REPO)}
    assert "counter" in names, f"counter not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
