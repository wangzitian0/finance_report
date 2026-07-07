"""reconciliation package — package-model structural invariant guards."""

import ast
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
RECONCILIATION = REPO / "apps/backend/src/reconciliation"

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


def test_reconciliation_converges_by_layer():
    assert (RECONCILIATION / "base/config.py").exists()
    assert (RECONCILIATION / "base/repository.py").exists()
    assert (RECONCILIATION / "extension/matching.py").exists()
    assert (RECONCILIATION / "extension/repository.py").exists()
    assert (RECONCILIATION / "extension/phases/transfer_detection.py").exists()
    assert (RECONCILIATION / "extension/phases/many_to_one.py").exists()
    assert (RECONCILIATION / "extension/phases/normal_matching.py").exists()
    assert (RECONCILIATION / "data/stats.py").exists()
    assert not (REPO / "apps/backend/src/services/reconciliation.py").exists()


def test_reconciliation_base_layer_is_pure():
    offenders: dict[str, set[str]] = {}
    for path in sorted((RECONCILIATION / "base").rglob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            if m.startswith("src.reconciliation.extension")
            or m.startswith("src.reconciliation.data")
            or "sqlalchemy" in m
            or m == "src.database"
            or m.startswith("fastapi")
        }
        if bad:
            offenders[str(path.relative_to(RECONCILIATION))] = bad
    assert not offenders, f"reconciliation base/ reaches impure edges: {offenders}"


def test_reconciliation_only_all_is_the_published_language():
    import src.reconciliation as reconciliation_pkg
    from common.reconciliation.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(reconciliation_pkg.__all__)
    assert CONTRACT.name == "reconciliation"
    assert CONTRACT.implementations["be"] == "apps/backend/src/reconciliation"


def test_reconciliation_package_contract_gate_passes():
    names = {p.name for p in discover_packages(REPO)}
    assert "reconciliation" in names, f"reconciliation not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
