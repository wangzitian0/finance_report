# `pricing` — Price and Valuation Resolution SSOT

`common/pricing/` owns `PriceObservation` / `PriceableSubject` / `resolve(subject, as_of, policy)` (`apps/backend/src/pricing/`, `status="active"`, `tier="CODE-ONLY"`). Overrides are append-only (Axiom A), bitemporal (`as_of != observed_at`), and publish `PriceObserved` events atomically.

## Decision-backed valuation contributions

`resolve_valuation_contribution()` and `resolve_manual_valuation_contributions()` return typed DTOs carrying audit `TraceDecisionRef` coordinates (`ManualValuationAttestationPolicy` / `ResolvedMarketValuationPolicy`). Unproven or stale observations remain `unproven` (draft only). Investment schedules pass `MarketValuationSelection` identities for re-verification before freezing a package.

## <a id="manual-valuation-snapshots"></a>Manual valuation snapshots (pre-#1610-cutover shipped model)

`ManualValuationSnapshot` (`manual_valuation_snapshots`, `apps/backend/src/pricing/orm/manual_valuation.py`) records positive `Decimal` manual assets/liabilities (`property_value`, `rsu`, `other_liability`, etc.) with `liquidity_class`, `provenance="manual"`, and `ManualValuationBasis` (`market_appraisal`, `employer_grant_document`, `bank_statement`, `broker_statement`, `government_statement`, `insurer_statement`, `self_estimate`). Guided updates via `record_manual_valuation()` version by `(component_type, source, as_of_date)`; snapshots without a basis raise `missing_valuation_basis`. `split_net_worth_scope()` (`extension/valuation.py`) separates liquid vs excluded restricted/illiquid assets and linked liabilities.

## Market data (pre-#1610-cutover shipped model)

Supports lazy report FX/price resolution and daily scheduled sync (`run_market_data_scheduler()` at 22:00 Asia/Singapore via `MarketDataScopeProvider`) from Yahoo Finance and Stooq (`<= 2%` cross-source check; `POST /api/market-data/{fx,stocks}/syncs`, read-only `GET /api/market-data/status` and `GET /api/reports/*`).

- **FX precision & conversion**: Store 6 dp rates in `fx_rates`/`stock_prices`, convert amounts solely via `ExchangeRate(` and `Money(` (`convert(Money(Decimal("1000.00"), "SGD"), ExchangeRate("SGD", "USD", Decimal("0.741523"))).amount` -> `741.52 USD`), never raw floats or ad-hoc multiplication. Missing paths raise `NoObservationError` (`PricingError`).
- **Seeding**: `uv run python tools/seed_fx_rates.py --env local`.
