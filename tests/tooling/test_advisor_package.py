"""Structural proofs for the ``advisor`` package (#1671, Wave B).

``AC-advisor.txn.1``: the advisor reads other domains only via their
*published* interfaces — never through the un-migrated app remainder's
internal service paths.  Structurally that means:

* the contract's ``implementations["be"]`` points at a real, physically
  carved package directory (not ``None``, not a ``services/`` path);
* no module inside that directory imports ``src.services.*`` /
  ``src.prompts.*`` / ``src.routers.*`` (the L4 app-remainder
  super-package) or the retired ``src.models.chat`` module — reads whose
  owning domain still lives in the remainder (reporting, report
  readiness, fx, the fx-pair composer) are injected through the
  ``extension/app_reads.py`` ports by the composition root instead;
* the package-contract gate (interface == ``__all__``, DAG honesty both
  ways, one-transaction-per-domain) passes for ``advisor``.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The app-remainder import prefixes AC-advisor.txn.1 forbids inside the
#: advisor package.  ``src.models.chat`` is the advisor's own aggregate —
#: after the move it lives at ``src/advisor/orm/chat.py``, so any import of
#: the old path is a stale reference, not a legal read.
FORBIDDEN_PREFIXES = (
    "src.services",
    "src.prompts",
    "src.routers",
    "src.models.chat",
)


def _advisor_impl_dir() -> Path:
    from common.advisor.contract import CONTRACT

    be_impl = CONTRACT.implementations.get("be")
    assert be_impl, (
        "AC-advisor.txn.1: contract.implementations['be'] is not set — the advisor "
        "package has no physical implementation to hold its boundary."
    )
    assert "/services/" not in be_impl, (
        f"AC-advisor.txn.1: implementations['be']={be_impl!r} still points into the "
        "app remainder (services/) — the physical move has not happened."
    )
    return ROOT / be_impl


def test_AC_advisor_txn_1_impl_exists_at_contracted_path() -> None:
    """AC-advisor.txn.1: the advisor implementation physically lives at the contracted path."""
    impl = _advisor_impl_dir()
    assert (impl / "__init__.py").exists(), f"{impl} has no __init__.py"


def test_AC_advisor_txn_1_reads_only_published_interfaces() -> None:
    """AC-advisor.txn.1: no advisor module imports the app remainder's internal service paths."""
    impl = _advisor_impl_dir()
    offenders: list[str] = []
    for py in sorted(impl.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in FORBIDDEN_PREFIXES
                ):
                    offenders.append(f"{py.relative_to(ROOT)}: imports {module}")
    assert offenders == [], (
        "AC-advisor.txn.1: advisor reads must go through published package roots "
        f"or the registered app_reads ports, never internal service paths:\n"
        + "\n".join(offenders)
    )


def test_AC_advisor_txn_1_package_contract_gate_passes_for_advisor() -> None:
    """AC-advisor.txn.1: the package-contract gate (interface/DAG/txn honesty) passes for advisor."""
    from common.meta.extension.check_package_contract import run

    ok, errors = run(ROOT)
    advisor_errors = [e for e in errors if e.startswith("[advisor]")]
    assert advisor_errors == [], "\n".join(advisor_errors)
