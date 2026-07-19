"""``testing`` package — package-model structural invariant guards.

Mirrors ``test_counter_package.py``: proves the published language equals
``__all__`` and that ``check_package_contract`` discovers and validates the
package (the ``passes-own-governance-gate`` invariant — not a roadmap AC;
see ``common/testing/contract.py``). ``testing`` has no ``apps/backend/src`` counterpart
(``implementations["be"] = "common/testing"``, self-hosted like
``common/meta``/``common/runtime``), so there is no layering or ORM-boundary
check here yet — those apply once the package adopts a ``base/extension``
split.
"""

from __future__ import annotations

from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run

REPO = Path(__file__).resolve().parents[2]
TESTING = REPO / "common" / "testing"


def test_AC_testing_1_1_only_all_is_the_published_language():
    """Invariant interface-equals-published-language: contract.interface == __init__.__all__."""
    import common.testing as testing_pkg

    from common.testing.contract import CONTRACT

    assert sorted(CONTRACT.interface) == sorted(testing_pkg.__all__)
    assert CONTRACT.name == "testing"
    assert CONTRACT.klass == "infra"
    assert CONTRACT.implementations["be"] == "common/testing"
    assert CONTRACT.context is not None
    assert "business-domain acceptance semantics" in CONTRACT.context.out_of_scope
    assert [
        (relation.provider, relation.mode) for relation in CONTRACT.relationships
    ] == [("meta", "published-language")]


def test_AC_testing_1_1_package_contract_gate_passes_for_testing():
    """Invariant passes-own-governance-gate: check_package_contract validates testing (green)."""
    names = {p.name for p in discover_packages(REPO)}
    assert "testing" in names, f"testing not discovered; found {names}"
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)
