"""``common.audit`` — the spec + review surface for the ``audit`` package.

This package directory holds the *authoritative* form of ``audit`` (the **number
governor**, the parallel peer to ``meta`` the *form* governor) — its
ubiquitous-language prose ([`readme.md`](./readme.md)), its machine-checkable
:class:`~common.meta.package_contract.PackageContract`
([`contract.py`](./contract.py)).

The value language ``audit`` governs (``Money`` / ``Ratio`` / ``Quantity`` /
``UnitPrice`` and friends) is physically folded here as domain submodules
(``common.audit.money``, ``common.audit.ratio``, ...) — each still
dependency-light (stdlib + Decimal only), importable from tooling/tests/the
conformance suite without pulling in ``common.meta``/pydantic. ``CONTRACT`` is
therefore lazy-loaded (`PEP 562 <https://peps.python.org/pep-0562/>`_): plain
``from common.audit import CONTRACT`` still works for governance tooling, but
``from common.audit.money import Money`` does not eagerly import
``common.meta.package_contract`` (and its pydantic dependency) just to reach a
domain submodule. See ``common/meta/readme.md`` and
``common/meta/migration-standard.md`` for the model and the value→audit fold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.audit.contract import CONTRACT as CONTRACT

__all__ = ["CONTRACT"]


def __getattr__(name: str):
    if name == "CONTRACT":
        from common.audit.contract import CONTRACT

        return CONTRACT
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
