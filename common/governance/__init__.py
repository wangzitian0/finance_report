"""``common.governance`` — the package-model meta-scaffolding (a self-hosting package).

A *package* in this repo is a DDD bounded context: a ``readme.md`` (prose /
ubiquitous language) + a :class:`PackageContract` (the machine-checkable
contract in ``contract.py``) + a ``todo.md`` + conforming implementations whose
files converge by role (``types/ops/store/api``) and whose published language is
declared via ``__all__``.

Governance is *computed from contracts*, not hand-maintained: every package
declares a :class:`PackageContract` in ``common/<pkg>/contract.py`` and
``tools/check_package_contract.py`` validates the implementation against it. The
model self-hosts — this package ships its own ``contract.py`` and is checked by
the very gate it provides.

See ``common/governance/readme.md`` for the package-model spec and
``common/counter`` (spec) + ``apps/backend/src/counter`` (implementation) for the
first worked example.
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
