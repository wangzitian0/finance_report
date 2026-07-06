"""``common.advisor`` — the spec + review surface for the ``advisor`` package.

This package directory holds the *authoritative* form of ``advisor`` — its
ubiquitous-language prose ([`readme.md`](./readme.md)), its machine-checkable
:class:`~common.meta.package_contract.PackageContract`
([`contract.py`](./contract.py)), and its worklist ([`todo.md`](./todo.md)).

The running implementation currently lives at
``apps/backend/src/services/ai_advisor`` (the pre-migration location).
It will move to ``apps/backend/src/advisor``
(``contract.implementations["be"]``) in PR2 of the cutover.  This is a *spec
surface*, not the package's code: the only thing it re-exports is the
package's own ``CONTRACT`` (so tooling can ``from common.advisor import
CONTRACT``); the package's published *language* is the implementation's
``__all__``.  See ``common/meta/readme.md`` for the model.
"""

from __future__ import annotations

from common.advisor.contract import CONTRACT

__all__ = ["CONTRACT"]
