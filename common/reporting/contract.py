"""The ``reporting`` package's machine-checkable :class:`PackageContract` (draft scaffold).

Scaffold for the EPIC-026 Lane B (#1387) ``reporting`` band: the ``L1 -> report``
layer of the financial data flow
(``(extraction + portfolio) -> reconciliation -> ledger -> reporting -> advisor``).

Reporting is **deterministic aggregation of trusted L1 facts** into
framework-tagged statement lines — pure code, no model in the loop — so it is a
``CODE-ONLY`` ``core`` package. That tier is the whole point: it makes the
band's real proof obligation explicit (``exact`` aggregation), which is the
missing link #1397 calls out and #1353 owns.

``status="draft"``: this declares the bounded context (ubiquitous language,
authority tier, planned invariants) ahead of the code move. The conforming
implementation lives today at ``apps/backend/src/services/reporting``; it is
migrated into ``apps/backend/src/reporting`` (role-converged ``types/ops/store/api``)
in follow-up one-package PRs, at which point ``implementations["be"]``,
``interface``, ``invariants`` and ``roadmap`` are filled and ``status`` flips to
``active``. See ``readme.md`` for the language and ``todo.md`` for the worklist.
"""

from __future__ import annotations

from common.meta.package_contract import PackageContract

CONTRACT = PackageContract(
    name="reporting",
    klass="core",
    status="draft",
    # L1 -> report is pure arithmetic on trusted L1 facts; no LLM. Decided per
    # #1387 Lane B (every PC-wave band is CODE-ONLY). One package = one tier.
    tier="CODE-ONLY",
    # Down-only edges (core may import platform + kernel). Same-class core deps
    # (ledger, portfolio) are declared once those packages exist and reporting's
    # implementation is migrated.
    depends_on=["platform", "kernel"],
    roles=["types", "ops", "store", "api"],
    # Draft: no conforming implementation pointed-at yet (the gate skips the
    # interface==__all__ check while be is None). Code currently lives at
    # apps/backend/src/services/reporting and is migrated in a follow-up PR.
    implementations={"be": None, "fe": None},
    interface=[],
    events=[],
    invariants=[],
    roadmap=[],
)
