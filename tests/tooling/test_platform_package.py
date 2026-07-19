"""platform package — package-model structural invariant guards.

The ``platform`` package (the technical substrate logically labelled
*middleware*: the domain EventBus via the transactional outbox) is cut over to the
``base``/``extension`` building-block layering, mirroring ``counter``. These tests
prove its **structural invariants** (declared in ``common/platform/contract.py``
``invariants`` and resolved by ``check_package_contract`` via ``invariants[].test``):
the package converges by layer, the ``base`` layer stays pure (never reaches its
own ``extension`` or the ORM/session), the ports split into a base port + an
extension adapter (mechanism B), the published language equals ``__all__``, and the
governance gate passes. They are invariant proofs, NOT AC critical-proofs, so they
carry no ``@ac_proof`` (the domain ACs are proven by the DB-backed tests under
``apps/backend/tests/platform/``).
"""

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
PLATFORM = REPO / "apps/backend/src/platform"

# The implementation is importable as ``src.platform`` only with ``apps/backend``
# on the path. Insert it at import time so the published-language test below
# (``import src.platform``) is order-independent.
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


def test_platform_converges_by_layer():
    """Invariant converges-by-layer: platform is base/ (pure core) + extension/ (edges)."""
    # base: the event record + the bus/repo ports.
    assert (PLATFORM / "base/event.py").exists()
    assert (PLATFORM / "base/bus.py").exists()
    assert (PLATFORM / "base/outbox.py").exists()
    # extension: the bus adapters, the relay, and the SQL outbox adapter + table.
    assert (PLATFORM / "extension/bus.py").exists()
    assert (PLATFORM / "extension/relay.py").exists()
    assert (PLATFORM / "extension/sql.py").exists()
    # the retired role dirs are GONE (single home; no residue).
    assert not (PLATFORM / "events").exists()
    assert not (PLATFORM / "store").exists()
    exports = (PLATFORM / "__init__.py").read_text(encoding="utf-8")
    for name in ("DomainEvent", "EventBus", "Outbox", "OutboxEventBus", "OutboxRelay"):
        assert name in exports, f"platform must export {name}"


def test_platform_repository_split():
    """Invariant repository-split: the bus and outbox-repo ports each split into a
    base port + an extension adapter (dependency inversion, mechanism B).
    """
    # outbox repository: port in base/, SQL adapter in extension/.
    assert (PLATFORM / "base/outbox.py").exists()
    assert (PLATFORM / "extension/sql.py").exists()
    # event bus: port in base/, concrete adapters in extension/.
    assert (PLATFORM / "base/bus.py").exists()
    assert (PLATFORM / "extension/bus.py").exists()
    sql = (PLATFORM / "extension/sql.py").read_text(encoding="utf-8")
    assert "class SqlOutboxRepository" in sql
    ext_bus = (PLATFORM / "extension/bus.py").read_text(encoding="utf-8")
    assert "class OutboxEventBus" in ext_bus


def test_platform_base_layer_is_pure():
    """Invariant base-layer-pure: the base/ layer never imports the package's own
    extension/ layer or the ORM — base is the pure, downward-only core.
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted((PLATFORM / "base").rglob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            # base must not reach its own extension — neither directly nor via the
            # package root (``import src.platform`` / ``from src.platform import …``
            # re-exports the extension layer), nor the ORM.
            if m.startswith("src.platform.extension")
            or m == "src.platform"
            or "sqlalchemy" in m
            or m == "src.database"
        }
        if bad:
            offenders[str(path.relative_to(PLATFORM))] = bad
    assert not offenders, f"platform base/ reaches into extension/ORM: {offenders}"


def test_platform_interface_equals_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.platform as platform_pkg
    from common.platform.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(platform_pkg.__all__)
    assert CONTRACT.name == "platform"
    assert CONTRACT.klass == "infra"
    assert CONTRACT.implementations["be"] == "apps/backend/src/platform"
    assert CONTRACT.context is not None
    assert {relation.provider for relation in CONTRACT.relationships} == set(
        CONTRACT.depends_on
    )


def test_platform_package_contract_gate_passes():
    """Invariant passes-own-governance-gate: check_package_contract validates platform (green)."""
    names = {p.name for p in discover_packages(REPO)}
    assert "platform" in names, f"platform not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
