"""identity package — package-model structural invariant guards.

The ``identity`` package (users + authentication + AI-feedback) is cut over to the
``base``/``extension`` building-block layering, mirroring ``counter``/``platform``.
These tests prove its **structural invariants** (declared in
``common/identity/contract.py`` ``invariants`` and resolved by
``check_package_contract`` via ``invariants[].test``): the package converges by
layer, the god-files it replaces are gone (single home, zero residue), the
``UserRepository`` port splits into a base port + an extension adapter (mechanism
B), the ``base`` layer stays pure (never reaches its own ``extension``), the
published language equals ``__all__``, and the governance gate passes. They are
invariant proofs, NOT AC critical-proofs, so they carry no ``@ac_proof`` (the
domain ACs are proven by the DB-backed tests under ``apps/backend/tests/identity``).
"""

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
IDENTITY = REPO / "apps/backend/src/identity"

# The implementation is importable as ``src.identity`` only with ``apps/backend``
# on the path. Insert it at import time so the published-language test below
# (``import src.identity``) is order-independent.
_BACKEND_ROOT = str(REPO / "apps" / "backend")
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# The pre-migration god-files this cutover consolidates and DELETES (zero residue).
RETIRED_GOD_FILES = [
    "apps/backend/src/auth.py",
    "apps/backend/src/security.py",
    "apps/backend/src/rate_limit.py",
    "apps/backend/src/observability_events.py",
    "apps/backend/src/routers/auth.py",
    "apps/backend/src/routers/users.py",
    "apps/backend/src/schemas/auth.py",
    "apps/backend/src/schemas/ai_feedback.py",
    "apps/backend/src/models/user.py",
]


def _imported_modules(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_identity_converges_by_layer():
    """Invariant converges-by-layer: identity is base/ (pure core) + extension/ (edges)."""
    # base: the pure value objects + the repository port.
    assert (IDENTITY / "base/types/auth.py").exists()
    assert (IDENTITY / "base/types/ai_feedback.py").exists()
    assert (IDENTITY / "base/repository.py").exists()
    # extension: the ORM adapter + table models, security, auth dep, rate limiters,
    # observability, and the /auth + /users transport.
    assert (IDENTITY / "extension/sql.py").exists()
    assert (IDENTITY / "extension/security.py").exists()
    assert (IDENTITY / "extension/auth.py").exists()
    assert (IDENTITY / "extension/rate_limit.py").exists()
    assert (IDENTITY / "extension/observability.py").exists()
    assert (IDENTITY / "extension/api/auth.py").exists()
    assert (IDENTITY / "extension/api/users.py").exists()
    exports = (IDENTITY / "__init__.py").read_text(encoding="utf-8")
    for name in ("User", "AiFeedback", "get_current_user_id", "register", "login"):
        assert name in exports, f"identity must export {name}"


def test_identity_god_files_are_gone():
    """Invariant single-home-no-residue: the pre-migration god-files are DELETED.

    identity is the single home; a lingering original means the package is NOT
    migrated (DoD step 6).
    """
    lingering = [p for p in RETIRED_GOD_FILES if (REPO / p).exists()]
    assert not lingering, (
        f"retired god-files still present (zero-residue violated): {lingering}"
    )


def test_identity_repository_split():
    """Invariant repository-split: the UserRepository port splits into a base port
    + an extension SQL adapter (dependency inversion, mechanism B).
    """
    assert (IDENTITY / "base/repository.py").exists()
    assert (IDENTITY / "extension/sql.py").exists()
    port = (IDENTITY / "base/repository.py").read_text(encoding="utf-8")
    assert "class UserRepository" in port and "Protocol" in port
    adapter = (IDENTITY / "extension/sql.py").read_text(encoding="utf-8")
    assert "class SqlUserRepository" in adapter


def test_identity_base_layer_is_pure():
    """Invariant base-layer-pure: the base/ layer never imports the package's own
    extension/ layer (nor, here, the ORM) — base is the pure, downward-only core.
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted((IDENTITY / "base").rglob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            if m.startswith("src.identity.extension")
            or m == "src.identity"
            or "sqlalchemy" in m
            or m == "src.database"
        }
        if bad:
            offenders[str(path.relative_to(IDENTITY))] = bad
    assert not offenders, f"identity base/ reaches into extension/ORM: {offenders}"


def test_identity_interface_equals_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.identity as identity_pkg
    from common.identity.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(identity_pkg.__all__)
    assert CONTRACT.name == "identity"
    assert CONTRACT.klass == "core"
    assert CONTRACT.implementations["be"] == "apps/backend/src/identity"


def test_identity_package_contract_gate_passes():
    """Invariant passes-own-governance-gate: check_package_contract validates identity (green)."""
    names = {p.name for p in discover_packages(REPO)}
    assert "identity" in names, f"identity not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
