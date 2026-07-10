"""The ``pricing`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__init__.__all__``
(``implementations["be"]`` = ``apps/backend/src/pricing``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways-cyclic edge.

## What this package is (design review 2026-07-06, #1610)

The price/valuation **observation + resolution** SSOT — not a lookup cache.
Pre-migration, "what is X worth at time T" was scattered across 5 tables with
3 incompatible key vocabularies (``FxRate``, ``StockPrice``,
``MarketDataOverride``, ``ManualValuationSnapshot``, plus statement-extracted
unit prices), and the resolution logic (which observation wins when several
disagree) was implicit and re-derived at each consumption site.

The essence: *an observation that a subject was worth X at time T, from a
source, with an authority rank — plus the resolution policy for conflicting
observations*. NOT named ``market_data`` — the crawler is one source, not the
concept (the package exists even with no crawler: manual valuations and
overrides remain).

## Boundary rulings (record, don't relitigate — see #1610)

1. **Resolution is the core domain service, not an afterthought.**
   ``resolve(subject, as_of, policy)`` — consumers pass policy (reporting
   wants conservative, portfolio wants latest). Moving the 5 tables without
   the resolver would just relocate a junk drawer.
2. **Overrides are append-only high-authority observations, not mutations.**
   Deleting an override re-exposes the prior observation (Axiom A).
   ``MarketDataOverride`` dissolves into the unified observation model
   (``source=manual-override``).
3. **Bitemporal:** ``as_of`` (which day the price belongs to) ≠
   ``observed_at`` (when we learned it). A late backfill must never silently
   rewrite a frozen ``ReportSnapshot``.
4. **Statement-extracted unit prices stay in ``extraction``** (document-fact,
   provenance chain, re-parse lifecycle). ``extraction`` publishes a domain
   event; pricing ingests an id-referenced observation copy
   (``source=statement``). No shared transaction, no FK.
5. **FX splits in two:** conversion *arithmetic* (``convert(money, rate)``,
   rate passed in, pure) stays in ``audit`` — audit never looks up a rate;
   rate *lookup* + FX-specific services (inverse, triangulation, gap
   interpolation) live here.
6. **Subject identity first.** ``PriceableSubject`` unifies the 3 key
   vocabularies (currency pair / listed security / valued component). The
   dual-listing question (same equity, two symbols) is deliberately NOT
   collapsed in the first cut — each listing is its own subject; an alias
   mapping is future package-internal work, not a re-cutover.
7. **Staleness is a fact pricing owns; the tier mapping is policy the
   consumer owns.** ``resolve`` reports an observation's age; reporting
   decides what "too stale" means for its own tier.

``pricing`` is an L3 domain leaf: it imports no other L3 (domain) package —
portfolio/reporting/reconciliation declare the (acyclic, sideways) edge TO
pricing, never the reverse.
"""

from __future__ import annotations

from common.meta.package_contract import ACRecord, Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="pricing",
    # klass is not declared here — it resolves from PACKAGE_LAYER (L0 owns
    # placement in the five-layer topology, #1595); see
    # common/meta/base/layering.py, which lists pricing as "domain" (L3).
    status="active",
    tier="CODE-ONLY",
    # "config" was dropped from this list (migration closeout continuation,
    # #1663 / #1710): src.config is a bare top-level module, not a registered
    # package, so it's never governed by depends_on — no other package
    # declares it either despite importing it directly.
    depends_on=["audit", "platform", "observability"],
    roles=["base", "extension", "data"],
    units=[
        # ── base: the pure observation + subject-identity + policy language ──
        Unit(
            name="PriceObservation",
            kind=Kind.AGGREGATE_ROOT,
            module="base/observation.py",
        ),
        Unit(name="PriceableSubject", kind=Kind.VALUE_OBJECT, module="base/subject.py"),
        Unit(
            name="ObservationSource",
            kind=Kind.VALUE_OBJECT,
            module="base/observation.py",
        ),
        Unit(name="Authority", kind=Kind.VALUE_OBJECT, module="base/observation.py"),
        Unit(name="ResolutionPolicy", kind=Kind.VALUE_OBJECT, module="base/policy.py"),
        Unit(name="PriceObserved", kind=Kind.DOMAIN_EVENT, module="base/events.py"),
        Unit(name="PricingError", kind=Kind.VALUE_OBJECT, module="base/errors.py"),
        # resolve() is implementation-pure (no I/O — the repository port
        # supplies the candidate observations as a plain argument), but
        # KIND_LAYER places every DOMAIN_SERVICE in extension/ with no
        # exception, so it's placed there physically despite being pure.
        Unit(name="resolve", kind=Kind.DOMAIN_SERVICE, module="extension/resolve.py"),
        # The split block (mechanism B): port in base/, adapter in extension/.
        # The adapter is schema-preserving on purpose — it queries the 4
        # legacy tables (FxRate/StockPrice/MarketDataOverride/
        # ManualValuationSnapshot) directly rather than waiting on a unified
        # physical store, so it can land ahead of that migration.
        Unit(
            name="ObservationRepository",
            kind=Kind.REPOSITORY,
            module="base/repository.py",
            impl="extension/repository.py",
        ),
        # record_manual_valuation/record_override are the write-side
        # counterpart to the read adapter above: they persist into the same
        # 2 user-scoped legacy tables the adapter reads back uniformly, and
        # each publishes PriceObserved through the platform outbox in the
        # SAME db session as the write (the counter.record_increment
        # pattern) — the event is atomic with the state change by
        # construction, not a separate best-effort notification.
        Unit(
            name="record_manual_valuation",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/manual.py",
        ),
        Unit(
            name="record_override",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/manual.py",
        ),
        # get_exchange_rate is a thin FX-specific wrapper: the identity rate
        # (a currency against itself) is a business rule that doesn't belong
        # in subject-agnostic resolve(); everything else routes through the
        # same PriceableSubject + resolve() path every other subject kind
        # uses. Caching and the lazy crawler-fallback (fx.py's lazy_load)
        # are deliberately deferred — see extension/fx.py's docstring.
        Unit(
            name="get_exchange_rate", kind=Kind.DOMAIN_SERVICE, module="extension/fx.py"
        ),
        # convert_amount/convert_money/convert_to_base: thin lookup+math
        # bridges over get_exchange_rate (lookup) + audit.money.convert
        # (math, rate passed in — ruling 5, audit never looks up a rate).
        Unit(name="convert_amount", kind=Kind.DOMAIN_SERVICE, module="extension/fx.py"),
        Unit(name="convert_money", kind=Kind.DOMAIN_SERVICE, module="extension/fx.py"),
        Unit(
            name="convert_to_base", kind=Kind.DOMAIN_SERVICE, module="extension/fx.py"
        ),
        # get_average_rate: the mean of the repository's own candidates in a
        # date range (not a separate SQL AVG query) — the repository stays
        # "what observations exist"; averaging is pricing's own logic.
        Unit(
            name="get_average_rate", kind=Kind.DOMAIN_SERVICE, module="extension/fx.py"
        ),
        # ── extension: crawler sync (given scopes, sync/report on them — the
        # ledger-reading discovery of *which* scopes lives in app-glue
        # ``src.services.market_data_discovery``, never inside pricing;
        # dependency inversion, meta Decision B) ──
        Unit(
            name="sync_fx_rates",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/market_data/service.py",
        ),
        Unit(
            name="sync_stock_prices",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/market_data/service.py",
        ),
        Unit(
            name="ensure_market_data_fresh",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/market_data/service.py",
        ),
        Unit(
            name="get_market_data_status",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/market_data/service.py",
        ),
        Unit(
            name="resolve_missing_fx_rate",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/market_data/service.py",
        ),
        # MarketDataScopeStatus/MarketDataSyncResult (DTOs) and
        # MARKET_DATA_QUANTITY_UNIT (a plain constant) are published in
        # ``interface`` below but, like several of audit's own published
        # helpers (e.g. RECONCILIATION_AUTO_ACCEPT_SCORE), don't get their own
        # taxonomy Unit() — units is a curated tactical-pattern annotation,
        # not a 1:1 mirror of interface.
        # ── extension (reserved): the extraction event subscriber ──
        Unit(name="ingest_statement_price", kind=Kind.DOMAIN_SERVICE),
        # ── data (reserved): read-models consumed by portfolio/reporting/reconciliation ──
        Unit(name="LatestPriceView", kind=Kind.PROJECTION),
        Unit(name="StalenessView", kind=Kind.PROJECTION),
    ],
    implementations={"be": "apps/backend/src/pricing", "fe": None},
    # This commit's real, working surface: the pure base/ model, resolve()
    # (implementation-pure, physically in extension/ per KIND_LAYER), the
    # repository port + its read-only SQL adapter (querying the 4 legacy
    # tables), the two user-scoped write-side recorders (which also publish
    # PriceObserved through the platform outbox, atomically with the write —
    # pricing is a real producer on the bus, not just a declared event type),
    # the FX lookup + convert_* + average-rate wrappers, and the crawler sync
    # (moved in from apps/backend/src/services/market_data/, #1610 PR2 step
    # 2). The remaining domain-service (extraction-event ingest) + 2 data
    # projections are reserved units above — they join the interface once a
    # later commit implements them for real.
    interface=[
        "Authority",
        "FxRate",
        "MARKET_DATA_QUANTITY_UNIT",
        "MarketDataScopeStatus",
        "MarketDataSyncResult",
        "MarketDataSyncState",
        "ObservationRepository",
        "ObservationSource",
        "PriceObservation",
        "PriceObserved",
        "PriceableSubject",
        "PricingError",
        "ResolutionPolicy",
        "SqlObservationRepository",
        "StockPrice",
        "convert_amount",
        "convert_money",
        "convert_to_base",
        "ensure_market_data_fresh",
        "get_average_rate",
        "get_exchange_rate",
        "get_market_data_status",
        "record_manual_valuation",
        "record_override",
        "resolve",
        "resolve_missing_fx_rate",
        "sync_fx_rates",
        "sync_stock_prices",
    ],
    events=["PriceObserved"],
    invariants=[
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_1_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="converges-by-layer",
            statement="The package converges into base/ (pure) + extension/ (edges) + data/ (projections).",
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_2_converges_by_layer"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement="base/ never imports the package's own extension/ or data/, the ORM, or any network client.",
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_3_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="observations-are-append-only",
            statement=(
                "PriceObservation rows are never updated or deleted in place; an "
                "override is a new higher-authority observation, and removing one "
                "re-exposes the prior observation it superseded (Axiom A)."
            ),
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_4_observations_are_append_only_by_construction"
            ),
        ),
        Invariant(
            id="audit-never-looks-up-a-rate",
            statement=(
                "audit.money.convert takes a rate as an argument and performs no "
                "database lookup; rate lookup lives only in pricing."
            ),
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_5_audit_convert_takes_rate_as_argument"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates pricing with no violations.",
            test=(
                "tests/tooling/test_pricing_package.py"
                "::test_AC_pricing_1_6_package_contract_gate_passes"
            ),
        ),
    ],
    roadmap=[
        # ── group marketdata: daily FX/stock market data sync (was EPIC-011
        # AC11.10, migration closeout continuation, #1663 / #1710) ──
        ACRecord(
            id="AC-pricing.marketdata.1",
            statement=(
                "Stock price sync fetches daily prices for active holdings "
                "and stores idempotent rows. Was EPIC-011 AC11.10.1."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_sync.py"
                "::test_sync_stock_prices_inserts_missing_daily_rows_and_is_idempotent"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.2",
            statement=(
                "FX sync fetches explicit or observed pairs incrementally, "
                "with USD/base as the default non-empty pair. Was EPIC-011 "
                "AC11.10.2."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_sync.py"
                "::test_sync_fx_rates_starts_after_last_stored_date"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.3",
            statement=(
                "Missing trading days are recorded as misses without "
                "failing the whole sync. Was EPIC-011 AC11.10.3."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_sync.py"
                "::test_sync_stock_prices_records_missing_trading_days"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.4",
            statement=(
                "Primary and secondary providers are cross-validated and "
                "disagreements are not silently persisted. Was EPIC-011 "
                "AC11.10.4."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_sync.py"
                "::test_stock_provider_disagreement_is_reported_without_persisting"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.5",
            statement=(
                "Market data sync endpoints expose FX and stock sync status "
                "for scheduler/E2E callers. Was EPIC-011 AC11.10.5."
            ),
            test=(
                "apps/backend/tests/market_data/test_sync_router.py"
                "::test_market_data_sync_endpoints_return_counts"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.6",
            statement=(
                "Portfolio valuation prefers synced stock prices over stale "
                "brokerage snapshots. Was EPIC-011 AC11.10.6."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_sync.py"
                "::test_portfolio_uses_synced_stock_price_before_atomic_snapshot"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.7",
            statement=(
                "E2E gates cover provider-backed FX sync and stock-price "
                "portfolio valuation paths. Was EPIC-011 AC11.10.7."
            ),
            test=(
                "tests/e2e/test_market_data_price_paths.py"
                "::test_market_data_provider_sync_feeds_fx_and_stock_price_paths"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.8",
            statement=(
                "Long historical market data sync uses bounded range "
                "provider requests instead of per-day provider calls. Was "
                "EPIC-011 AC11.10.8."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_sync.py"
                "::test_sync_stock_prices_fetches_decade_range_once"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.9",
            statement=(
                "Report reads check market data freshness and trigger at "
                "most one immediate refresh when the last successful sync "
                "is older than 24 hours. Was EPIC-011 AC11.10.9."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_sync.py"
                "::test_market_data_freshness_sync_runs_once_after_24h"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.10",
            statement=(
                "Backend scheduler runs daily market data sync at the "
                "nightly Asia/Singapore close-refresh window. Was EPIC-011 "
                "AC11.10.10."
            ),
            test=(
                "apps/backend/tests/market_data/test_scheduler.py"
                "::test_next_market_data_sync_at_uses_nightly_sgt_schedule"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.marketdata.11",
            statement=(
                "Staging E2E covers report-time market data refresh from an "
                "authenticated ordinary-user path without manual sync. Was "
                "EPIC-011 AC11.10.11."
            ),
            test=(
                "tests/e2e/test_market_data_price_paths.py"
                "::test_market_data_provider_sync_feeds_fx_and_stock_price_paths"
            ),
            priority="P0",
            status="done",
        ),
        # ── group manualvaluation: append-only manual valuation facts,
        # Axiom A (was EPIC-011 AC11.19, migration closeout continuation,
        # #1663 / #1710) ──
        ACRecord(
            id="AC-pricing.manualvaluation.1",
            statement=(
                "Correcting a manual valuation appends a new version and "
                "preserves the prior fact unedited as a retrievable "
                "superseded version. Was EPIC-011 AC11.19.1."
            ),
            test=(
                "apps/backend/tests/assets/test_manual_valuation_snapshots.py"
                "::test_AC11_19_1_manual_valuation_correction_appends_version_and_preserves_history"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.manualvaluation.2",
            statement=(
                "Heads-only reads use the current version so a corrected "
                "valuation is never double-counted in net worth or "
                "listings. Was EPIC-011 AC11.19.2."
            ),
            test=(
                "apps/backend/tests/assets/test_manual_valuation_snapshots.py"
                "::test_AC11_19_2_corrected_valuation_is_not_double_counted_in_net_worth"
            ),
            priority="P1",
            status="done",
        ),
        # ── group providers: manual price update + provider symbol/ticker
        # handling (was EPIC-017 AC17.1.6/AC17.15/AC17.33, migration
        # closeout continuation, #1663 / #1710) ──
        ACRecord(
            id="AC-pricing.providers.1",
            statement=(
                "A manual price update creates a MarketDataOverride record "
                "for the given asset/date, independent of provider sync. "
                "Was EPIC-017 AC17.1.6."
            ),
            test=(
                "apps/backend/tests/portfolio/test_portfolio_service.py"
                "::test_update_prices_happy"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.providers.2",
            statement=(
                "_looks_like_ticker accepts real tickers/FX pairs and "
                "rejects fund-name free text. Was EPIC-017 AC17.15.1."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_provider_parsers.py"
                "::test_looks_like_ticker_accepts_real_tickers_rejects_free_text"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.providers.3",
            statement=(
                "A non-ticker identifier short-circuits the Yahoo stock "
                "fetch with no HTTP call. Was EPIC-017 AC17.15.2."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_provider_parsers.py"
                "::test_yahoo_stock_fetch_short_circuits_for_non_ticker"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.providers.4",
            statement=(
                "HK numeric exchange codes map to the Yahoo <4-digit>.HK "
                "symbol while US tickers and already-suffixed symbols pass "
                "through unchanged. Was EPIC-017 AC17.33.1."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_provider_parsers.py"
                "::test_AC17_33_1_yahoo_stock_symbol_maps_hk_numeric_codes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-pricing.providers.5",
            statement=(
                "HK numeric codes resolve to the Stooq <4-digit>.hk symbol "
                "while US tickers stay .us. Was EPIC-017 AC17.33.2."
            ),
            test=(
                "apps/backend/tests/pricing/market_data/test_provider_parsers.py"
                "::test_AC17_33_2_stooq_stock_symbol_maps_hk_numeric_codes"
            ),
            priority="P1",
            status="done",
        ),
        # ── group provenance: normalized data-provenance vocabulary, pricing
        # share of a dual-package row (was EPIC-022 AC22.13.1, migration
        # closeout continuation, #1663 / #1710) ──
        ACRecord(
            id="AC-pricing.provenance.1",
            statement=(
                "Manual valuation component items expose a provenance field "
                "constrained to the shared Imported/Manual/Derived "
                "vocabulary. Was EPIC-022 AC22.13.1 (pricing's "
                "ManualValuationSnapshot share of a dual-package row; the "
                "portfolio and reporting shares stay with their own owners)."
            ),
            test=(
                "apps/backend/tests/assets/test_manual_valuation_snapshots.py"
                "::test_AC22_13_1_valuation_component_item_uses_normalized_provenance_type"
            ),
            priority="P1",
            status="done",
        ),
    ],
)
