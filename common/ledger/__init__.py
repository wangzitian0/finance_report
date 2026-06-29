"""``common.ledger`` — the spec + review surface for the ``ledger`` package.

This package directory holds the *authoritative* form of ``ledger`` — its
ubiquitous-language prose ([`readme.md`](./readme.md), the double-entry SSOT), its
machine-checkable :class:`~common.meta.package_contract.PackageContract`
([`contract.py`](./contract.py)), and its worklist ([`todo.md`](./todo.md)).

The running implementation lives at ``apps/backend/src/ledger``
(``contract.implementations["be"]``). This is a *spec surface*, not the package's
code: the only thing it re-exports is the package's own ``CONTRACT`` (so tooling
can ``from common.ledger import CONTRACT``); the package's published *language* is
the implementation's ``__all__``. See ``common/meta/readme.md`` for the model.
"""

from __future__ import annotations

from common.ledger.contract import CONTRACT

__all__ = ["CONTRACT"]
