"""``common.governance`` — the package-model meta-scaffolding.

A *package* in this repo is a DDD bounded context: a README (prose / ubiquitous
language) + a :class:`PackageContract` (the machine-checkable contract) + role
folders ``types/ops/store/api`` + a published language declared via ``__all__``.

Governance is *computed from contracts*, not hand-maintained: every package
declares a :class:`PackageContract` in its ``contract.py`` and
``tools/check_package_contract.py`` validates the live package against it.

See ``docs/ssot/package-model.md`` for the spec and ``apps/backend/src/counter``
for the first worked example.
"""

from __future__ import annotations

from common.governance.package_contract import (
    ACRecord,
    Invariant,
    PackageContract,
)

__all__ = [
    "ACRecord",
    "Invariant",
    "PackageContract",
]
