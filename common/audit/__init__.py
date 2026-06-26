"""``common.audit`` — the spec + review surface for the ``audit`` package.

This package directory holds the *authoritative* form of ``audit`` (the **number
governor**, the parallel peer to ``meta`` the *form* governor) — its
ubiquitous-language prose ([`readme.md`](./readme.md)), its machine-checkable
:class:`~common.meta.package_contract.PackageContract`
([`contract.py`](./contract.py)), and its worklist ([`todo.md`](./todo.md)).

``audit`` has no implementation of its own yet: the value language it governs
(``Money`` / ``Ratio`` / ``Quantity`` / ``UnitPrice`` and friends) runs in the
Shared-Kernel value packages' cross-runtime mirrors (``common/<pkg>`` +
``apps/backend/src/<pkg>`` + ``apps/frontend/src/lib/<pkg>``). This is a *spec
surface*: the only thing it re-exports is the package's own ``CONTRACT`` (so
tooling can ``from common.audit import CONTRACT``). See ``common/meta/readme.md``
and ``common/meta/migration-standard.md`` for the model and the value→audit fold.
"""

from __future__ import annotations

from common.audit.contract import CONTRACT

__all__ = ["CONTRACT"]
