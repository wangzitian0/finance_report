"""ledger package — package-model structural invariant guards.

``ledger`` is the first ``core`` domain cut over to the package model (#1420). These
tests prove its **structural invariants** (declared in ``common/ledger/contract.py``
``invariants`` and resolved by ``check_package_contract`` via ``invariants[].test``):
the package converges into base/extension/data, base stays pure (never reaches its
own extension/data, the ORM session, or transport), the JournalRepository splits
into a base port + an extension adapter, the published language equals ``__all__``,
and the governance gate passes for ledger. They are invariant proofs, NOT AC
critical-proofs, so they carry no ``@ac_proof`` (the double-entry behavior ACs are
proven by the tests under ``apps/backend/tests/ledger/``).
"""

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
LEDGER = REPO / "apps/backend/src/ledger"

# The implementation is importable as ``src.ledger`` only with ``apps/backend`` on
# the path. Insert it at import time so the published-language test below
# (``import src.ledger``) is order-independent.
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


def test_ledger_converges_by_layer():
    """Invariant converges-by-layer: ledger is structured base/ + extension/ + data/."""
    # base: pure types + validators + the repository port.
    assert (LEDGER / "base/types/entry.py").exists()
    assert (LEDGER / "base/types/errors.py").exists()
    assert (LEDGER / "base/validators.py").exists()
    assert (LEDGER / "base/repository.py").exists()
    # extension: the posting service + the AsyncSession adapter.
    assert (LEDGER / "extension/post.py").exists()
    assert (LEDGER / "extension/repository.py").exists()
    # data: the account-balance projection (read-model sink).
    assert (LEDGER / "data/balance.py").exists()
    # the retired role dirs are gone (single home, zero residue).
    assert not (LEDGER / "types").exists()
    assert not (LEDGER / "ops").exists()
    assert not (LEDGER / "store").exists()
    exports = (LEDGER / "__init__.py").read_text(encoding="utf-8")
    for name in (
        "Entry",
        "Leg",
        "post_entry",
        "JournalRepository",
        "calculate_account_balance",
    ):
        assert name in exports, f"ledger must export {name}"


def test_ledger_processing_converges_by_layer():
    """Invariant processing-converges-by-layer: the processing (in-transit) account
    folded into the package (#1420 slice 3b) splits into a pure base half + an impure
    extension half, and the original ``services/processing_account.py`` is gone (zero
    residue). The pure identity/policy lives in ``base/processing.py``; the DB verbs
    (acquire/post/project/pair) in ``extension/processing.py``.
    """
    base = LEDGER / "base/processing.py"
    ext = LEDGER / "extension/processing.py"
    assert base.exists(), "processing pure core must live in base/processing.py"
    assert ext.exists(), "processing verbs must live in extension/processing.py"

    base_src = base.read_text(encoding="utf-8")
    for name in (
        "class ProcessingAccount",
        "class TransferPair",
        "def detect_transfer_pattern",
    ):
        assert name in base_src, f"base/processing.py must define {name}"

    ext_src = ext.read_text(encoding="utf-8")
    for name in (
        "def get_or_create_processing_account",
        "def find_transfer_pairs",
        "def create_transfer_out_entry",
        "def create_transfer_in_entry",
        "def get_processing_balance",
    ):
        assert name in ext_src, f"extension/processing.py must define {name}"

    # zero residue: the retired service module is deleted, not re-exported.
    assert not (REPO / "apps/backend/src/services/processing_account.py").exists(), (
        "services/processing_account.py must be deleted (folded into ledger, no shim)"
    )


def test_ledger_base_layer_is_pure():
    """Invariant base-layer-pure: base/ never imports the package's own extension/ or
    data/, the ORM session, or the FastAPI/transport edge — base is the downward-only core.
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted((LEDGER / "base").rglob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            if m.startswith("src.ledger.extension")
            or m.startswith("src.ledger.data")
            or "sqlalchemy.ext.asyncio" in m
            or m == "src.database"
            or m.startswith("fastapi")
        }
        if bad:
            offenders[str(path.relative_to(LEDGER))] = bad
    assert not offenders, (
        f"ledger base/ reaches into extension/data/ORM-session: {offenders}"
    )


def test_ledger_repository_splits():
    """Invariant repository-splits: the JournalRepository port is in base/, its adapter
    in extension/ (dependency inversion, mechanism B)."""
    port = (LEDGER / "base/repository.py").read_text(encoding="utf-8")
    assert "class JournalRepository(Protocol)" in port, (
        "the port must be a Protocol in base/"
    )
    adapter = (LEDGER / "extension/repository.py").read_text(encoding="utf-8")
    assert "class SqlJournalRepository" in adapter, (
        "the adapter must live in extension/"
    )
    # the adapter implements the port over an AsyncSession; the pure service depends
    # on the port, not the session.
    post = (LEDGER / "extension/post.py").read_text(encoding="utf-8")
    assert "from src.ledger.base.repository import JournalRepository" in post


def test_ledger_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import src.ledger as ledger_pkg
    from common.ledger.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(ledger_pkg.__all__)
    assert CONTRACT.name == "ledger"
    assert CONTRACT.klass == "domain"
    assert CONTRACT.implementations["be"] == "apps/backend/src/ledger"


def test_ledger_package_contract_gate_passes():
    """Invariant passes-own-governance-gate: check_package_contract validates ledger (green)."""
    names = {p.name for p in discover_packages(REPO)}
    assert "ledger" in names, f"ledger not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
