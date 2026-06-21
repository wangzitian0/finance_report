"""``common.counter`` — the spec + review surface for the ``counter`` package.

This package directory holds the *authoritative* form of ``counter`` — its
ubiquitous-language prose ([`readme.md`](./readme.md)), its machine-checkable
:class:`~common.governance.package_contract.PackageContract`
([`contract.py`](./contract.py)), and its worklist ([`todo.md`](./todo.md)).

The running implementation lives at ``apps/backend/src/counter``
(``contract.implementations["be"]``); this module intentionally exports nothing —
it is a spec surface, not code. See ``common/governance/readme.md`` for the model.
"""

from __future__ import annotations

from common.counter.contract import CONTRACT

__all__ = ["CONTRACT"]
