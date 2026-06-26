"""``common.meta`` — the package-model meta-scaffolding (a self-hosting package).

A *package* in this repo is a DDD bounded context: a ``readme.md`` (prose /
ubiquitous language) + a :class:`PackageContract` (the machine-checkable
contract in ``contract.py``) + a ``todo.md`` + conforming implementations whose
files converge by layer (``base`` / ``extension`` / ``data``) and whose published
language is declared via ``__all__``.

The meta package now follows the very layout it governs (the Layout-3 exemplar):

* ``base``      — :mod:`common.meta.base.package_contract`: the ``PackageContract``
  aggregate root, its value objects, and the ``Kind`` / ``KIND_LAYER``
  building-block taxonomy (pure model);
* ``extension`` — :mod:`common.meta.extension.check_package_contract`: the
  governance gate (the impure edge that walks the tree and validates);
* ``data``      — :mod:`common.meta.data.projection`: ``contract_index``, the
  computed meta-index (the read-model / projection).

Governance is *computed from contracts*, not hand-maintained: every package
declares a :class:`PackageContract` in ``common/<pkg>/contract.py`` and
``tools/check_package_contract.py`` validates the implementation against it. The
model self-hosts — this package ships its own ``contract.py`` and is checked by
the very gate it provides.

See ``common/meta/readme.md`` for the package-model spec and
``common/counter`` (spec) + ``apps/backend/src/counter`` (implementation) for the
first worked example.
"""

from __future__ import annotations

from common.meta.base.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)
from common.meta.data.projection import contract_index

__all__ = [
    "ACRecord",
    "Invariant",
    "Kind",
    "PackageContract",
    "Unit",
    "contract_index",
]
