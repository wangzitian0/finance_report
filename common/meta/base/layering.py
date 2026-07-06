"""Single machine source of the five-layer package topology.

``meta < infra < middleware < domain < app`` — the project's dependency ladder.
Placement is **global topology**, so it is owned here in L0 (the meta package)
as one central map instead of per-contract self-claims: a package's
``contract.py`` does not declare a ``klass``; the model resolves it from
:data:`PACKAGE_LAYER` (a declared ``klass`` is accepted only for packages not
yet in the map — synthetic/test packages — and must agree with the map when
both exist).

The five layers:

- ``meta``       (L0) — this package: the template every package follows
  (``PackageContract``) + the global governance gates. Its ``extension``
  inverts the dependency at tool-time (CI scans every contract); nothing at
  runtime imports upward.
- ``infra``      (L1) — business-agnostic foundations: config, audit,
  authority, observability, testing, coverage, governance, runtime, llm,
  platform (the event-bus ports). L1 does not know what money is.
- ``middleware`` (L2) — the shared domain kernel: the value language
  (money/ratio/quantity/unit_price) and generic capabilities (counter).
- ``domain``     (L3) — vertical business slices: ledger, identity,
  extraction, reconciliation.
- ``app``        (L4) — the deliverables: apps/backend, apps/frontend.

Imports point down only. Where a lower layer must *know about* a higher one,
the edge is inverted through one of exactly two legal forms: a port in the
lower layer's ``base`` with the adapter registered from above (import-time),
or a declaration in the upper package's contract scanned by the lower
package's ``extension`` at tool-time (never a runtime import).

**stdlib-only by design** (``typing`` only): importable by the lightweight CI
lint env (``uv run --with pyyaml …``) exactly like its sibling
:mod:`common.meta.base.authority_matrix`.
"""

from __future__ import annotations

from typing import Literal, get_args

#: A package's layer in the five-layer topology, L0 → L4.
PackageClass = Literal["meta", "infra", "middleware", "domain", "app"]

#: Layer -> rank. The DAG rule is "never up, never sideways-cyclic": a package
#: may never import a higher-ranked layer, and same-layer edges must be
#: declared in ``depends_on`` and stay acyclic.
LAYER_RANK: dict[str, int] = {
    layer: rank for rank, layer in enumerate(get_args(PackageClass))
}

#: The central placement map — package name -> layer. This is the topology's
#: single source of truth, ahead of contracts existing: shell directories that
#: have not shipped a ``contract.py`` yet are
#: placed here so their eventual contract needs no self-claim and cannot land
#: in the wrong layer. ``check_package_contract`` requires every discovered
#: package to resolve a layer from this map (or, for names not mapped, an
#: explicit ``klass`` that the map does not contradict).
PACKAGE_LAYER: dict[str, PackageClass] = {
    # L0 — the template + global governance.
    "meta": "meta",
    # L1 — business-agnostic foundations.
    "audit": "infra",
    "authority": "infra",
    "config": "infra",
    "coverage": "infra",
    "governance": "infra",
    "llm": "infra",
    "observability": "infra",
    "platform": "infra",
    "runtime": "infra",
    "testing": "infra",
    # L2 — the shared domain kernel (generic capabilities). The value language
    # (money/ratio/quantity/unit_price) folded into audit (#1419), so those
    # names are gone from the map — audit (L1) owns the financial base types.
    "counter": "middleware",
    # L3 — vertical business slices.
    "extraction": "domain",
    "identity": "domain",
    "ledger": "domain",
    "reconciliation": "domain",
    # L4 — the deliverables.
    "backend": "app",
    "frontend": "app",
}
