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
"""

from __future__ import annotations

from common.meta.base.package_contract import KIND_LAYER, SPLIT, PackageContract


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
    for c in contracts:
        for ac in c.roadmap:
            ac_index[ac.id] = c.name

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
        "consumers": consumers,
        "units_by_layer": units_by_layer,
    }
