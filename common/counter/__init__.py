"""``common.counter`` — the spec + review surface for the ``counter`` package.

This package directory holds the *authoritative* form of ``counter`` — its
ubiquitous-language prose ([`readme.md`](./readme.md)), its machine-checkable
:class:`~common.meta.package_contract.PackageContract`
([`contract.py`](./contract.py)), and its worklist ([`todo.md`](./todo.md)).

The running implementation lives at ``apps/backend/src/counter``
(``contract.implementations["be"]``). This is a *spec surface*, not the package's
code: the only thing it re-exports is the package's own ``CONTRACT`` (so tooling
can ``from common.counter import CONTRACT``); the package's published *language*
is the implementation's ``__all__``. See ``common/meta/readme.md`` for the
model.
"""

from __future__ import annotations

from common.counter.contract import CONTRACT

__all__ = ["CONTRACT"]
