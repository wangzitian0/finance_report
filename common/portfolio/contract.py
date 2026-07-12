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
* Cross-package edges today (updated at the #1641/#1643 read-side cutover):
  ``audit`` (Money/Quantity/UnitPrice base types), ``ledger`` (``post_entry``
  — portfolio writes only its own aggregate in one transaction, then posts a
  balanced ``Entry``; no shared transaction), ``observability`` (logging),
  and ``pricing`` (the published FX surface ``convert_amount``/``convert_money``
  with the ``lazy_load`` crawler fallback, plus ``StockPrice``/
  ``MARKET_DATA_QUANTITY_UNIT`` — portfolio consumes prices, never fetches or
  stores one). ``platform`` (event publish) is still intent, not code — add it
  to ``depends_on`` with its first real import, not before (a
  declared-but-unused edge fails ``check_package_contract`` as of #1674).
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="portfolio",
    # klass is not declared here — it resolves from PACKAGE_LAYER (L0 owns
    # placement in the five-layer topology, #1595); see
    # common/meta/base/layering.py, which already lists portfolio as
    # "domain" (L3).
    status="active",
    tier="CODE-ONLY",
    depends_on=["audit", "ledger", "observability", "pricing"],
    roles=["base", "extension", "data"],
    units=[
        # ── base: real value objects — plain exceptions, no ORM references ──
        Unit(name="PortfolioError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        Unit(
            name="PortfolioNotFoundError",
            kind=Kind.VALUE_OBJECT,
            module="base/errors.py",
        ),
        Unit(
            name="InvalidDateRangeError",
            kind=Kind.VALUE_OBJECT,
            module="base/errors.py",
        ),
        Unit(
            name="AssetNotFoundError", kind=Kind.VALUE_OBJECT, module="base/errors.py"
        ),
        Unit(
            name="InvestmentAccountingError",
            kind=Kind.VALUE_OBJECT,
            module="base/errors.py",
        ),
        Unit(
            name="InvestmentAccountingValidationError",
            kind=Kind.VALUE_OBJECT,
            module="base/errors.py",
        ),
        # ── taxonomy-only ORM units (no module= — the gate skips placement
        # checks, same as extraction's AtomicTransaction/UploadedDocument).
        # InvestmentTransaction/InvestmentLot/DividendIncome + their enums now
        # live in orm/portfolio.py (#1675 D5): cross-domain references
        # (managed_positions, journal_entries) are bare FK columns; the former
        # relationship() navigations were unused and removed per the
        # 2026-07-11 ruling. ManagedPosition/AtomicPosition/PositionStatus/
        # CostBasisMethod still live in the unregistered src/models/ remainder
        # (layer3.py — extraction-bound, the parallel D4+D5c PR).
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
        # ── extension: the write-side accounting service ──
        # post_buy/post_sell/post_dividend (methods, not separate units)
        # compose ledger.post_entry. InvestmentAccountingResult holds ORM
        # references (InvestmentTransaction/JournalEntry/ManagedPosition) —
        # taxonomy-only (no module=) for the same reason those entities are:
        # the base-layer-pure invariant forbids ORM types in base/, and these
        # ORM types are themselves deferred to Stage-4.
        Unit(name="InvestmentAccountingResult", kind=Kind.VALUE_OBJECT),
        Unit(
            name="InvestmentAccountingService",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/accounting.py",
        ),
        # ── extension (real — #1643): the read-side holdings/P&L query service ──
        # get_holdings/get_portfolio_summary/calculate_realized_pnl/
        # calculate_unrealized_pnl/update_market_prices are methods on
        # PortfolioService (methods, not separate units — the accounting
        # precedent above). The repository port/adapter split the issue's DoD
        # calls for is still ahead (raw AsyncSession today), so
        # PortfolioRepository stays reserved.
        Unit(name="PortfolioRepository", kind=Kind.REPOSITORY),
        Unit(
            name="PortfolioService",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/holdings.py",
        ),
        # ── extension (real — #1643): allocation + performance + report assembly ──
        Unit(
            name="get_sector_allocation",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/allocation.py",
        ),
        Unit(
            name="get_geography_allocation",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/allocation.py",
        ),
        Unit(
            name="get_asset_class_allocation",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/allocation.py",
        ),
        Unit(
            name="calculate_xirr",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/performance.py",
        ),
        Unit(
            name="calculate_time_weighted_return",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/performance.py",
        ),
        Unit(
            name="calculate_money_weighted_return",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/performance.py",
        ),
        Unit(
            name="calculate_dividend_yield",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/performance.py",
        ),
        Unit(
            name="build_investment_performance_report_schedule",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/performance_report.py",
        ),
        # ── extension (real — #1641): market-data scope discovery reads ──
        # "what does this user hold" — composed by the delivery layer into the
        # scopes passed to pricing's crawl (call-convention inversion).
        Unit(
            name="active_stock_symbols",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/discovery.py",
        ),
        Unit(
            name="position_currencies",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/discovery.py",
        ),
        # ── data (reserved): read-models consumed by routers/reporting — the
        # response schemas still live in the unregistered src/schemas/. ──
        Unit(name="HoldingResponse", kind=Kind.PROJECTION),
        Unit(name="RealizedPnLResponse", kind=Kind.PROJECTION),
        Unit(name="UnrealizedPnLResponse", kind=Kind.PROJECTION),
        Unit(name="PortfolioSummaryResponse", kind=Kind.PROJECTION),
    ],
    implementations={"be": "apps/backend/src/portfolio", "fe": None},
    # The real, working surface: the plain-exception error families (base/),
    # the write-side accounting + position services, the read-side holdings/
    # P&L/allocation/performance queries and the report-schedule assembly
    # (#1643), and the scope-discovery reads (#1641).
    interface=[
        "AssetNotFoundError",
        "DepreciationResult",
        "DividendIncome",
        "DividendType",
        "InsufficientDataError",
        "InvalidDateRangeError",
        "InvestmentAccountingError",
        "InvestmentAccountingResult",
        "InvestmentAccountingService",
        "InvestmentAccountingValidationError",
        "InvestmentLot",
        "InvestmentTransaction",
        "InvestmentTransactionType",
        "PerformanceError",
        "PortfolioError",
        "PortfolioNotFoundError",
        "PortfolioService",
        "PositionService",
        "PositionServiceError",
        "ReconcileResult",
        "XIRRCalculationError",
        "active_stock_symbols",
        "build_investment_performance_report_schedule",
        "calculate_dividend_yield",
        "calculate_money_weighted_return",
        "calculate_time_weighted_return",
        "calculate_xirr",
        "get_asset_class_allocation",
        "get_geography_allocation",
        "get_sector_allocation",
        "portfolio_service",
        "position_currencies",
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
    # The write-side accounting slice is real, tested, and CODE-ONLY (money/
    # ledger postings, no LLM), so the package ships active with that tier
    # decided now; the read-side holdings/P&L cutover landed with #1643 (real
    # units above). The EPIC-011/017 read-side AC rows migrate into this
    # roadmap separately (#1717).
    roadmap=[
        ACRecord(
            id="AC-portfolio.1.1",
            statement=(
                "post_buy posts a balanced ledger entry, creates the opening "
                "InvestmentLot, and increases the ManagedPosition cost basis and quantity."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_buy_transaction_creates_balanced_journal_entry_and_lot"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.2.1",
            statement=(
                "post_sell consumes InvestmentLots by the configured FIFO cost-basis "
                "method and never sells more than the remaining quantity."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_sell_transaction_uses_fifo_and_records_realized_gain"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.2.2",
            statement=(
                "post_sell supports average-cost disposal and persists the AVGCOST "
                "method on the realized transaction and remaining position."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_sell_transaction_uses_average_cost_for_realized_pnl"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.3.1",
            statement=(
                "A sell updates ManagedPosition quantity and disposal status without "
                "ever driving an open position quantity below zero."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_sell_transaction_uses_lifo_loss_and_disposes_position"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.4.1",
            statement=(
                "post_dividend posts cash plus dividend income and persists a "
                "DividendIncome record for the position."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_dividend_transaction_posts_income_and_dividend_record"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.4.2",
            statement=(
                "post_dividend splits withholding tax into separate cash and tax "
                "expense legs while keeping the ledger entry balanced."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_dividend_transaction_posts_withholding_tax"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.1.2",
            statement=(
                "Investment accounting rejects invalid buy, sell, and dividend "
                "inputs before writing portfolio or ledger state."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_investment_accounting_rejects_invalid_transactions"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.1.3",
            statement=(
                "Investment accounting helper lookups reject missing positions and "
                "inactive or wrong-type accounts with clean domain errors."
            ),
            test=(
                "apps/backend/tests/portfolio/test_investment_accounting.py"
                "::test_investment_accounting_rejects_invalid_account_and_position_helpers"
            ),
            priority="P1",
            status="done",
        ),
        # ── group reconcile: AtomicPosition -> ManagedPosition reconciliation
        # (migrated from EPIC-011 AC11.1.1-12, migration closeout continuation, #1663) ──
        ACRecord(
            id="AC-portfolio.reconcile.1",
            statement="Reconcile creates a new ManagedPosition from an AtomicPosition snapshot.",
            test="apps/backend/tests/assets/test_asset_service.py::test_reconcile_creates_position",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.2",
            statement="Reconcile updates an existing position's quantity from the latest snapshot.",
            test="apps/backend/tests/assets/test_asset_service.py::test_reconcile_updates_position",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.3",
            statement="Reconcile disposes a position when the latest snapshot quantity is 0.",
            test="apps/backend/tests/assets/test_asset_service.py::test_reconcile_disposes_position",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.4",
            statement="Reconcile sets cost basis from the snapshot's market_value.",
            test="apps/backend/tests/assets/test_asset_service.py::test_reconcile_cost_basis_uses_market_value",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.5",
            statement="Reconcile handles multiple different assets in one run.",
            test="apps/backend/tests/assets/test_asset_service.py::test_reconcile_multiple_assets",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.6",
            statement="The same asset at different brokers reconciles into separate positions.",
            test=(
                "apps/backend/tests/assets/test_asset_service.py"
                "::test_reconcile_multiple_brokers_same_asset"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.7",
            statement="A null/missing broker name falls back to 'Unknown Broker' instead of failing.",
            test="apps/backend/tests/assets/test_asset_service.py::test_reconcile_with_null_broker",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.8",
            statement="A disposed position reactivates to ACTIVE when it reappears in a later snapshot.",
            test=(
                "apps/backend/tests/assets/test_asset_service.py"
                "::test_reconcile_reactivates_disposed_position"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.9",
            statement="Listing positions returns an empty list when none exist, not an error.",
            test="apps/backend/tests/assets/test_asset_service.py::test_get_positions_empty",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.10",
            statement="Reconcile with no atomic snapshots is a no-op (no positions created/changed).",
            test="apps/backend/tests/assets/test_asset_service.py::test_reconcile_no_snapshots",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.11",
            statement="Negative quantities (short positions) reconcile correctly, not as an error.",
            test=(
                "apps/backend/tests/assets/test_asset_service.py"
                "::test_reconcile_negative_quantity_short_position"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.reconcile.12",
            statement="A single reconcile run's updated and disposed position counts are mutually exclusive.",
            test=(
                "apps/backend/tests/assets/test_asset_service.py"
                "::test_reconcile_result_counts_are_mutually_exclusive"
            ),
            priority="P0",
            status="done",
        ),
        # ── group router: positions/reconcile/depreciation HTTP surface
        # (migrated from EPIC-011 AC11.2/.3/.4/.5/.7, migration closeout continuation, #1663) ──
        ACRecord(
            id="AC-portfolio.router.1",
            statement="GET /assets/positions returns an empty list when the user has no positions.",
            test="apps/backend/tests/assets/test_assets_router.py::test_list_positions_empty",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.2",
            statement="GET /assets/positions returns the user's positions with data.",
            test="apps/backend/tests/assets/test_assets_router.py::test_list_positions_with_data",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.3",
            statement="GET /assets/positions filters correctly by status.",
            test="apps/backend/tests/assets/test_assets_router.py::test_list_positions_filter_by_status",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.4",
            statement="GET /assets/positions/{id} returns the position's details.",
            test="apps/backend/tests/assets/test_assets_router.py::test_get_position_success",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.5",
            statement="GET /assets/positions/{id} returns 404 for a non-existent position.",
            test="apps/backend/tests/assets/test_assets_router.py::test_get_position_not_found",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.6",
            statement="GET /assets/positions/{id} returns 404 for another user's position.",
            test="apps/backend/tests/assets/test_assets_router.py::test_get_position_wrong_user",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.7",
            statement="POST /assets/reconcile creates positions from the latest atomic snapshots.",
            test="apps/backend/tests/assets/test_assets_router.py::test_reconcile_positions_success",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.8",
            statement="POST /assets/reconcile with no snapshots returns zero created/updated/disposed counts.",
            test="apps/backend/tests/assets/test_assets_router.py::test_reconcile_positions_empty",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.9",
            statement="GET /assets/positions requires authentication.",
            test="apps/backend/tests/assets/test_assets_router.py::test_list_positions_requires_auth",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.10",
            statement="GET /assets/positions/{id} requires authentication.",
            test="apps/backend/tests/assets/test_assets_router.py::test_get_position_requires_auth",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.11",
            statement="POST /assets/reconcile requires authentication.",
            test="apps/backend/tests/assets/test_assets_router.py::test_reconcile_requires_auth",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.router.12",
            statement="Position queries are isolated by user_id — one user never sees another's positions.",
            test="apps/backend/tests/assets/test_assets_router.py::test_get_position_user_isolation",
            priority="P0",
            status="done",
        ),
        # ── group depreciation: depreciation-schedule HTTP surface
        # (migrated from EPIC-011 AC11.6, migration closeout continuation, #1663) ──
        ACRecord(
            id="AC-portfolio.depreciation.1",
            statement="GET /assets/positions/{id}/depreciation returns the depreciation schedule.",
            test=(
                "apps/backend/tests/assets/test_assets_router.py"
                "::test_get_position_depreciation_success"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.depreciation.2",
            statement="GET /assets/positions/{id}/depreciation returns 400 for a non-existent position.",
            test=(
                "apps/backend/tests/assets/test_assets_router.py"
                "::test_get_position_depreciation_not_found"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.depreciation.3",
            statement="GET /assets/positions/{id}/depreciation returns 400 for a disposed position.",
            test=(
                "apps/backend/tests/assets/test_assets_router.py"
                "::test_get_position_depreciation_disposed_position"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.depreciation.4",
            statement="GET /assets/positions/{id}/depreciation returns 422 for invalid method/parameters.",
            test=(
                "apps/backend/tests/assets/test_assets_router.py"
                "::test_get_position_depreciation_invalid_params"
            ),
            priority="P1",
            status="done",
        ),
        # ── group holdings: holdings summary + portfolio summary reads (was
        # EPIC-017 AC17.1.1, AC17.1.5 and AC17.1.7-9, migration closeout
        # continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.holdings.1",
            statement=(
                "get_holdings returns the holdings summary (ticker, quantity, cost basis, "
                "market value) for active positions."
            ),
            # was AC17.1.1
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_get_holdings_happy_path"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.holdings.2",
            statement="Unrealized P&L is calculated from cost basis and current market value.",
            # was AC17.1.5
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_unrealized_pnl_happy_path"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.holdings.3",
            statement="The portfolio summary happy path returns correct counts and totals.",
            # was AC17.1.7
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_portfolio_summary_happy"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.holdings.4",
            statement="The portfolio summary includes both active and disposed positions.",
            # was AC17.1.8
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_portfolio_summary_with_disposed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.holdings.5",
            statement="A zero total cost yields net_pnl_percent = 0 instead of a division error.",
            # was AC17.1.9
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_portfolio_summary_zero_cost"
            ),
            priority="P1",
            status="done",
        ),
        # ── group performance: XIRR/TWR/MWR + realized/unrealized P&L math
        # (was EPIC-017 AC17.2.1-5 and AC17.2.7-9; AC17.2.6 deduped into
        # AC-portfolio.holdings.2 — same test, same fact; migration closeout
        # continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.performance.1",
            statement=(
                "XIRR over realistic data is accurate (within 0.01% of the Excel XIRR "
                "reference)."
            ),
            # was AC17.2.1
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_xirr_with_realistic_data"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.performance.2",
            statement="Time-weighted return is computed correctly for a period.",
            # was AC17.2.2
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_time_weighted_return_with_period"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.performance.3",
            statement="Money-weighted return is computed from dated cash flows.",
            # was AC17.2.3
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_money_weighted_return_with_data"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.performance.4",
            statement=(
                "A zero cost basis yields realized_pnl_percent = 0 instead of a division error."
            ),
            # was AC17.2.4
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_realized_pnl_zero_cost"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.performance.5",
            statement=(
                "A disposed position in a non-base currency triggers FX conversion for realized "
                "P&L."
            ),
            # was AC17.2.5
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_realized_pnl_fx_conversion"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.performance.6",
            statement="Unrealized P&L on an empty portfolio raises PortfolioNotFoundError.",
            # was AC17.2.7
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_unrealized_pnl_no_positions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.performance.7",
            statement=(
                "A zero cost basis yields unrealized_pnl_percent = 0 in per-position details."
            ),
            # was AC17.2.8
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_unrealized_pnl_zero_cost"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.performance.8",
            statement="Unrealized P&L converts non-base-currency positions via FX.",
            # was AC17.2.9
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_unrealized_pnl_fx_conversion"
            ),
            priority="P1",
            status="done",
        ),
        # ── group allocation: allocation breakdowns + performance edge cases
        # (was EPIC-017 AC17.3.1-3, AC17.3.5 and AC17.3.7-14; AC17.3.4/.6
        # deduped into AC-portfolio.performance.2/.3 — same tests, same facts;
        # migration closeout continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.allocation.1",
            statement="Sector allocation breaks holdings down by sector.",
            # was AC17.3.1
            test=(
                "apps/backend/tests/portfolio/test_allocation_service.py"
                "::test_sector_allocation_with_positions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.2",
            statement="Geography allocation breaks holdings down by geography.",
            # was AC17.3.2
            test=(
                "apps/backend/tests/portfolio/test_allocation_service.py"
                "::test_geography_allocation_with_positions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.3",
            statement="Asset-class allocation breaks holdings down by asset class.",
            # was AC17.3.3
            test=(
                "apps/backend/tests/portfolio/test_allocation_service.py"
                "::test_asset_class_allocation_with_positions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.4",
            statement="MWR raises InsufficientDataError on an empty portfolio.",
            # was AC17.3.5
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_money_weighted_return_insufficient_data"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.5",
            statement="XIRR respects the as_of_date parameter.",
            # was AC17.3.7
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_xirr_with_as_of_date"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.6",
            statement="TWR returns zero for a same-day period.",
            # was AC17.3.8
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_time_weighted_return_same_day"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.7",
            statement="Performance metrics handle cash-only portfolios without positions.",
            # was AC17.3.9
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_performance_metrics_with_zero_positions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.8",
            statement="XIRR handles extreme convergence edge cases.",
            # was AC17.3.10
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_xirr_convergence_edge_case"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.9",
            statement="_xirr_bisection raises ValueError when no root exists.",
            # was AC17.3.11
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_xirr_bisection_no_root_raises"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.10",
            statement="_xirr_bisection returns a Decimal estimate after max_iter exhaustion.",
            # was AC17.3.12
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_xirr_bisection_max_iter_returns"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.11",
            statement="_xirr_newton falls back to bisection on non-convergence.",
            # was AC17.3.13
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_xirr_newton_fallthrough_to_bisection"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.allocation.12",
            statement="XIRRCalculationError is raised when Newton and bisection both fail.",
            # was AC17.3.14
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_xirr_calculation_error_raised"
            ),
            priority="P1",
            status="done",
        ),
        # ── group valuation: position valuation reads + balance-sheet flow
        # (was EPIC-017 AC17.5.4-8, migration closeout continuation,
        # #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.valuation.1",
            statement=(
                "Unrealized P&L flows into the balance sheet: an imported statement's holdings "
                "change balance-sheet value."
            ),
            # was AC17.5.4
            test=(
                "apps/backend/tests/portfolio/test_brokerage_position_parsing.py"
                "::test_statement_import_flows_to_holdings_and_balance_sheet"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.valuation.2",
            statement=(
                "A zero-quantity position returns its market_value directly instead of deriving "
                "a unit price."
            ),
            # was AC17.5.5
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_get_latest_price_zero_quantity"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.valuation.3",
            statement="Missing price data raises AssetNotFoundError.",
            # was AC17.5.6
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_get_latest_price_no_data"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.valuation.4",
            statement="_get_latest_atomic returns the most recent snapshot.",
            # was AC17.5.7
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_get_latest_atomic_returns_latest"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.valuation.5",
            statement="_get_latest_atomic returns None when no snapshots exist.",
            # was AC17.5.8
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_get_latest_atomic_none"
            ),
            priority="P1",
            status="done",
        ),
        # ── group api: portfolio HTTP surface (was EPIC-017 AC17.6.3-21,
        # migration closeout continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.api.1",
            statement="GET /portfolio/holdings with an as_of_date filter returns 200.",
            # was AC17.6.3
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_holdings_with_date_filter"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.2",
            statement="GET /portfolio/holdings with include_disposed=true returns 200.",
            # was AC17.6.4
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_holdings_include_disposed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.3",
            statement="GET /portfolio/performance without a period returns metrics.",
            # was AC17.6.5
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_performance_without_period"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.4",
            statement="GET /portfolio/performance with period params returns metrics.",
            # was AC17.6.6
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_performance_with_period"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.5",
            statement="GET /portfolio/allocation/sector on an empty portfolio returns [].",
            # was AC17.6.7
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_sector_allocation_empty"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.6",
            statement="GET /portfolio/allocation/sector with data returns the breakdown.",
            # was AC17.6.8
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_sector_allocation_with_data"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.7",
            statement="GET /portfolio/allocation/geography on an empty portfolio returns [].",
            # was AC17.6.9
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_geography_allocation_empty"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.8",
            statement="GET /portfolio/allocation/geography with data returns the breakdown.",
            # was AC17.6.10
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_geography_allocation_with_data"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.9",
            statement="GET /portfolio/allocation/asset-class on an empty portfolio returns [].",
            # was AC17.6.11
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_asset_class_allocation_empty"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.10",
            statement="GET /portfolio/allocation/asset-class with data returns the breakdown.",
            # was AC17.6.12
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_asset_class_allocation_with_data"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.11",
            statement="POST /portfolio/prices/update with a single asset returns success.",
            # was AC17.6.13
            test="apps/backend/tests/portfolio/test_portfolio_router.py::test_update_prices_single",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.12",
            statement="POST /portfolio/prices/update with a batch returns success.",
            # was AC17.6.14
            test="apps/backend/tests/portfolio/test_portfolio_router.py::test_update_prices_batch",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.13",
            statement="POST /portfolio/prices/update with an invalid payload returns 422.",
            # was AC17.6.15
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_update_prices_invalid_payload"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.14",
            statement="All portfolio endpoints require authentication.",
            # was AC17.6.16
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_portfolio_endpoints_require_auth"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.15",
            statement="GET /portfolio/allocation/sector with as_of_date returns 200.",
            # was AC17.6.17
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_allocation_with_as_of_date"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.16",
            statement="GET /portfolio/performance returns string-formatted metrics.",
            # was AC17.6.18
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_performance_metrics_response_format"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.17",
            statement="InsufficientDataError on an empty portfolio defaults xirr/mwr to 0.",
            # was AC17.6.19
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_performance_insufficient_data"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.18",
            statement="A non-InsufficientData PerformanceError on XIRR returns 422.",
            # was AC17.6.20
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_performance_xirr_calculation_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.api.19",
            statement="A non-InsufficientData PerformanceError on MWR returns 422.",
            # was AC17.6.21
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_performance_mwr_calculation_error"
            ),
            priority="P1",
            status="done",
        ),
        # ── group as-of: point-in-time holdings snapshots (was EPIC-017
        # AC17.9.1-2 — the frontend selector row AC17.9.3 stays in EPIC-017;
        # migration closeout continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.as-of.1",
            statement=(
                "Historical holdings quantity and market value come from the latest "
                "AtomicPosition snapshot at or before as_of_date."
            ),
            # was AC17.9.1
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_get_holdings_explicit_as_of_uses_historical_atomic_snapshot"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.as-of.2",
            statement=(
                "The holdings API returns date-bounded snapshot quantities for explicit "
                "as_of_date requests."
            ),
            # was AC17.9.2
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_get_holdings_explicit_date_uses_historical_snapshot_quantity"
            ),
            priority="P0",
            status="done",
        ),
        # ── group report-schedule: investment performance report schedule API
        # (was EPIC-017 AC17.10.1-6, migration closeout continuation,
        # #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.report-schedule.1",
            statement=(
                "The investment performance schedule API exposes report-ready metrics and "
                "per-holding/allocation rows."
            ),
            # was AC17.10.1
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.report-schedule.2",
            statement=(
                "The schedule API exposes data freshness, source links, and notes for report "
                "traceability."
            ),
            # was AC17.10.2
            test=(
                "tests/tooling/test_investment_performance_report_contract.py"
                "::test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.report-schedule.3",
            statement=(
                "Schedule source links preserve brokerage statement, price source, ledger, "
                "transaction source, and report-section anchors."
            ),
            # was AC17.10.3
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.report-schedule.4",
            statement=(
                "Schedule data freshness marks the schedule stale when any holding lacks "
                "current as-of-date price evidence."
            ),
            # was AC17.10.4
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_10_4_report_schedule_marks_stale_when_any_holding_price_is_stale"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.report-schedule.5",
            statement="The XIRR solver never converts monetary Decimal cash flows to float.",
            # was AC17.10.5
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_AC17_10_5_xirr_solver_does_not_float_monetary_cashflows"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.report-schedule.6",
            statement=(
                "The schedule converts mixed-currency cost basis, market value, realized P&L, "
                "and dividend income into the presentation currency before aggregation."
            ),
            # was AC17.10.6
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_10_6_investment_performance_schedule_converts_mixed_currency_amounts"
            ),
            priority="P0",
            status="done",
        ),
        # ── group logic-audit: portfolio financial logic audit fixes (was
        # EPIC-017 AC17.11.1-4, migration closeout continuation,
        # #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.logic-audit.1",
            statement=(
                "XIRR and MWR use investment transactions only, excluding unrelated bank atomic "
                "transactions."
            ),
            # was AC17.11.1
            test=(
                "apps/backend/tests/portfolio/test_financial_logic_audit.py"
                "::test_AC17_11_1_xirr_excludes_unrelated_bank_transactions"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.logic-audit.2",
            statement=(
                "Summary YTD realized P&L and dividend income convert to the presentation "
                "currency before aggregation."
            ),
            # was AC17.11.2
            test=(
                "apps/backend/tests/portfolio/test_financial_logic_audit.py"
                "::test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.logic-audit.3",
            statement=(
                "TWR excludes unrelated bank atomic transactions from the period cash-flow "
                "adjustment."
            ),
            # was AC17.11.3
            test=(
                "apps/backend/tests/portfolio/test_financial_logic_audit.py"
                "::test_AC17_11_3_twr_excludes_unrelated_bank_transactions"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.logic-audit.4",
            statement="Non-structured source document payloads produce no audit links.",
            # was AC17.11.4
            test=(
                "apps/backend/tests/portfolio/test_financial_logic_audit.py"
                "::test_AC17_11_4_source_document_links_ignore_non_structured_payloads"
            ),
            priority="P0",
            status="done",
        ),
        # ── group fixtures: portfolio audit fixture contract (was EPIC-017
        # AC17.12.1-3, migration closeout continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.fixtures.1",
            statement=(
                "The portfolio audit fixture contract covers multi-broker, multi-currency "
                "expected positions and a report period containing every activity row."
            ),
            # was AC17.12.1
            test=(
                "tests/tooling/test_portfolio_audit_fixture_contract.py"
                "::test_AC17_12_1_portfolio_fixture_contract_covers_multi_broker_multi_currency_inputs"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.fixtures.2",
            statement=(
                "The fixture contract pins sanitized trade, dividend, fee, and valuation "
                "activity rows and derives expected totals from fixture rows and positions."
            ),
            # was AC17.12.2
            test=(
                "tests/tooling/test_portfolio_audit_fixture_contract.py"
                "::test_AC17_12_2_portfolio_fixture_pins_activity_rows_without_raw_documents"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.fixtures.3",
            statement=(
                "The personal report package fixture consumes the expanded portfolio expected "
                "outputs instead of inline one-position constants."
            ),
            # was AC17.12.3
            test=(
                "tests/tooling/test_portfolio_audit_fixture_contract.py"
                "::test_AC17_12_3_personal_package_references_expanded_portfolio_fixture_contract"
            ),
            priority="P0",
            status="done",
        ),
        # ── group fact-boundary: portfolio facts vs framework conclusions
        # (was EPIC-017 AC17.13.1, migration closeout continuation,
        # #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.fact-boundary.1",
            statement=(
                "Portfolio owns holdings, lots, dividends, fees, and source links and relays "
                "pricing facts as framework policy inputs; it does not own final US/HK report "
                "presentation decisions."
            ),
            # was AC17.13.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC17_13_1_portfolio_supplies_facts_not_framework_conclusions"
            ),
            priority="P0",
            status="done",
        ),
        # ── group pagination: list endpoint pagination bounds (was EPIC-017
        # AC17.30.1-6, migration closeout continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.pagination.1",
            statement="GET /portfolio/holdings caps results at the default limit when paginating.",
            # was AC17.30.1
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_30_1_holdings_default_cap_applied"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.pagination.2",
            statement="GET /portfolio/holdings honors limit and offset to page through holdings.",
            # was AC17.30.2
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_30_2_holdings_limit_offset_honored"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.pagination.3",
            statement="GET /portfolio/holdings rejects out-of-range limit/offset with 422.",
            # was AC17.30.3
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_30_3_holdings_rejects_out_of_range_pagination"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.pagination.4",
            statement=(
                "GET /portfolio/{ticker}/dividends honors limit/offset and rejects out-of-range "
                "values."
            ),
            # was AC17.30.4
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_30_4_dividends_limit_offset_honored"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.pagination.5",
            statement=(
                "GET /portfolio/{ticker}/realized honors limit/offset and rejects out-of-range "
                "values."
            ),
            # was AC17.30.5
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_30_5_realized_limit_offset_honored"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.pagination.6",
            statement=(
                "GET /portfolio/allocation/* honors limit/offset and rejects out-of-range "
                "values."
            ),
            # was AC17.30.6
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC17_30_6_allocation_limit_offset_honored"
            ),
            priority="P1",
            status="done",
        ),
        # ── group typed-responses: typed Pydantic router responses (was
        # EPIC-017 AC17.31.1-2, migration closeout continuation,
        # #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.typed-responses.1",
            statement=(
                "POST /portfolio/prices/update returns the typed {updated_count, results} "
                "shape."
            ),
            # was AC17.31.1
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC17_31_1_prices_update_returns_typed_batch_response"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.typed-responses.2",
            statement="PATCH /portfolio/{ticker} for an unknown holding returns a structured 404.",
            # was AC17.31.2
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC17_31_2_patch_unknown_holding_returns_404"
            ),
            priority="P2",
            status="done",
        ),
        # ── group metrics: portfolio-owned performance math that lived in the
        # reporting EPIC (was EPIC-005 AC5.6.1-3 and AC5.6.6, migration
        # closeout continuation, #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.metrics.1",
            statement="XIRR matches the single-year Excel XIRR reference case within 0.01%.",
            # was AC5.6.1
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_AC5_6_1_xirr_matches_single_year_excel_case"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.metrics.2",
            statement="Annualized time-weighted return matches the snapshot period reference.",
            # was AC5.6.2
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_AC5_6_2_time_weighted_return_matches_snapshot_period"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.metrics.3",
            statement="Dividend yield is trailing annual dividends over current value.",
            # was AC5.6.3
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_AC5_6_3_dividend_yield_uses_trailing_dividends_over_current_value"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.metrics.4",
            statement="Money-weighted return matches XIRR for a single cash flow.",
            # was AC5.6.6
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_AC5_6_6_money_weighted_return_matches_xirr_for_single_cashflow"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.metrics.5",
            statement=(
                "A position's contribution to XIRR/TWR/dividend-yield portfolio "
                "value as of a historical date is decided by whether it was held "
                "on that date (point-in-time, via its snapshot quantity), not by "
                "ManagedPosition.status which reflects today -- a position "
                "disposed after the requested date still counts."
            ),
            test=(
                "apps/backend/tests/portfolio/test_performance_service.py"
                "::test_AC5_6_3_dividend_yield_counts_position_disposed_after_as_of_date"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        # ── group schedule-fallback: mixed-currency schedule fallback (was
        # EPIC-019 AC19.8.8's portfolio share — the readiness-FX and Playwright
        # shares stay in EPIC-019; migration closeout continuation,
        # #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.schedule-fallback.1",
            statement=(
                "The mixed-currency investment schedule fallback converts holding cost basis "
                "into the schedule currency."
            ),
            # was AC19.8.8 (portfolio share)
            test=(
                "apps/backend/tests/portfolio/test_portfolio_router.py"
                "::test_AC19_8_8_investment_schedule_fallback_holding_cost_basis_converts_currency"
            ),
            priority="P0",
            status="done",
        ),
        # ── group provenance: conservative provenance labeling (was EPIC-022
        # AC22.10.1's backend half and AC22.13.1's portfolio share — the
        # frontend badge halves stay in EPIC-022; the pricing share is
        # AC-pricing.provenance.1 and the reporting share is
        # AC-reporting.provenance.1; migration closeout continuation,
        # #1663 / #1717) ──
        ACRecord(
            id="AC-portfolio.provenance.1",
            statement=(
                "A holding whose latest snapshot is backed by a source document is labeled "
                "imported; holdings without document evidence carry no provenance label."
            ),
            # was AC22.10.1 (backend half)
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_get_holdings_provenance_imported_with_source_document"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-portfolio.provenance.2",
            statement=(
                "Portfolio holdings and explicit as-of holdings expose the normalized "
                "provenance enum when the source basis is known, and stay unlabeled instead of "
                "guessing."
            ),
            # was AC22.13.1 (portfolio share)
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_AC22_13_1_explicit_as_of_holdings_preserve_snapshot_provenance"
            ),
            priority="P1",
            status="done",
        ),
    ],
)
