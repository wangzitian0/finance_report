"""The ``governance`` meta-package's own :class:`PackageContract`.

The package model self-hosts: the meta package that *defines* what a package is
(``PackageContract`` / ``ACRecord`` / ``Invariant`` and the
``check_package_contract`` gate) is itself a package, with a ``readme.md`` (the
package-model spec), this ``contract.py``, and a ``todo.md``. It is discovered
and validated by the very gate it ships, so the model proves itself.

Its BE implementation is ``common/governance`` (the same directory): the
published language is ``common/governance/__init__.py``'s ``__all__``. The gate
resolves ``interface`` against that, and pins each invariant/roadmap AC to a real
governance test.
"""

from __future__ import annotations

from common.governance.package_contract import (
    Invariant,
    PackageContract,
)

CONTRACT = PackageContract(
    name="governance",
    klass="platform",
    status="active",
    depends_on=[],
    roles=["package_contract", "check_package_contract"],
    implementations={"be": "common/governance", "fe": None},
    interface=[
        "ACRecord",
        "Invariant",
        "PackageContract",
    ],
    events=[],
    invariants=[
        Invariant(
            id="contract-equals-published-language",
            statement=(
                "A package's contract.interface must equal its BE implementation's "
                "__init__.__all__; a drift between the declared and published "
                "language is reported by the gate."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_interface_mismatch_is_reported"
            ),
        ),
        Invariant(
            id="unproven-reference-is-rejected",
            statement=(
                "Every invariants[].test and roadmap[].test must resolve to a real "
                "test function; an unresolved reference is a gate failure."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_unresolved_invariant_and_roadmap_refs_are_reported"
            ),
        ),
        Invariant(
            id="dag-down-only",
            statement=(
                "A package's implementation may import only strictly-lower-class "
                "packages declared in depends_on; an upward/sideways/undeclared "
                "edge is rejected (the project stays a DAG)."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_upward_edge_is_forbidden"
            ),
        ),
    ],
    roadmap=[],
)
