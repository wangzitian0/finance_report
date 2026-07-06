"""The ``portfolio`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__init__.__all__``
(``implementations["be"]`` = ``apps/backend/src/portfolio``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways-cyclic edge.

## What this package is (issue #1422, Stage 3 of umbrella #1416)

Investment position accounting: buy/sell/dividend transactions posted through
``ledger.post_entry``, ``ManagedPosition``/``InvestmentLot`` bookkeeping
(cost-basis method, FIFO/LIFO/AVGCOST lot consumption), and the read-side
holdings/P&L/allocation/performance queries built on top.

**Positions-only boundary** (2026-07-06, updated after the pricing design
review #1610): portfolio owns only position math — quantity, cost basis,
realized/unrealized P&L. It never fetches or stores a price or a valuation;
it *consumes* one via ``pricing.resolve(subject, as_of, policy)``. The old
``MarketDataOverride`` write path (``PortfolioService.update_market_prices``)
belongs to ``pricing.record_override`` now, not here — see the P3 unit note
below for how that overlap is resolved.

## Ownership boundaries

* **``ManagedPosition`` is portfolio's aggregate**: it owns ``InvestmentLot``
  and ``InvestmentTransaction``; the invariant is *open position quantity ≥ 0*
  plus cost-basis consistency across lots.
* The ORM entities (``ManagedPosition``/``InvestmentLot``/
  ``InvestmentTransaction``/``DividendIncome``/``AtomicPosition``) stay in the
  unregistered ``src/models/`` until their cross-domain FKs are cut (Stage-4
  scope — same deferral extraction and ledger already made). Their enums
  (``PositionStatus``/``CostBasisMethod``/``InvestmentTransactionType``/
  ``DividendType``) are declared alongside them on the ORM model files, so
  they're taxonomy-only here too, for the same reason.
* Cross-package edges: ``audit`` (Money/Quantity/UnitPrice base types),
  ``ledger`` (``post_entry`` — portfolio writes only its own aggregate in one
  transaction, then posts a balanced ``Entry``; no shared transaction),
  ``pricing`` (price/FX resolution — portfolio never looks up a rate itself).
  Both ``ledger`` and ``pricing`` are L3 domain siblings; the edge is
  acyclic and sideways (``portfolio → ledger``, ``portfolio → pricing``,
  never the reverse).
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="portfolio",
    # klass is not declared here — it resolves from PACKAGE_LAYER (L0 owns
    # placement in the five-layer topology, #1595); see
    # common/meta/base/layering.py, which already lists portfolio as
    # "domain" (L3).
    status="draft",
    tier=None,
    depends_on=["audit", "ledger", "pricing", "platform", "observability", "config"],
    roles=["base", "extension", "data"],
    units=[
        # ── base: real value objects — plain exceptions, no ORM references ──
        Unit(name="PortfolioError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        Unit(name="PortfolioNotFoundError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        Unit(name="InvalidDateRangeError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        Unit(name="AssetNotFoundError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        Unit(name="InvestmentAccountingError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        Unit(
            name="InvestmentAccountingValidationError",
            kind=Kind.VALUE_OBJECT,
            module="base/errors.py",
        ),
        # ── base (taxonomy-only): the ORM aggregate/entities, unregistered ──
        # in src/models/ until Stage-4 cross-domain FK surgery (extraction/
        # ledger precedent). No module= — the gate skips placement checks
        # for these, same as extraction's AtomicTransaction/UploadedDocument.
        Unit(name="ManagedPosition", kind=Kind.AGGREGATE_ROOT),
        Unit(name="InvestmentLot", kind=Kind.ENTITY),
        Unit(name="InvestmentTransaction", kind=Kind.ENTITY),
        Unit(name="DividendIncome", kind=Kind.ENTITY),
        Unit(name="AtomicPosition", kind=Kind.ENTITY),
        # ── base (taxonomy-only): enums declared alongside the ORM models above ──
        Unit(name="PositionStatus", kind=Kind.VALUE_OBJECT),
        Unit(name="CostBasisMethod", kind=Kind.VALUE_OBJECT),
        Unit(name="InvestmentTransactionType", kind=Kind.VALUE_OBJECT),
        Unit(name="DividendType", kind=Kind.VALUE_OBJECT),
        # ── extension (reserved — P2): the write-side accounting service ──
        # post_buy/post_sell/post_dividend compose ledger.post_entry;
        # InvestmentAccountingResult holds ORM references (InvestmentTransaction/
        # JournalEntry/ManagedPosition) so it lives here, not base/ (the
        # base-layer-pure invariant forbids ORM types in base/).
        Unit(name="InvestmentAccountingResult", kind=Kind.DOMAIN_SERVICE),
        Unit(name="post_buy", kind=Kind.DOMAIN_SERVICE),
        Unit(name="post_sell", kind=Kind.DOMAIN_SERVICE),
        Unit(name="post_dividend", kind=Kind.DOMAIN_SERVICE),
        # ── extension (reserved — P3): the read-side holdings/P&L queries ──
        # + the repository port/adapter split the issue's DoD calls for
        # (currently raw AsyncSession in services/portfolio.py).
        Unit(name="PortfolioRepository", kind=Kind.REPOSITORY),
        Unit(name="get_holdings", kind=Kind.DOMAIN_SERVICE),
        Unit(name="get_portfolio_summary", kind=Kind.DOMAIN_SERVICE),
        Unit(name="calculate_unrealized_pnl", kind=Kind.DOMAIN_SERVICE),
        Unit(name="calculate_realized_pnl", kind=Kind.DOMAIN_SERVICE),
        # ── extension (reserved — P4): allocation + performance + report assembly ──
        Unit(name="get_sector_allocation", kind=Kind.DOMAIN_SERVICE),
        Unit(name="get_geography_allocation", kind=Kind.DOMAIN_SERVICE),
        Unit(name="get_asset_class_allocation", kind=Kind.DOMAIN_SERVICE),
        Unit(name="calculate_xirr", kind=Kind.DOMAIN_SERVICE),
        Unit(name="calculate_time_weighted_return", kind=Kind.DOMAIN_SERVICE),
        Unit(name="calculate_money_weighted_return", kind=Kind.DOMAIN_SERVICE),
        Unit(name="calculate_dividend_yield", kind=Kind.DOMAIN_SERVICE),
        # ── data (reserved — P4): read-models consumed by routers/reporting ──
        Unit(name="HoldingResponse", kind=Kind.PROJECTION),
        Unit(name="RealizedPnLResponse", kind=Kind.PROJECTION),
        Unit(name="UnrealizedPnLResponse", kind=Kind.PROJECTION),
        Unit(name="PortfolioSummaryResponse", kind=Kind.PROJECTION),
    ],
    implementations={"be": "apps/backend/src/portfolio", "fe": None},
    # This commit's real, working surface: the 6 plain-exception error types.
    # Everything else above is reserved (taxonomy-only or no module=) until a
    # later commit moves the real implementation in — same incremental
    # pattern the pricing cutover (#1610, PR #1617) used.
    interface=[
        "AssetNotFoundError",
        "InvalidDateRangeError",
        "InvestmentAccountingError",
        "InvestmentAccountingValidationError",
        "PortfolioError",
        "PortfolioNotFoundError",
    ],
    events=[],
    invariants=[
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_portfolio_package.py"
                "::test_AC_portfolio_1_1_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="converges-by-layer",
            statement="The package converges into base/ (pure) + extension/ (edges) + data/ (projections).",
            test=(
                "tests/tooling/test_portfolio_package.py"
                "::test_AC_portfolio_1_2_converges_by_layer"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement="base/ never imports the package's own extension/ or data/, the ORM, or any network client.",
            test=(
                "tests/tooling/test_portfolio_package.py"
                "::test_AC_portfolio_1_3_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates portfolio with no violations.",
            test=(
                "tests/tooling/test_portfolio_package.py"
                "::test_AC_portfolio_1_4_package_contract_gate_passes"
            ),
        ),
    ],
    # Filled by the EPIC-011/017 portfolio-AC migration (a later commit in
    # PR1); the package goes status="active" with its authority tier decided
    # there, per this repo's established precedent (migrate ownership only
    # after the physical fold is complete — see #1548/AC-audit.* migration).
    roadmap=[],
)
