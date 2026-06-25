"""``common.platform`` — the spec + review surface for the ``platform`` package.

This directory holds the *authoritative* form of ``platform`` — its
ubiquitous-language prose ([`readme.md`](./readme.md)), its machine-checkable
:class:`~common.meta.package_contract.PackageContract`
([`contract.py`](./contract.py)), and its worklist ([`todo.md`](./todo.md)).

The running implementation lives at ``apps/backend/src/platform``
(``contract.implementations["be"]``). This is a *spec surface*, not the package's
code: the only thing it re-exports is the package's own ``CONTRACT`` (so tooling
can ``from common.platform import CONTRACT``). See ``common/meta/readme.md``
for the model and ``common/counter`` for the first worked example.
"""

from __future__ import annotations

from common.platform.contract import CONTRACT

__all__ = ["CONTRACT"]
