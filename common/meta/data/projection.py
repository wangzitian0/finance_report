"""``contract_index`` — the computed meta-index over package contracts.

This is the meta package's ``data`` layer: a CQRS-style **read model** derived
from the write side (the :class:`~common.meta.base.package_contract.PackageContract`
aggregates). It is a pure projection — a function of the contracts it is handed,
with no I/O and no discovery of its own. Discovery (walking the filesystem) is an
``extension`` concern; the caller passes the already-loaded contracts in, so this
layer depends only on ``base`` and stays a leaf sink.

The index answers the questions the standard's ``data`` layer is meant to:

* **registry** — name -> class / tier / status, the at-a-glance package table;
* **ac_index** — every roadmap AC id -> the package that owns it (no AC is owned
  twice);
* **consumers** — reverse dependencies (who depends on each package), the
  blast-radius view;
* **units_by_layer** — per package, how many DDD building-block units land in
  ``base`` / ``extension`` / ``data`` (the extension fan-out / anti-mud-ball
  metric: a package whose ``extension`` count balloons is drifting toward a mud
  ball).

Sibling projections answer the same computed-registry question for package
declarations: :func:`concept_index` maps SSOT concepts to their metadata, while
:func:`ac_vision_index` maps roadmap AC ids to their declared ``vision.md``
anchors. :func:`dependency_index` is the reviewable dependency plane: typed
contract edges plus deterministic direct and transitive consumers.
"""

from __future__ import annotations

from common.meta.base.dependency_graph import build_dependency_graph
from common.meta.base.package_contract import (
    KIND_LAYER,
    SPLIT,
    ConceptRecord,
    PackageContract,
)


def dependency_index(contracts: list[PackageContract]) -> dict[str, object]:
    """Project validated package contracts into the dependency read model."""

    return build_dependency_graph(contracts).as_dict()


def contract_index(contracts: list[PackageContract]) -> dict[str, dict]:
    """Project a set of package contracts into the computed meta-index.

    Pure: the result is a function of ``contracts`` alone. ``consumers`` and
    ``ac_index`` only reference packages within the given set, so the projection
    is well-defined over any subset (e.g. a single package in a test).
    """
    by_name = {c.name: c for c in contracts}

    registry: dict[str, dict] = {
        c.name: {"klass": c.klass, "tier": c.tier, "status": c.status}
        for c in contracts
    }

    ac_index: dict[str, str] = {}
    roadmap: dict[str, dict] = {}
    for c in contracts:
        for ac in c.roadmap:
            owner = ac_index.get(ac.id)
            if owner is not None:
                raise ValueError(
                    f"AC {ac.id!r} is claimed by two packages or twice within one "
                    f"package: {owner!r} and {c.name!r}"
                )
            ac_index[ac.id] = c.name
            roadmap[ac.id] = {
                "owner": c.name,
                "statement": ac.statement,
                "test": ac.test,
                "priority": ac.priority,
                "status": ac.status,
                "proof_kind": ac.proof_kind,
                "vision_anchor": ac.vision_anchor,
            }

    governance: dict[str, dict] = {}
    for c in contracts:
        for initiative in c.governance:
            key = f"{c.name}/{initiative.id}"
            governance[key] = {
                "owner": c.name,
                **initiative.model_dump(mode="json"),
            }

    consumers: dict[str, list[str]] = {name: [] for name in by_name}
    for c in contracts:
        for dep in c.depends_on:
            if dep in consumers:
                consumers[dep].append(c.name)
    consumers = {name: sorted(deps) for name, deps in consumers.items()}

    units_by_layer: dict[str, dict[str, int]] = {}
    for c in contracts:
        counts = {"base": 0, "extension": 0, "data": 0}
        for unit in c.units:
            layer = KIND_LAYER[unit.kind]
            if layer == SPLIT:
                # a repository spans both sides of the dependency inversion.
                counts["base"] += 1
                counts["extension"] += 1
            else:
                counts[layer] += 1
        units_by_layer[c.name] = counts

    return {
        "registry": registry,
        "ac_index": ac_index,
        "roadmap": roadmap,
        "governance": governance,
        "consumers": consumers,
        "units_by_layer": units_by_layer,
        "command_boundaries": {
            c.name: [
                boundary.model_dump(mode="json") for boundary in c.command_boundaries
            ]
            for c in contracts
        },
    }


def ac_vision_index(contracts: list[PackageContract]) -> dict[str, str]:
    """Project roadmap vision declarations into ``{ac_id: vision_anchor}``.

    Pure and intentionally AC-keyed: several ACs may back the same vision node,
    so anchors are not ownership keys and need no double-claim check here.
    Duplicate AC ownership is already rejected by :func:`contract_index`.
    """
    return {
        ac.id: ac.vision_anchor
        for contract in contracts
        for ac in contract.roadmap
        if ac.vision_anchor is not None
    }


def _concept_dict(concept: ConceptRecord) -> dict:
    return {
        "owner": concept.owner,
        "description": concept.description,
        "cross_refs": list(concept.cross_refs),
        "proofs": list(concept.proofs),
        "family": concept.family,
        "kind": concept.kind,
        "authority": concept.authority,
        "parent": concept.parent,
    }


def concept_index(contracts: list[PackageContract]) -> dict[str, dict]:
    """Project package-declared concepts into the computed concept registry.

    Pure: the result is a function of ``contracts`` alone, mirroring
    :func:`contract_index`'s ``ac_index``. The returned shape matches a
    ``common/meta/data/MANIFEST.yaml`` concept entry exactly (``owner``,
    ``description``, ``cross_refs``, plus the optional classification
    fields), so a caller can merge it with the residual (no-owning-package)
    entries still hand-kept in ``MANIFEST.yaml`` and hand the union straight
    to ``check_manifest.py``'s existing checks.
    """
    concepts: dict[str, dict] = {}
    owner_package: dict[str, str] = {}
    for c in contracts:
        for concept in c.concepts:
            existing = owner_package.get(concept.key)
            if existing is not None and existing != c.name:
                # No concept is owned twice. A duplicate key across packages is
                # a contract-integrity violation; surface it instead of
                # silently overwriting the owner mapping.
                raise ValueError(
                    f"concept {concept.key!r} is claimed by two packages: "
                    f"{existing!r} and {c.name!r}"
                )
            owner_package[concept.key] = c.name
            concepts[concept.key] = _concept_dict(concept)
    return concepts
