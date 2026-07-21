"""``common.meta`` — the package-model meta-scaffolding (a self-hosting package).

A *package* in this repo is a DDD bounded context: a ``readme.md`` (prose /
ubiquitous language) + a :class:`PackageContract` (the machine-checkable
contract in ``contract.py``) + conforming implementations whose
files converge by layer (``base`` / ``extension`` / ``data``) and whose published
language is declared via ``__all__``.

The meta package now follows the very layout it governs (the Layout-3 exemplar):

* ``base``      — :mod:`common.meta.base.package_contract`: the ``PackageContract``
  aggregate root, its value objects, and the ``Kind`` / ``KIND_LAYER``
  building-block taxonomy; :mod:`common.meta.base.dependency_graph` owns the
  typed dependency vocabulary and pure graph policy;
* ``extension`` — :mod:`common.meta.extension.check_package_contract`: the
  governance gate (the impure edge that walks the tree and validates);
* ``data``      — :mod:`common.meta.data.projection`: ``contract_index``,
  ``dependency_index``, and ``ac_vision_index`` computed read-model projections.

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

__all__ = [
    "ACRecord",
    "ConceptRecord",
    "CommandBoundary",
    "GovernanceGuarantee",
    "GovernanceInitiative",
    "DependencyEdge",
    "DependencyKind",
    "Invariant",
    "Kind",
    "PackageContract",
    "Unit",
    "ac_vision_index",
    "concept_index",
    "contract_index",
    "dependency_index",
]

# Lazy re-export (PEP 562): common/meta/extension/ hosts several stdlib-only
# governance gates (check_manifest, check_ssot_ownership, ...) that CI's lint
# job runs with only `--with pyyaml` -- no pydantic. Importing ANY
# common.meta.* submodule always runs this __init__ first, so an eager import
# of the pydantic-backed base/data layers here would drag pydantic into every
# one of those lightweight gates. __getattr__ defers the import until a caller
# actually reaches for ACRecord/ConceptRecord/Invariant/Kind/PackageContract/
# Unit/contract_index/concept_index/ac_vision_index/dependency_index, so
# check_package_contract.py
# (which does
# need the model) still gets it, while the stdlib-only gates never pay the
# cost. (check_manifest.py itself now needs the model too — #1799 — but reaches
# it via a direct `common.meta.extension.check_package_contract` import rather
# than through this lazy attribute, so its CI invocation adds `--with pydantic`
# explicitly instead of relying on this shield.)
_BASE_NAMES = {
    "ACRecord",
    "ConceptRecord",
    "CommandBoundary",
    "GovernanceGuarantee",
    "GovernanceInitiative",
    "DependencyEdge",
    "DependencyKind",
    "Invariant",
    "Kind",
    "PackageContract",
    "Unit",
}


def __getattr__(name: str):
    if name in _BASE_NAMES:
        if name in {"DependencyEdge", "DependencyKind"}:
            from common.meta.base import dependency_graph

            return getattr(dependency_graph, name)
        from common.meta.base import package_contract

        return getattr(package_contract, name)
    if name == "contract_index":
        from common.meta.data.projection import contract_index

        return contract_index
    if name == "concept_index":
        from common.meta.data.projection import concept_index

        return concept_index
    if name == "ac_vision_index":
        from common.meta.data.projection import ac_vision_index

        return ac_vision_index
    if name == "dependency_index":
        from common.meta.data.projection import dependency_index

        return dependency_index
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
