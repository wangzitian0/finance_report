# `pricing` — the price/valuation observation + resolution SSOT (domain package)

> Package model: [`../meta/readme.md`](../meta/readme.md). Machine contract:
> [`contract.py`](./contract.py).
>
> This `common/pricing/` directory is the **spec + review surface**; the
> conforming implementation lives at
> [`apps/backend/src/pricing`](../../apps/backend/src/pricing)
> (`contract.implementations["be"]`).
>
> **Status: `draft`** (design review #1610 landed the model + resolver +
> repository + FX wrappers; the roadmap is still empty pending the
> EPIC-011/005/017 pricing-AC migration — see [Status](#status) below).

## Why

Pre-migration, "what is X worth at time T" was scattered across 5 tables with
3 incompatible key vocabularies (`FxRate`, `StockPrice`, `MarketDataOverride`,
`ManualValuationSnapshot`, plus statement-extracted unit prices), and the
resolution logic (which observation wins when several disagree) was implicit
and re-derived at each consumption site. `pricing` unifies this into one
observation + resolution SSOT, orthogonal to the financial flow: portfolio
marks positions to market, reconciliation checks per-currency balances,
reporting restates net worth — all through the same `resolve(subject, as_of,
policy)` call.

## Ubiquitous language

- **`PriceObservation`** — the aggregate root: a subject was worth X at time
  T, from a source, with an authority rank. Append-only (Axiom A) — an
  override is a new higher-authority observation, never a mutation; deleting
  one re-exposes the prior observation.
- **`PriceableSubject`** — unifies the 3 legacy key vocabularies (currency
  pair / listed security / valued component) into one subject identity.
- **`resolve(subject, as_of, policy)`** — the domain service, not a lookup:
  consumers pass a `ResolutionPolicy` (reporting wants conservative, portfolio
  wants latest).
- **Bitemporal** — `as_of` (which day the price belongs to) ≠ `observed_at`
  (when we learned it). A late backfill must never silently rewrite a frozen
  `ReportSnapshot`.
- **`PriceObserved`** — the domain event `pricing` publishes (through the
  platform outbox, atomically with the write) whenever a new observation is
  recorded; `extraction` is one producer (`source=statement`), the manual
  recorders another (`source=manual-override`).

## Boundary rulings (record, don't relitigate — see #1610)

1. Statement-extracted unit prices stay in `extraction` (document-fact,
   provenance chain, re-parse lifecycle); `extraction` publishes `PriceObserved`
   and pricing ingests an id-referenced copy. No shared transaction, no FK.
2. FX splits in two: conversion *arithmetic* (`audit.money.convert(money,
   rate)`, rate passed in, pure) stays in `audit` — audit never looks up a
   rate; rate *lookup* + FX-specific services (inverse, triangulation, gap
   interpolation) live here.
3. Staleness is a fact pricing owns; the tier mapping ("too stale for this
   report") is policy the consumer owns.

`pricing` is an L3 domain leaf: it imports no other L3 (domain) package —
portfolio/reporting/reconciliation declare the (acyclic, sideways) edge TO
pricing, never the reverse.

## What's real today

The pure `base/` model (`PriceObservation`/`PriceableSubject`/
`ResolutionPolicy`), `resolve()`, the `ObservationRepository` port + its
read-only SQL adapter (querying the 4 legacy tables directly — schema-preserving
on purpose, so this lands ahead of a unified physical store), the two
user-scoped write-side recorders (`record_manual_valuation`/`record_override`,
each publishing `PriceObserved` atomically with the write), the
extraction-event ingest subscriber (`ingest_statement_price` +
`subscribe_price_ingest`, #1642 — the codebase's first cross-domain event
consumer: extraction's `source=statement` `PriceObserved` publications land as
id-referenced copies in `statement_price_observations`, idempotent on the
upstream fact id, no FK, wired by the app composition root), and the FX
lookup + `convert_*` + average-rate wrappers (`extension/fx.py`).

Reserved (declared in [`contract.py`](./contract.py), no `module=` yet): the
`LatestPriceView`/`StalenessView` read projections.

## Status

`status="active"`, `tier="CODE-ONLY"` — the package owns its ACs in
[`contract.py`](./contract.py)'s `roadmap` (`AC-pricing.*`; the EPIC-era rows
were distributed in the migration closeout series, umbrella #1416). Remaining
consumer wiring is tracked in #1610 PR2.

## <a id="manual-valuation-snapshots"></a>Manual valuation snapshots (pre-#1610-cutover shipped model)

*(Internalized from `docs/ssot/assets.md`, migration closeout wave 3, #1664
— this is now the single owner; do not re-add a separate SSOT copy.
`ManualValuationSnapshot` is the shipped pre-migration shape; it retires
into the unified append-only `PriceObservation` model above at the #1610
consumer-wiring cutover — a manual valuation becomes a high-authority
observation. This section describes the shipped behavior in the meantime.)*

Manual snapshots (`ManualValuationSnapshot`, `manual_valuation_snapshots`
table, `apps/backend/src/extraction/orm/layer3.py`, #1675 D5c) cover property value,
mortgage/loan balance, CPF/provident fund balances, retirement accounts,
personal social-security account balances, long-term benefit assets,
legacy long-term savings, tax payable/refund, insurance cash value, ESOP,
RSU, stock options, and generic assets/liabilities. Insurance is
represented only by its attributable cash/surrender value — coverage
amounts and future benefits are never recorded as assets. The value is
always a positive `Decimal`; `liquidity_class` determines whether it
contributes to assets, liabilities, restricted, or illiquid net-worth
presentation. Reminder cadence is optional; when present, `recurrence_days`
is positive.

Manual snapshot capture uses a controlled source vocabulary for new
frontend submissions: `manual`, `broker_portal`, `bank_portal`,
`cpf_portal`, `tax_portal`, `insurer_portal`, `employer_portal`,
`property_valuation`, `other_document`. Historical source strings remain
valid response data and are displayed as-is when they don't match a known
vocabulary value.

Manual valuation snapshot and latest-valuation-component API responses
expose normalized read-model provenance as `provenance="manual"` — a
separate user-trust signal from the snapshot's `source` basis string:
`source` describes where the user says the value came from, while
`provenance` states that the value was user-entered rather than imported
or derived by the system.

### Guided evidence intake contract (#706)

Guided evidence intake is the end-to-end contract for capturing a
manual-trusted value with a structured, auditable evidence basis. It binds
the frontend guided form, the persisted `valuation_basis` enum, the
component classification, and the report artifacts that surface the basis
into one chain.

**Guided form → `component_type` → default `valuation_basis`.** The shared
guided form offers three source classes; each maps to a backend
`component_type` and a default basis (the user may override from the full
enum):

| Guided source class | `component_type`   | Default `valuation_basis`   |
|---------------------|--------------------|-----------------------------|
| `esop_rsu_plan`     | `rsu`              | `employer_grant_document`   |
| `property_statement`| `property_value`   | `market_appraisal`          |
| `liability_statement`| `other_liability` | `bank_statement`            |

**`valuation_basis` enum values** (`ManualValuationBasis`, persisted on the
snapshot; nullable): `market_appraisal`, `broker_statement`,
`employer_grant_document`, `bank_statement`, `government_statement`,
`insurer_statement`, `self_estimate`. A current evidence-bearing snapshot
with no basis (and no legacy notes) surfaces a `missing_valuation_basis`
readiness blocker rather than being rejected.

**Report artifacts that surface the basis** — the captured basis flows,
null-safe (falling back to `unspecified`), into: the annualized income
schedule (`GET /api/reports/package/annualized-income-schedule`, each
restricted holding's `valuation_basis` carries the snapshot enum value);
balance sheet / net worth (manual snapshots aggregate into asset/liability
and restricted/illiquid totals by `liquidity_class`); the package
`valuation-basis` note (surfaces the `manual_valuation_snapshots` source
state); and the traceability appendix (each manual snapshot's
source-anchor detail records its `valuation_basis` enum value).

Design constraints: manual valuation values are positive `Decimal`
amounts; use `liquidity_class` to separate liquid/restricted/illiquid/
liability presentation; never include a snapshot in liquid net worth
unless it is economically liquid.

## Market data (pre-#1610-cutover shipped model)

*(Internalized from `docs/ssot/market_data.md`, migration closeout wave 3,
#1664 — this is now the single owner; do not re-add a separate SSOT copy.
The `FxRate`/`StockPrice`/`MarketDataOverride` split and the `fx`/
`market_data` services are the shipped pre-migration model that
consolidates into the unified observation model above at the #1610
consumer-wiring cutover.)*

Report and dashboard preparation may automatically refresh FX rates and
stock prices for currencies/symbols observed in trusted user data.
Automatic market-data refresh is supporting evidence for valuation and
reporting — it never replaces source documents, brokerage statements, or
user-confirmed ledger facts. Every persisted FX rate or price retains its
source and date; when market data is unavailable or stale, reports and
assistant suggestions must expose that limitation instead of inventing a
value.

**Data sources** — primary: Yahoo Finance chart endpoint (yfinance-
compatible currency/stock symbols; report-side lazy FX rates + daily stock
closes; unofficial ~2000 req/hour; falls back to stored inverse/bridge
rates before an external fetch). Secondary: Stooq (public daily CSV, no
app secret; cross-source validation for incremental sync — if Yahoo and
Stooq differ by more than 2%, the row is not persisted and the
disagreement is returned/logged).

Report lazy-resolution priority: (1) existing direct DB row on or before
the date, (2) existing inverse DB row persisted as a derived direct row,
(3) existing bridge rows via `MARKET_DATA_FX_BRIDGE_CURRENCY` (default
USD), (4) Yahoo Finance direct/inverse/bridge fetch when lazy fetch is
enabled — otherwise raises `MarketDataUnavailable`.

**Sync schedule** — FX rates and stock prices both sync daily at 22:00
Asia/Singapore from pricing's own scheduler (`run_market_data_scheduler()`,
started in the FastAPI lifespan; absorbed from
`services/market_data_scheduler.py`, #1610 P2). The scheduler never
discovers scopes itself: the app composition root injects a
`MarketDataScopeProvider` (`src/composition.py::market_data_scopes`, which
composes each domain's published currency/holdings reads) — pricing stays
an L3 leaf. FX pairs derive from actual business data plus a
non-empty default pair between `BASE_CURRENCY` and USD (explicit API pairs
also accepted); stock symbols are active holdings or explicit API
symbols. Long-lived daily history is retained — incremental sync starts
after the latest stored date so decade-scale datasets don't need full
refreshes. Report APIs still use lazy resolution when a required rate is
missing. The Yahoo stock fetch is skipped (no observation, debug-logged)
for identifiers that aren't plausibly a ticker (whitespace, excessive
length, free text like `CSOP USD MONEY MARKET FUND SGX296797238`) — real
tickers (`AAPL`, `BRK.B`, `0700.HK`) and FX pairs (`USDSGD`) still pass;
such fund positions value from their existing brokerage snapshot instead.

Manual/E2E callers can trigger `POST /api/market-data/fx/syncs` and
`POST /api/market-data/stocks/syncs`. Report endpoints call
`ensure_market_data_fresh()` before generation with the report's own
effective end date — if the relevant FX pair, requested non-base report
currency, or active stock symbol has no successful provider sync in the
last 24 hours, the backend sends one immediate incremental provider
request and records the new sync state (including successful no-row
responses like weekends/holidays). `GET /api/market-data/status` is
authenticated, read-only, and does not trigger provider requests. Sync
fetches provider data by bounded date range per pair/symbol, then inserts
only missing daily rows — never one provider request per calendar day.

**Data schema** — `fx_rates` (`base_currency`, `quote_currency`, `rate`
`CHECK (rate > 0)`, `rate_date`, `source`, unique on
`(base_currency, quote_currency, rate_date)`); `stock_prices` (`symbol`,
`price` `CHECK (price > 0)`, `currency`, `price_date`, `source`, unique on
`(symbol, currency, source, price_date)` — provider-scoped uniqueness
because the same symbol/date can arrive from different sources/currencies;
read paths query by `symbol`+`price_date` and pick deterministically by
latest `created_at` then `source` when more than one provider-scoped row
exists); `market_data_sync_state` (`kind`, `scope`, `last_success_at`,
`last_success_date`, `last_observation_date`, unique on `(kind, scope)`).

**FX rate precision** — storage 6 decimals, amount calculation 2 decimals
(after conversion), display 4 decimals. Conversion always goes through
`audit.money.convert`/`ExchangeRate` (never a hand-rolled multiply), e.g.
`convert(Money(Decimal("1000.00"), "SGD"), ExchangeRate("SGD", "USD",
Decimal("0.741523"))).amount` → `741.52 USD`.

**Caching** — no global in-process TTL cache: the retired
`services/fx.py` cache was deliberately not carried into pricing
(correctness first; re-add only if load-tested need appears). Report
builders batch-prefetch their pairs into a scope-local
`PrefetchedFxRates` instead; `lazy_load=True` call sites may resolve a
missing DB rate through inverse, bridge, or Yahoo Finance and persist the
result to `fx_rates`.

Design constraints: always store the source name with the rate for
auditability; store FX rates exactly and convert amounts through
`Money`/`ExchangeRate` so 2dp money rounding stays centralized; prefer
historical rates over real-time for reporting; persist derived report-side
rates with `source` values like `derived:inverse:SGD/HKD`,
`derived:bridge:USD`, or `yahoo_finance`; persist only positive FX
rates/prices (invalid zero/negative provider outputs are rejected at the
database boundary). Never hardcode exchange rates; never silently invent
rates when direct, inverse, bridge, and provider lookup all fail.

**Error handling** — missing direct rate → try inverse/bridge rates from
`fx_rates`; source timeout → log a warning and continue to report error
handling; missing rate for date → use the latest stored/provider date on
or before the requested date; all lazy paths failed → raise the pricing
error family (`NoObservationError`, a `PricingError`, with the
`No FX rate available for BASE/QUOTE on DATE` message), report APIs
surface a controlled `ReportError`.

**FX rate seeding (test data)** — `uv run python tools/seed_fx_rates.py
--env local` (or `--env staging` with `DATABASE_URL` set) seeds a fixed
FX-rate test dataset (USD/SGD/EUR base rates plus USD↔SGD 1.28,
USD↔EUR 0.852) used for deterministic FX gain/loss test scenarios.
