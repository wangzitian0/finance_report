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
* The ORM entities: ``InvestmentLot``/``InvestmentTransaction``/
  ``DividendIncome`` live in this package's own ``orm/portfolio.py``
  (#1675 D5); ``ManagedPosition``/``AtomicPosition`` live in ``extraction``'s
  ``orm/layer3.py`` (#1675 D4+D5c — extraction owns the fact family's ORM;
  portfolio imports the published entities, never the ORM class directly).
  Their enums (``PositionStatus``/``CostBasisMethod``/
  ``InvestmentTransactionType``/``DividendType``) are declared alongside them
  on the ORM model files, so they're taxonomy-only here too.
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
    ac,
    ContextRelation,
    ContextScope,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

# fmt: off
CONTRACT = PackageContract(
    name="portfolio",
    # klass is not declared here — it resolves from PACKAGE_LAYER (L0 owns
    # placement in the five-layer topology, #1595); see
    # common/meta/base/layering.py, which already lists portfolio as
    # "domain" (L3).
    status="active",
    tier="CODE-ONLY",
    # ``platform`` (#1675 D6): orm/portfolio.py's mapped classes use the base
    # ORM mixins (UUIDMixin/UserOwnedMixin/TimestampMixin), moved from
    # src/models/base.py to platform.orm.base — a downward edge (platform is
    # infra, L1; portfolio is domain, L3).
    depends_on=[
        "audit",
        "extraction",
        "ledger",
        "observability",
        "platform",
        "pricing",
    ],
    context=ContextScope(
        purpose="Own investment position accounting: lots, cost basis, position quantity, and realized or unrealized performance over accounting facts.",
        in_scope=[
            "ManagedPosition, investment lots, investment transactions, and dividend position math",
            "cost-basis selection, holdings, allocation, and portfolio performance projections",
            "portfolio-owned trade accounting inputs before ledger posting",
        ],
        out_of_scope=[
            "source-document/AtomicPosition lifecycle and extraction provenance",
            "double-entry journal ownership or price/FX observation and resolution ownership",
            "shared value language, telemetry/persistence substrate, report presentation, and workflow",
        ],
    ),
    relationships=[
        ContextRelation(
            provider="audit",
            consumer="portfolio",
            mode="published-language",
            reason="Uses audit Money, Quantity, UnitPrice, and Ratio language for position accounting.",
        ),
        ContextRelation(
            provider="extraction",
            consumer="portfolio",
            mode="projection",
            reason="Reads extraction-owned AtomicPosition and managed-position snapshots as brokerage input without owning document facts or provenance.",
        ),
        ContextRelation(
            provider="ledger",
            consumer="portfolio",
            mode="consumer-port",
            reason="Submits balanced trade and dividend entries through ledger ports while retaining portfolio lot and cost-basis semantics.",
        ),
        ContextRelation(
            provider="observability",
            consumer="portfolio",
            mode="published-language",
            reason="Uses published safe logging language for portfolio calculation diagnostics.",
        ),
        ContextRelation(
            provider="platform",
            consumer="portfolio",
            mode="composition",
            reason="Uses platform ORM persistence mixins without owning generic persistence behavior.",
        ),
        ContextRelation(
            provider="pricing",
            consumer="portfolio",
            mode="published-language",
            reason="Consumes pricing valuation and FX-resolution language but never fetches, stores, or resolves price observations itself.",
        ),
    ],
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
        Unit(name="DividendEvent", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="TradeAccounts", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="TradeOrder", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        # ── taxonomy-only ORM units (no module= — the gate skips placement
        # checks, same as extraction's AtomicTransaction/UploadedDocument).
        # InvestmentTransaction/InvestmentLot/DividendIncome + their enums now
        # live in orm/portfolio.py (#1675 D5): cross-domain references
        # (managed_positions, journal_entries) are bare FK columns; the former
        # relationship() navigations were unused and removed per the
        # 2026-07-11 ruling. ManagedPosition/AtomicPosition/PositionStatus/
        # CostBasisMethod live in extraction's orm/layer3.py (#1675 D4+D5c —
        # extraction owns the fact family's ORM; portfolio imports the
        # published entities, never the ORM class directly).
        Unit(name="ManagedPosition", kind=Kind.AGGREGATE_ROOT),
        Unit(name="InvestmentLot", kind=Kind.ENTITY),
        Unit(name="InvestmentTransaction", kind=Kind.ENTITY),
        Unit(name="DividendIncome", kind=Kind.ENTITY),
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
        "DividendEvent",
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
        "TradeAccounts",
        "TradeOrder",
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
        ac('AC-portfolio.posting-inputs.1', 'Investment posting accepts TradeOrder, TradeAccounts, and DividendEvent value objects so quantity, unit price, money, related accounts, and conditional withholding-tax inputs are constructed once before the write boundary.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_AC_portfolio_posting_inputs_1_value_objects_bound_the_write_signature', priority='P1'),
        ac('AC-portfolio.1.1', 'post_buy posts a balanced ledger entry, creates the opening InvestmentLot, and increases the ManagedPosition cost basis and quantity.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_buy_transaction_creates_balanced_journal_entry_and_lot'),
        ac('AC-portfolio.2.1', 'post_sell consumes InvestmentLots by the configured FIFO cost-basis method and never sells more than the remaining quantity.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_sell_transaction_uses_fifo_and_records_realized_gain'),
        ac('AC-portfolio.2.2', 'post_sell supports average-cost disposal and persists the AVGCOST method on the realized transaction and remaining position.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_sell_transaction_uses_average_cost_for_realized_pnl'),
        ac('AC-portfolio.3.1', 'A sell updates ManagedPosition quantity and disposal status without ever driving an open position quantity below zero.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_sell_transaction_uses_lifo_loss_and_disposes_position'),
        ac('AC-portfolio.4.1', 'post_dividend posts cash plus dividend income and persists a DividendIncome record for the position.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_dividend_transaction_posts_income_and_dividend_record'),
        ac('AC-portfolio.4.2', 'post_dividend splits withholding tax into separate cash and tax expense legs while keeping the ledger entry balanced.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_dividend_transaction_posts_withholding_tax', priority='P1'),
        ac('AC-portfolio.1.2', 'Investment accounting rejects invalid buy, sell, and dividend inputs before writing portfolio or ledger state.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_investment_accounting_rejects_invalid_transactions'),
        ac('AC-portfolio.1.3', 'Investment accounting helper lookups reject missing positions and inactive or wrong-type accounts with clean domain errors.', 'apps/backend/tests/portfolio/test_investment_accounting.py::test_investment_accounting_rejects_invalid_account_and_position_helpers', priority='P1'),
        # ── group reconcile: AtomicPosition -> ManagedPosition reconciliation
        # (migrated from EPIC-011 AC11.1.1-12, migration closeout continuation, #1663) ──
        ac('AC-portfolio.reconcile.1', 'Reconcile creates a new ManagedPosition from an AtomicPosition snapshot.', 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_creates_position'),
        ac('AC-portfolio.reconcile.2', "Reconcile updates an existing position's quantity from the latest snapshot.", 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_updates_position'),
        ac('AC-portfolio.reconcile.3', 'Reconcile disposes a position when the latest snapshot quantity is 0.', 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_disposes_position'),
        ac('AC-portfolio.reconcile.4', "Reconcile sets cost basis from the snapshot's market_value.", 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_cost_basis_uses_market_value'),
        ac('AC-portfolio.reconcile.5', 'Reconcile handles multiple different assets in one run.', 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_multiple_assets'),
        ac('AC-portfolio.reconcile.6', 'The same asset at different brokers reconciles into separate positions.', 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_multiple_brokers_same_asset'),
        ac('AC-portfolio.reconcile.7', "A null/missing broker name falls back to 'Unknown Broker' instead of failing.", 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_with_null_broker', priority='P1'),
        ac('AC-portfolio.reconcile.8', 'A disposed position reactivates to ACTIVE when it reappears in a later snapshot.', 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_reactivates_disposed_position'),
        ac('AC-portfolio.reconcile.9', 'Listing positions returns an empty list when none exist, not an error.', 'apps/backend/tests/assets/test_asset_service.py::test_get_positions_empty'),
        ac('AC-portfolio.reconcile.10', 'Reconcile with no atomic snapshots is a no-op (no positions created/changed).', 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_no_snapshots'),
        ac('AC-portfolio.reconcile.11', 'Negative quantities (short positions) reconcile correctly, not as an error.', 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_negative_quantity_short_position', priority='P1'),
        ac('AC-portfolio.reconcile.12', "A single reconcile run's updated and disposed position counts are mutually exclusive.", 'apps/backend/tests/assets/test_asset_service.py::test_reconcile_result_counts_are_mutually_exclusive'),
        # ── group router: positions/reconcile/depreciation HTTP surface
        # (migrated from EPIC-011 AC11.2/.3/.4/.5/.7, migration closeout continuation, #1663) ──
        ac('AC-portfolio.router.1', 'GET /assets/positions returns an empty list when the user has no positions.', 'apps/backend/tests/assets/test_assets_router.py::test_list_positions_empty'),
        ac('AC-portfolio.router.2', "GET /assets/positions returns the user's positions with data.", 'apps/backend/tests/assets/test_assets_router.py::test_list_positions_with_data'),
        ac('AC-portfolio.router.3', 'GET /assets/positions filters correctly by status.', 'apps/backend/tests/assets/test_assets_router.py::test_list_positions_filter_by_status'),
        ac('AC-portfolio.router.4', "GET /assets/positions/{id} returns the position's details.", 'apps/backend/tests/assets/test_assets_router.py::test_get_position_success'),
        ac('AC-portfolio.router.5', 'GET /assets/positions/{id} returns 404 for a non-existent position.', 'apps/backend/tests/assets/test_assets_router.py::test_get_position_not_found'),
        ac('AC-portfolio.router.6', "GET /assets/positions/{id} returns 404 for another user's position.", 'apps/backend/tests/assets/test_assets_router.py::test_get_position_wrong_user'),
        ac('AC-portfolio.router.7', 'POST /assets/reconcile creates positions from the latest atomic snapshots.', 'apps/backend/tests/assets/test_assets_router.py::test_reconcile_positions_success'),
        ac('AC-portfolio.router.8', 'POST /assets/reconcile with no snapshots returns zero created/updated/disposed counts.', 'apps/backend/tests/assets/test_assets_router.py::test_reconcile_positions_empty'),
        ac('AC-portfolio.router.9', 'GET /assets/positions requires authentication.', 'apps/backend/tests/assets/test_assets_router.py::test_list_positions_requires_auth'),
        ac('AC-portfolio.router.10', 'GET /assets/positions/{id} requires authentication.', 'apps/backend/tests/assets/test_assets_router.py::test_get_position_requires_auth'),
        ac('AC-portfolio.router.11', 'POST /assets/reconcile requires authentication.', 'apps/backend/tests/assets/test_assets_router.py::test_reconcile_requires_auth'),
        ac('AC-portfolio.router.12', "Position queries are isolated by user_id — one user never sees another's positions.", 'apps/backend/tests/assets/test_assets_router.py::test_get_position_user_isolation'),
        # ── group depreciation: depreciation-schedule HTTP surface
        # (migrated from EPIC-011 AC11.6, migration closeout continuation, #1663) ──
        ac('AC-portfolio.depreciation.1', 'GET /assets/positions/{id}/depreciation returns the depreciation schedule.', 'apps/backend/tests/assets/test_assets_router.py::test_get_position_depreciation_success'),
        ac('AC-portfolio.depreciation.2', 'GET /assets/positions/{id}/depreciation returns 400 for a non-existent position.', 'apps/backend/tests/assets/test_assets_router.py::test_get_position_depreciation_not_found'),
        ac('AC-portfolio.depreciation.3', 'GET /assets/positions/{id}/depreciation returns 400 for a disposed position.', 'apps/backend/tests/assets/test_assets_router.py::test_get_position_depreciation_disposed_position'),
        ac('AC-portfolio.depreciation.4', 'GET /assets/positions/{id}/depreciation returns 422 for invalid method/parameters.', 'apps/backend/tests/assets/test_assets_router.py::test_get_position_depreciation_invalid_params', priority='P1'),
        # ── group holdings: holdings summary + portfolio summary reads (was
        # EPIC-017 AC17.1.1, AC17.1.5 and AC17.1.7-9, migration closeout
        # continuation, #1663 / #1717) ──
        ac('AC-portfolio.holdings.1', 'get_holdings returns the holdings summary (ticker, quantity, cost basis, market value) for active positions.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_get_holdings_happy_path'),
        ac('AC-portfolio.holdings.2', 'Unrealized P&L is calculated from cost basis and current market value.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_unrealized_pnl_happy_path'),
        ac('AC-portfolio.holdings.3', 'The portfolio summary happy path returns correct counts and totals.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_portfolio_summary_happy', priority='P1'),
        ac('AC-portfolio.holdings.4', 'The portfolio summary includes both active and disposed positions.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_portfolio_summary_with_disposed', priority='P1'),
        ac('AC-portfolio.holdings.5', 'A zero total cost yields net_pnl_percent = 0 instead of a division error.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_portfolio_summary_zero_cost', priority='P1'),
        ac('AC-portfolio.holdings.6', 'GET /portfolio/holdings responds in the repo-standard items+total wrapper with a warnings list: a point-in-time snapshot excluded from the page (no reconciled managed position as of the requested date) is disclosed to the caller instead of only being logged (#1796).', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC_portfolio_holdings_6_unreconciled_snapshot_disclosed_in_warnings', priority='P1'),
        # ── group performance: XIRR/TWR/MWR + realized/unrealized P&L math
        # (was EPIC-017 AC17.2.1-5 and AC17.2.7-9; AC17.2.6 deduped into
        # AC-portfolio.holdings.2 — same test, same fact; migration closeout
        # continuation, #1663 / #1717) ──
        ac('AC-portfolio.performance.1', 'XIRR over realistic data is accurate (within 0.01% of the Excel XIRR reference).', 'apps/backend/tests/portfolio/test_performance_service.py::test_xirr_with_realistic_data'),
        ac('AC-portfolio.performance.2', 'Time-weighted return is computed correctly for a period.', 'apps/backend/tests/portfolio/test_performance_service.py::test_time_weighted_return_with_period'),
        ac('AC-portfolio.performance.3', 'Money-weighted return is computed from dated cash flows.', 'apps/backend/tests/portfolio/test_performance_service.py::test_money_weighted_return_with_data', priority='P1'),
        ac('AC-portfolio.performance.4', 'A zero cost basis yields realized_pnl_percent = 0 instead of a division error.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_realized_pnl_zero_cost', priority='P1'),
        ac('AC-portfolio.performance.5', 'A disposed position in a non-base currency triggers FX conversion for realized P&L.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_realized_pnl_fx_conversion', priority='P1'),
        ac('AC-portfolio.performance.6', 'Unrealized P&L on an empty portfolio raises PortfolioNotFoundError.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_unrealized_pnl_no_positions', priority='P1'),
        ac('AC-portfolio.performance.7', 'A zero cost basis yields unrealized_pnl_percent = 0 in per-position details.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_unrealized_pnl_zero_cost', priority='P1'),
        ac('AC-portfolio.performance.8', 'Unrealized P&L converts non-base-currency positions via FX.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_unrealized_pnl_fx_conversion', priority='P1'),
        # ── group allocation: allocation breakdowns + performance edge cases
        # (was EPIC-017 AC17.3.1-3, AC17.3.5 and AC17.3.7-14; AC17.3.4/.6
        # deduped into AC-portfolio.performance.2/.3 — same tests, same facts;
        # migration closeout continuation, #1663 / #1717) ──
        ac('AC-portfolio.allocation.1', 'Sector allocation breaks holdings down by sector.', 'apps/backend/tests/portfolio/test_allocation_service.py::test_sector_allocation_with_positions', priority='P1'),
        ac('AC-portfolio.allocation.2', 'Geography allocation breaks holdings down by geography.', 'apps/backend/tests/portfolio/test_allocation_service.py::test_geography_allocation_with_positions', priority='P1'),
        ac('AC-portfolio.allocation.3', 'Asset-class allocation breaks holdings down by asset class.', 'apps/backend/tests/portfolio/test_allocation_service.py::test_asset_class_allocation_with_positions', priority='P1'),
        ac('AC-portfolio.allocation.4', 'MWR raises InsufficientDataError on an empty portfolio.', 'apps/backend/tests/portfolio/test_performance_service.py::test_money_weighted_return_insufficient_data', priority='P1'),
        ac('AC-portfolio.allocation.5', 'XIRR respects the as_of_date parameter.', 'apps/backend/tests/portfolio/test_performance_service.py::test_xirr_with_as_of_date', priority='P1'),
        ac('AC-portfolio.allocation.6', 'TWR returns zero for a same-day period.', 'apps/backend/tests/portfolio/test_performance_service.py::test_time_weighted_return_same_day', priority='P1'),
        ac('AC-portfolio.allocation.7', 'Performance metrics handle cash-only portfolios without positions.', 'apps/backend/tests/portfolio/test_performance_service.py::test_performance_metrics_with_zero_positions', priority='P1'),
        ac('AC-portfolio.allocation.8', 'XIRR handles extreme convergence edge cases.', 'apps/backend/tests/portfolio/test_performance_service.py::test_xirr_convergence_edge_case', priority='P1'),
        ac('AC-portfolio.allocation.9', '_xirr_bisection raises ValueError when no root exists.', 'apps/backend/tests/portfolio/test_performance_service.py::test_xirr_bisection_no_root_raises', priority='P1'),
        ac('AC-portfolio.allocation.10', '_xirr_bisection returns a Decimal estimate after max_iter exhaustion.', 'apps/backend/tests/portfolio/test_performance_service.py::test_xirr_bisection_max_iter_returns', priority='P1'),
        ac('AC-portfolio.allocation.11', '_xirr_newton falls back to bisection on non-convergence.', 'apps/backend/tests/portfolio/test_performance_service.py::test_xirr_newton_fallthrough_to_bisection', priority='P1'),
        ac('AC-portfolio.allocation.12', 'XIRRCalculationError is raised when Newton and bisection both fail.', 'apps/backend/tests/portfolio/test_performance_service.py::test_xirr_calculation_error_raised', priority='P1'),
        # ── group valuation: position valuation reads + balance-sheet flow
        # (was EPIC-017 AC17.5.4-8, migration closeout continuation,
        # #1663 / #1717) ──
        ac('AC-portfolio.valuation.1', "Unrealized P&L flows into the balance sheet with EXACT values: an imported statement's parsed position reaches holdings and the balance sheet at the same exact Decimal market value (quantity, market_value, total_assets, and the net-worth adjustment all pinned).", 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_statement_import_flows_to_holdings_and_balance_sheet', proof_kind='exact'),
        ac('AC-portfolio.valuation.2', 'A zero-quantity position returns its market_value directly instead of deriving a unit price.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_get_latest_price_zero_quantity', priority='P1'),
        ac('AC-portfolio.valuation.3', 'Missing price data raises AssetNotFoundError.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_get_latest_price_no_data', priority='P1'),
        ac('AC-portfolio.valuation.4', '_get_latest_atomic returns the most recent snapshot.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_get_latest_atomic_returns_latest', priority='P1'),
        ac('AC-portfolio.valuation.5', '_get_latest_atomic returns None when no snapshots exist.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_get_latest_atomic_none', priority='P1'),
        # ── group api: portfolio HTTP surface (was EPIC-017 AC17.6.3-21,
        # migration closeout continuation, #1663 / #1717) ──
        ac('AC-portfolio.api.1', 'GET /portfolio/holdings with an as_of_date filter returns 200.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_holdings_with_date_filter', priority='P1'),
        ac('AC-portfolio.api.2', 'GET /portfolio/holdings with include_disposed=true returns 200.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_holdings_include_disposed', priority='P1'),
        ac('AC-portfolio.api.3', 'GET /portfolio/performance without a period returns metrics.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_performance_without_period', priority='P1'),
        ac('AC-portfolio.api.4', 'GET /portfolio/performance with period params returns metrics.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_performance_with_period', priority='P1'),
        ac('AC-portfolio.api.5', 'GET /portfolio/allocation/sector on an empty portfolio returns [].', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_sector_allocation_empty', priority='P1'),
        ac('AC-portfolio.api.6', 'GET /portfolio/allocation/sector with data returns the breakdown.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_sector_allocation_with_data', priority='P1'),
        ac('AC-portfolio.api.7', 'GET /portfolio/allocation/geography on an empty portfolio returns [].', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_geography_allocation_empty', priority='P1'),
        ac('AC-portfolio.api.8', 'GET /portfolio/allocation/geography with data returns the breakdown.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_geography_allocation_with_data', priority='P1'),
        ac('AC-portfolio.api.9', 'GET /portfolio/allocation/asset-class on an empty portfolio returns [].', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_asset_class_allocation_empty', priority='P1'),
        ac('AC-portfolio.api.10', 'GET /portfolio/allocation/asset-class with data returns the breakdown.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_asset_class_allocation_with_data', priority='P1'),
        ac('AC-portfolio.api.11', 'POST /portfolio/prices/update with a single asset returns success.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_update_prices_single', priority='P1'),
        ac('AC-portfolio.api.12', 'POST /portfolio/prices/update with a batch returns success.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_update_prices_batch', priority='P1'),
        ac('AC-portfolio.api.13', 'POST /portfolio/prices/update with an invalid payload returns 422.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_update_prices_invalid_payload', priority='P1'),
        ac('AC-portfolio.api.14', 'All portfolio endpoints require authentication.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_portfolio_endpoints_require_auth', priority='P1'),
        ac('AC-portfolio.api.15', 'GET /portfolio/allocation/sector with as_of_date returns 200.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_allocation_with_as_of_date', priority='P1'),
        ac('AC-portfolio.api.16', 'GET /portfolio/performance returns string-formatted metrics.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_performance_metrics_response_format', priority='P1'),
        ac('AC-portfolio.api.17', 'InsufficientDataError on an empty portfolio defaults xirr/mwr to 0.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_performance_insufficient_data', priority='P1'),
        ac('AC-portfolio.api.18', 'A non-InsufficientData PerformanceError on XIRR returns 422.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_performance_xirr_calculation_error', priority='P1'),
        ac('AC-portfolio.api.19', 'A non-InsufficientData PerformanceError on MWR returns 422.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_performance_mwr_calculation_error', priority='P1'),
        # ── group as-of: point-in-time holdings snapshots (was EPIC-017
        # AC17.9.1-2 — the frontend selector row AC17.9.3 stays in EPIC-017;
        # migration closeout continuation, #1663 / #1717) ──
        ac('AC-portfolio.as-of.1', 'Historical holdings quantity and market value come from the latest AtomicPosition snapshot at or before as_of_date.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_get_holdings_explicit_as_of_uses_historical_atomic_snapshot'),
        ac('AC-portfolio.as-of.2', 'The holdings API returns date-bounded snapshot quantities for explicit as_of_date requests.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_get_holdings_explicit_date_uses_historical_snapshot_quantity'),
        # ── group report-schedule: investment performance report schedule API
        # (was EPIC-017 AC17.10.1-6, migration closeout continuation,
        # #1663 / #1717) ──
        ac('AC-portfolio.report-schedule.1', 'The investment performance schedule API exposes report-ready metrics and per-holding/allocation rows.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule'),
        ac('AC-portfolio.report-schedule.2', 'The schedule API exposes data freshness, source links, and notes for report traceability.', 'tests/tooling/test_investment_performance_report_contract.py::test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract'),
        ac('AC-portfolio.report-schedule.3', 'Schedule source links preserve brokerage statement, price source, ledger, transaction source, and report-section anchors.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule'),
        ac('AC-portfolio.report-schedule.4', 'Schedule data freshness marks the schedule stale when any holding lacks current as-of-date price evidence.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_10_4_report_schedule_marks_stale_when_any_holding_price_is_stale'),
        ac('AC-portfolio.report-schedule.5', 'The XIRR solver never converts monetary Decimal cash flows to float.', 'apps/backend/tests/portfolio/test_performance_service.py::test_AC17_10_5_xirr_solver_does_not_float_monetary_cashflows'),
        ac('AC-portfolio.report-schedule.6', 'The schedule converts mixed-currency cost basis, market value, realized P&L, and dividend income into the presentation currency before aggregation.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_10_6_investment_performance_schedule_converts_mixed_currency_amounts'),
        # ── group logic-audit: portfolio financial logic audit fixes (was
        # EPIC-017 AC17.11.1-4, migration closeout continuation,
        # #1663 / #1717) ──
        ac('AC-portfolio.logic-audit.1', 'XIRR and MWR use investment transactions only, excluding unrelated bank atomic transactions.', 'apps/backend/tests/portfolio/test_financial_logic_audit.py::test_AC17_11_1_xirr_excludes_unrelated_bank_transactions'),
        ac('AC-portfolio.logic-audit.2', 'Summary YTD realized P&L and dividend income convert to the presentation currency before aggregation.', 'apps/backend/tests/portfolio/test_financial_logic_audit.py::test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency'),
        ac('AC-portfolio.logic-audit.3', 'TWR excludes unrelated bank atomic transactions from the period cash-flow adjustment.', 'apps/backend/tests/portfolio/test_financial_logic_audit.py::test_AC17_11_3_twr_excludes_unrelated_bank_transactions'),
        ac('AC-portfolio.logic-audit.4', 'Non-structured source document payloads produce no audit links.', 'apps/backend/tests/portfolio/test_financial_logic_audit.py::test_AC17_11_4_source_document_links_ignore_non_structured_payloads'),
        # ── group fixtures: portfolio audit fixture contract (was EPIC-017
        # AC17.12.1-3, migration closeout continuation, #1663 / #1717) ──
        ac('AC-portfolio.fixtures.1', 'The portfolio audit fixture contract covers multi-broker, multi-currency expected positions and a report period containing every activity row.', 'tests/tooling/test_portfolio_audit_fixture_contract.py::test_AC17_12_1_portfolio_fixture_contract_covers_multi_broker_multi_currency_inputs'),
        ac('AC-portfolio.fixtures.2', 'The fixture contract pins sanitized trade, dividend, fee, and valuation activity rows and derives expected totals from fixture rows and positions.', 'tests/tooling/test_portfolio_audit_fixture_contract.py::test_AC17_12_2_portfolio_fixture_pins_activity_rows_without_raw_documents'),
        ac('AC-portfolio.fixtures.3', 'The personal report package fixture consumes the expanded portfolio expected outputs instead of inline one-position constants.', 'tests/tooling/test_portfolio_audit_fixture_contract.py::test_AC17_12_3_personal_package_references_expanded_portfolio_fixture_contract'),
        # ── group fact-boundary: portfolio facts vs framework conclusions
        # (was EPIC-017 AC17.13.1, migration closeout continuation,
        # #1663 / #1717) ──
        ac('AC-portfolio.fact-boundary.1', 'Portfolio owns holdings, lots, dividends, fees, and source links and relays pricing facts as framework policy inputs; it does not own final US/HK report presentation decisions.', 'tests/tooling/test_framework_reporting_epic_contract.py::test_AC17_13_1_portfolio_supplies_facts_not_framework_conclusions'),
        # ── group pagination: list endpoint pagination bounds (was EPIC-017
        # AC17.30.1-6, migration closeout continuation, #1663 / #1717) ──
        ac('AC-portfolio.pagination.1', 'GET /portfolio/holdings caps results at the default limit when paginating.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_30_1_holdings_default_cap_applied', priority='P1'),
        ac('AC-portfolio.pagination.2', 'GET /portfolio/holdings honors limit and offset to page through holdings.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_30_2_holdings_limit_offset_honored', priority='P1'),
        ac('AC-portfolio.pagination.3', 'GET /portfolio/holdings rejects out-of-range limit/offset with 422.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_30_3_holdings_rejects_out_of_range_pagination', priority='P1'),
        ac('AC-portfolio.pagination.4', 'GET /portfolio/{ticker}/dividends honors limit/offset and rejects out-of-range values.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_30_4_dividends_limit_offset_honored', priority='P1'),
        ac('AC-portfolio.pagination.5', 'GET /portfolio/{ticker}/realized honors limit/offset and rejects out-of-range values.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_30_5_realized_limit_offset_honored', priority='P1'),
        ac('AC-portfolio.pagination.6', 'GET /portfolio/allocation/* honors limit/offset and rejects out-of-range values.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC17_30_6_allocation_limit_offset_honored', priority='P1'),
        # ── group typed-responses: typed Pydantic router responses (was
        # EPIC-017 AC17.31.1-2, migration closeout continuation,
        # #1663 / #1717) ──
        ac('AC-portfolio.typed-responses.1', 'POST /portfolio/prices/update returns the typed {updated_count, results} shape.', 'apps/backend/tests/api/test_typed_contract_sweep.py::test_AC17_31_1_prices_update_returns_typed_batch_response', priority='P2'),
        ac('AC-portfolio.typed-responses.2', 'PATCH /portfolio/{ticker} for an unknown holding returns a structured 404.', 'apps/backend/tests/api/test_typed_contract_sweep.py::test_AC17_31_2_patch_unknown_holding_returns_404', priority='P2'),
        # ── group metrics: portfolio-owned performance math that lived in the
        # reporting EPIC (was EPIC-005 AC5.6.1-3 and AC5.6.6, migration
        # closeout continuation, #1663 / #1717) ──
        ac('AC-portfolio.metrics.1', 'XIRR matches the single-year Excel XIRR reference case within 0.01%.', 'apps/backend/tests/portfolio/test_performance_service.py::test_AC5_6_1_xirr_matches_single_year_excel_case'),
        ac('AC-portfolio.metrics.2', 'Annualized time-weighted return matches the snapshot period reference.', 'apps/backend/tests/portfolio/test_performance_service.py::test_AC5_6_2_time_weighted_return_matches_snapshot_period'),
        ac('AC-portfolio.metrics.3', 'Dividend yield is trailing annual dividends over current value.', 'apps/backend/tests/portfolio/test_performance_service.py::test_AC5_6_3_dividend_yield_uses_trailing_dividends_over_current_value'),
        ac('AC-portfolio.metrics.4', 'Money-weighted return matches XIRR for a single cash flow.', 'apps/backend/tests/portfolio/test_performance_service.py::test_AC5_6_6_money_weighted_return_matches_xirr_for_single_cashflow', priority='P1'),
        ac('AC-portfolio.metrics.5', "A position's contribution to XIRR/TWR/dividend-yield portfolio value as of a historical date is decided by whether it was held on that date (point-in-time, via its snapshot quantity), not by ManagedPosition.status which reflects today -- a position disposed after the requested date still counts.", 'apps/backend/tests/portfolio/test_performance_service.py::test_AC5_6_3_dividend_yield_counts_position_disposed_after_as_of_date', proof_kind='property'),
        # ── group schedule-fallback: mixed-currency schedule fallback (was
        # EPIC-019 AC19.8.8's portfolio share — the readiness-FX and Playwright
        # shares stay in EPIC-019; migration closeout continuation,
        # #1663 / #1717) ──
        ac('AC-portfolio.schedule-fallback.1', 'The mixed-currency investment schedule fallback converts holding cost basis into the schedule currency.', 'apps/backend/tests/portfolio/test_portfolio_router.py::test_AC19_8_8_investment_schedule_fallback_holding_cost_basis_converts_currency'),
        # ── group provenance: conservative provenance labeling (was EPIC-022
        # AC22.10.1's backend half and AC22.13.1's portfolio share — the
        # frontend badge halves stay in EPIC-022; the pricing share is
        # AC-pricing.provenance.1 and the reporting share is
        # AC-reporting.provenance.1; migration closeout continuation,
        # #1663 / #1717) ──
        ac('AC-portfolio.provenance.1', 'A holding whose latest snapshot is backed by a source document is labeled imported; holdings without document evidence carry no provenance label.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_get_holdings_provenance_imported_with_source_document', priority='P1'),
        ac('AC-portfolio.provenance.2', 'Portfolio holdings and explicit as-of holdings expose the normalized provenance enum when the source basis is known, and stay unlabeled instead of guessing.', 'apps/backend/tests/portfolio/test_portfolio_service.py::test_AC22_13_1_explicit_as_of_holdings_preserve_snapshot_provenance', priority='P1'),
        # ── group brokerage-import: brokerage statement parsing + import
        # (was EPIC-017 AC17.4.1-.4.6/.4.8/.4.14, AC17.33.3, AC17.34.1, #1821
        # Wave A pending-package move) ──
        ac('AC-portfolio.brokerage-import.1', 'Moomoo brokerage statement parsing extracts subscription positions.', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_parse_moomoo_fixture_subscription_positions'),
        ac('AC-portfolio.brokerage-import.2', 'Futu brokerage statement parsing aggregates positions.', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_parse_futu_fixture_aggregate_position', priority='P1'),
        ac('AC-portfolio.brokerage-import.3', 'Interactive Brokers positions import idempotently and reconcile on re-import.', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_import_interactive_brokers_positions_idempotently_reconciles', priority='P1'),
        ac('AC-portfolio.brokerage-import.4', 'Broker auto-detection identifies Moomoo, Futu, and Interactive Brokers statements.', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_detect_broker_moomoo_futu_and_interactive_brokers', priority='P1'),
        ac('AC-portfolio.brokerage-import.5', 'The brokerage import endpoint flows a statement import into holdings and the balance sheet.', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_brokerage_import_endpoint', priority='P1'),
        ac('AC-portfolio.brokerage-import.6', 'Concurrent auto and manual brokerage import survives without duplicating positions (idempotency).', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import'),
        ac('AC-portfolio.brokerage-import.7', "Importing brokerage positions links the statement to the broker ASSET account it reconciles into: after POST /statements/{id}/brokerage/import the statement's account_id is set to that account (#1484).", 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_AC17_4_14_brokerage_import_links_statement_to_broker_account', priority='P1'),
        ac('AC-portfolio.brokerage-import.8', "An auto-created broker account adopts the holding's currency instead of a hardcoded USD.", 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_AC17_33_3_broker_account_uses_snapshot_currency_not_hardcoded_usd', priority='P1'),
        ac('AC-portfolio.brokerage-import.9', 'A short position (negative quantity and negative market value) imports as a signed position — atomic and managed rows persist with negative values — instead of being skipped or violating a CHECK constraint (500) (#1448).', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_AC17_34_1_brokerage_import_persists_short_positions_with_negative_market_value', priority='P1'),
        ac('AC-portfolio.brokerage-import.10', '``POST /portfolio/brokerage/import`` validates the payload at the wire boundary: a JSON float anywhere in the payload tree is rejected with 422 (amounts travel as decimal strings per the money wire policy), so float-precision values can never launder into position quantities or market values (#1864 S1).', 'apps/backend/tests/portfolio/test_brokerage_position_parsing.py::test_AC_brokerage_import_10_payload_rejects_json_floats'),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ac('AC-portfolio.fe-assets.1', 'Portfolio page renders loading and error retry states', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC16.15.4 renders loading and error retry states while fetching holdings', priority='P2'),
        ac('AC-portfolio.fe-assets.2', 'Portfolio page renders grouped positions and status filters on successful fetch', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC16.15.5 renders grouped positions and supports status filters', priority='P2'),
        ac('AC-portfolio.fe-assets.3', 'Brokerage import completion and portfolio value navigation', 'apps/frontend/src/__tests__/brokerageImportCompletionFlow.test.tsx::AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation', priority='P2'),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ac('AC-portfolio.fe-ia-portfolio.1', 'The holdings table renders the "Imported" provenance badge only for holdings with concrete document evidence (the backend labeling half migrated to the `portfolio` package roadmap as `AC-portfolio.provenance.1`, migration closeout continuation, #1663 / #1717; the frontend badge half stays here)', 'apps/frontend/src/__tests__/holdingsTable.test.tsx::AC22.10.1 AC22.13.2 shows provenance badges only when provenance is known', priority='P1'),
        ac('AC-portfolio.fe-ia-portfolio.2', 'Manual valuation capture uses a controlled source enum instead of free-text provenance, while existing historical source strings remain displayable in snapshot history', 'apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.4 AC22.10.2 AC11.9.7 valid submit posts a Decimal-safe payload through the typed client', priority='P1'),
        ac('AC-portfolio.fe-ia-portfolio.3', 'Desktop and mobile Playwright smoke covers portfolio provenance badges only for imported holdings, with unproven holdings unlabeled and no document horizontal overflow', 'apps/frontend/playwright/portfolio-provenance.spec.ts::${scenario.name} labels only imported holdings with provenance', priority='P1'),
        ac('AC-portfolio.fe-ia-portfolio.4', 'Portfolio and report surfaces render a shared Imported / Manual / Derived provenance badge; Manual is visually distinct from Imported and unlabeled values remain silent', 'apps/frontend/src/__tests__/provenanceBadge.test.tsx::AC22.13.2 renders normalized Imported, Manual, and Derived badges', priority='P1'),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ac('AC-portfolio.fe-assets2.1', 'The portfolio page labels retirement and benefit asset entry options as assets, with insurance represented only by cash value', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC11.20.3 labels retirement and benefit assets in net-worth allocation', priority='P1'),
        ac('AC-portfolio.fe-assets2.2', '`/portfolio/evidence` exposes a manual valuation entry form using the shared API client.', 'apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.4 AC22.10.2 AC11.9.7 valid submit posts a Decimal-safe payload through the typed client', priority='P2'),
        ac('AC-portfolio.fe-assets2.3', '([#706](https://github.com/wangzitian0/finance_report/issues/706)): the shared guided evidence form for the three source classes (`esop_rsu_plan`, `property_statement`, `liability_statement`) blocks submission and shows a readiness blocker when the required `valuation_basis` or `as_of_date` is missing, never calling the API; value is carried as a `Decimal`-safe string with no float math. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.6 *`.', 'apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.6 validateEvidenceForm flags missing basis and as-of date', priority='P2'),
        ac('AC-portfolio.fe-assets2.4', '([#706](https://github.com/wangzitian0/finance_report/issues/706)): a valid guided evidence submission persists through the existing `POST /api/assets/valuation-snapshots` endpoint via the typed `lib/api.ts` client (never raw `fetch`), mapping the chosen source class to its `component_type`, `valuation_basis`, source label, anchor, and notes, with the monetary `value` sent as a string. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.7 *`.', 'apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.4 AC22.10.2 AC11.9.7 valid submit posts a Decimal-safe payload through the typed client', priority='P2'),
        ac('AC-portfolio.fe-assets2.5', '([#706](https://github.com/wangzitian0/finance_report/issues/706)): the guided evidence flow surfaces a clear "Manual-trusted" disclosure badge for manually entered evidence so users and the traceability appendix can see the source-trust state of a value. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.8 *`.', 'apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.8 form shows a manual-trusted badge', priority='P2'),
        ac('AC-portfolio.fe-assets2.6', '([#706](https://github.com/wangzitian0/finance_report/issues/706)): the guided evidence form renders an accessible single-column mobile layout (and the recent-evidence list) when a mobile viewport is reported by `matchMedia`, and degrades gracefully when `matchMedia` is unavailable. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.9 *`.', 'apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.9 renders accessible single-column form on a mobile viewport', priority='P2'),
        ac('AC-portfolio.fe-assets2.7', 'Dashboard "Annualized Income" card renders the four annualized figures with the currency code and `as_of` date subtitle', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC11.8.2/AC11.8.6/AC5.6.4 renders Annualized Income card with the four metric labels', priority='P2'),
        ac('AC-portfolio.fe-assets2.8', 'Dashboard "Restricted Holdings" card lists restricted holdings separated from liquid net worth, with vesting timeline tooltip', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC11.8.4 renders Restricted Holdings separately with vesting metadata', priority='P2'),
        ac('AC-portfolio.fe-assets2.9', 'Net worth calculation toggle on dashboard (`include_restricted=true|false`) re-fetches and updates total, defaulting to `false` (vision: liquid wealth is primary)', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC11.8.5 defaults to liquid net worth and refetches when restricted holdings are included', priority='P2'),
        ac('AC-portfolio.fe-assets2.10', 'Frontend test mounts AnnualizedIncomeCard and asserts the four metric labels render', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC11.8.2/AC11.8.6/AC5.6.4 renders Annualized Income card with the four metric labels', priority='P2'),
        ac('AC-portfolio.fe-assets2.11', 'Import to Portfolio button visible for parsed/approved statements', 'apps/frontend/src/__tests__/brokerageImportCompletionFlow.test.tsx::AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation'),
        ac('AC-portfolio.fe-assets2.12', 'Import result banner with stats and portfolio link shown on success', 'apps/frontend/src/__tests__/brokerageImportCompletionFlow.test.tsx::AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation'),
        ac('AC-portfolio.fe-assets2.13', 'Import failure shows actionable error without sensitive data', 'apps/frontend/src/__tests__/statementDetailPage.coverage.test.tsx::AC17.8.3 shows actionable import error banner without exposing sensitive data'),
        ac('AC-portfolio.fe-assets2.14', 'Portfolio page shows total portfolio value prominently after import', 'apps/frontend/src/__tests__/brokerageImportCompletionFlow.test.tsx::AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation'),
        ac('AC-portfolio.fe-assets2.15', 'Import button hidden for non-parsed/approved statements (partial batch)', 'apps/frontend/src/__tests__/statementDetailPage.coverage.test.tsx::AC17.8.5 does not show Import to Portfolio for non-parsed statements'),
        ac('AC-portfolio.fe-assets2.16', 'Portfolio page exposes an as-of date selector and passes it to `/api/portfolio/holdings`', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC17.9.3 passes selected as-of date to holdings API'),
        ac('AC-portfolio.fe-assets2.17', 'Portfolio page renders a unified allocation panel without claiming a portfolio-value tie-out when report and holdings currencies differ', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC17.14.1 labels allocation and portfolio currencies instead of claiming a portfolio tie-out', priority='P1'),
        ac('AC-portfolio.fe-assets2.18', 'Portfolio page consumes the report-owned net-worth allocation schedule, showing asset class, liquidity, source currency, net-worth share, source labels, and restricted-inclusion filtering', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC17.14.3 renders net-worth allocation from the report schedule', priority='P1'),
        ac('AC-portfolio.fe-assets2.19', 'The asset-dashboard performance surface leads with unrealized market-value gain/loss, a simple return on cost valued at the schedule as-of date, and a price-freshness flag; TWR/IRR/MWR are not presented as the asset-dashboard answer and stay on the reporting side as clearly-labelled analytical measures', 'apps/frontend/src/__tests__/performanceCard.test.tsx::AC17.14.4 leads with unrealized gain/loss, return on cost, and price freshness', priority='P1'),
        ac('AC-portfolio.fe-assets2.20', 'Holding detail page `/portfolio/[ticker]` renders three tabs: `Overview`, `Dividends`, `Realized P&L`', 'apps/frontend/src/__tests__/holdingDetailPage.test.tsx::AC17.7.1 renders Overview, Dividends, and Realized P&L tabs', priority='P2'),
        ac('AC-portfolio.fe-assets2.21', 'Dividends tab lists historical dividend events `{ex_date, pay_date, amount, currency, reinvested}` from `GET /api/portfolio/{ticker}/dividends`', 'apps/frontend/src/__tests__/holdingDetailPage.test.tsx::AC17.7.2/AC17.7.6 switches to Dividends tab and renders dividend row labels', priority='P2', vision_anchor='decision-1-portfolio-self-developed'),
        ac('AC-portfolio.fe-assets2.22', 'Cost-basis method selector (`FIFO` / `LIFO` / `AvgCost`) on holding detail page persists per-holding via `PATCH /api/portfolio/{ticker}` and re-fetches realized P&L', 'apps/frontend/src/__tests__/holdingDetailPage.test.tsx::AC17.7.3 persists cost-basis method and refetches realized P&L', priority='P2'),
        ac('AC-portfolio.fe-assets2.23', 'Realized P&L tab shows lot-level table `{lot_id, acquired_date, sold_date, quantity, basis, proceeds, gain_loss, holding_period}` from `GET /api/portfolio/{ticker}/realized`', 'apps/frontend/src/__tests__/holdingDetailPage.test.tsx::AC17.7.4 renders lot-level realized P&L table', priority='P2'),
        ac('AC-portfolio.fe-assets2.24', 'Portfolio summary card on dashboard adds `realized_pnl_ytd` and `dividend_income_ytd` figures from `GET /api/portfolio/summary`', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC17.7.5 renders realized P&L YTD and dividend income YTD from portfolio summary', priority='P2'),
    ],
)
# fmt: on
