# Market Data SSOT

> **SSOT Key**: `market_data`
> **Core Definition**: FX rates and stock prices data sources, sync schedule, and caching strategy.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Report Lazy FX Resolution** | `apps/backend/src/services/market_data.py` | On-demand FX derivation/fetch for reports |
| **FX Lookup API** | `apps/backend/src/services/fx.py` | DB lookup, in-process cache, optional lazy resolution |
| **Rate Storage** | `fx_rates` table | Historical direct and derived rates |
| **Market Data Sync** | `apps/backend/src/services/market_data.py` | Incremental FX/stock sync and provider validation |
| **Market Data Status** | `GET /api/market-data/status` | Authenticated read-only freshness status for ordinary-user E2E and support diagnostics |
| **Market Data Scheduler** | `apps/backend/src/services/market_data_scheduler.py` | Daily 22:00 Asia/Singapore background sync |
| **Price Storage** | `stock_prices` table | Historical daily stock prices |
| **Sync State Storage** | `market_data_sync_state` table | Last successful provider sync timestamp by FX pair or stock symbol |

## 1.1 Product Automation Contract

Report and dashboard preparation may automatically refresh FX rates and stock
prices for currencies and symbols observed in trusted user data. Automatic
market-data refresh is supporting evidence for valuation and reporting; it does
not replace source documents, brokerage statements, or user-confirmed ledger
facts.

Every persisted FX rate or price must retain its source and date. If market
data is unavailable or stale, reports and assistant suggestions must expose that
limitation instead of inventing a value.

---

## 2. Data Sources

### Primary: Yahoo Finance
- **Type**: Yahoo Finance chart endpoint, compatible with yfinance currency and stock symbols
- **Data**: Report-side lazy FX rates and daily stock closes
- **Rate Limit**: Unofficial, ~2000 requests/hour
- **Fallback**: Stored inverse or bridge rates before external fetch

### Secondary: Stooq
- **Type**: Public daily CSV endpoint, no application secret required
- **Data**: FX rates and daily stock closes
- **Use Case**: Cross-source validation for incremental sync. If Yahoo and Stooq differ by more than 2%, the row is not persisted and the disagreement is returned/logged.

### Report Lazy Resolution Priority
```python
async def get_fx_rate(base: str, quote: str, date: date) -> Decimal:
    # 1. Existing direct DB row on or before date
    # 2. Existing inverse DB row, persisted as derived direct row
    # 3. Existing bridge rows via MARKET_DATA_FX_BRIDGE_CURRENCY, default USD
    # 4. Yahoo Finance direct/inverse/bridge fetch when lazy fetch is enabled
    raise MarketDataUnavailable(f"No source available for {base}/{quote}")
```

---

## 3. Sync Schedule

### FX Rates
- **Frequency**: Daily at 22:00 Asia/Singapore from the backend scheduler.
- **Pairs**: Derived from actual business data plus a non-empty default pair between `BASE_CURRENCY` and USD. Explicit API pairs are also accepted.
- **History**: Long-lived daily history is retained. Incremental sync starts after the latest stored date so decade-scale datasets do not require full refreshes.
- **Status**: Implemented for incremental range fill. Report APIs still use lazy resolution when a required rate is missing.

### Stock Prices
- **Frequency**: Daily at 22:00 Asia/Singapore from the backend scheduler.
- **Symbols**: Active holdings, or explicit symbols from API callers.
- **History**: Long-lived daily history is retained. Incremental sync starts after the latest stored date so decade-scale datasets do not require full refreshes.
- **Status**: Implemented. Portfolio valuation prefers synced daily prices over stale brokerage snapshots.

### Sync Workflow
- The backend starts `run_market_data_scheduler()` in FastAPI lifespan and runs FX plus stock sync once per day at 22:00 Asia/Singapore.
- Manual and E2E callers can still use `POST /api/market-data/sync/fx` and `POST /api/market-data/sync/stocks`.
- Report endpoints call `ensure_market_data_fresh()` before report generation with the report's own effective end date. If the relevant FX pair, requested non-base report currency, or active stock symbol has no successful provider sync in the last 24 hours, the backend sends one immediate incremental provider request and records the new sync state, including successful no-row responses such as weekends or market holidays.
- Authenticated users can call `GET /api/market-data/status` with explicit `pairs` and `symbols` query parameters, or with no explicit scopes to inspect observed user scopes. The endpoint is read-only and does not trigger provider requests.
- Sync fetches provider chart/CSV data by bounded date range per pair or symbol, then inserts only missing daily rows. It does not issue one provider request per calendar day.

---

## 4. Data Schema

### fx_rates
```sql
CREATE TABLE fx_rates (
    id UUID PRIMARY KEY,
    base_currency CHAR(3) NOT NULL,
    quote_currency CHAR(3) NOT NULL,
    rate DECIMAL(18,6) NOT NULL,
    rate_date DATE NOT NULL,
    source VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    CHECK (rate > 0),
    UNIQUE(base_currency, quote_currency, rate_date)
);

CREATE INDEX idx_fx_rates_lookup 
    ON fx_rates(base_currency, quote_currency, rate_date);
```

### stock_prices
```sql
CREATE TABLE stock_prices (
    id UUID PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    price DECIMAL(18,6) NOT NULL,
    currency CHAR(3) NOT NULL,
    price_date DATE NOT NULL,
    source VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    CHECK (price > 0),
    UNIQUE(symbol, currency, source, price_date)
);

CREATE INDEX idx_stock_prices_lookup 
    ON stock_prices(symbol, price_date);
```

`stock_prices` uses provider-scoped uniqueness because the same symbol/date can
arrive from different sources or currencies. Report and portfolio read paths
still query by `symbol` and `price_date`; when more than one provider-scoped row
exists on the same date, they select deterministically by latest `created_at`
and then `source`.

### market_data_sync_state
```sql
CREATE TABLE market_data_sync_state (
    id UUID PRIMARY KEY,
    kind VARCHAR(10) NOT NULL,
    scope VARCHAR(50) NOT NULL,
    last_success_at TIMESTAMP NOT NULL,
    last_success_date DATE NOT NULL,
    last_observation_date DATE NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE(kind, scope)
);

CREATE INDEX idx_market_data_sync_state_lookup
    ON market_data_sync_state(kind, scope);
```

---

## 5. FX Rate Precision

| Use Case | Decimal Places |
|----------|----------------|
| FX rate storage | 6 decimals |
| Amount calculation | 2 decimals (after conversion) |
| Display | 4 decimals |

```python
# Conversion example
amount_sgd = Decimal("1000.00")
fx_rate = Decimal("0.741523")  # SGD/USD
amount_usd = (amount_sgd * fx_rate).quantize(Decimal("0.01"))
# Result: 741.52 USD
```

---

## 6. Caching Strategy

### FX Cache
- **Key format**: `fx:{base}:{quote}:{date}`
- **TTL**: 24 hours
- **Implementation**: In-process cache in `apps/backend/src/services/fx.py`
- **Fallback**: Database lookup if cache miss
- **Report lazy resolution**: `lazy_load=True` call sites may resolve a missing DB rate through inverse, bridge, or Yahoo Finance and persist the result to `fx_rates`.

```python
async def get_fx_rate_cached(base: str, quote: str, date: date) -> Decimal:
    cache_key = f"fx:{base}:{quote}:{date.isoformat()}"
    
    # Try cache
    cached = await redis.get(cache_key)
    if cached:
        return Decimal(cached)
    
    # Fallback to DB
    rate = await db.query(FxRate).filter(...).first()
    if rate:
        await redis.setex(cache_key, 86400, str(rate.rate))
        return rate.rate
    
    # Report-only lazy fallback
    rate = await resolve_missing_fx_rate(base, quote, date)
    await save_to_db(rate)
    cache.set(cache_key, rate)
    return rate
```

---

## 7. Design Constraints

### ✅ Recommended Patterns
- **Pattern A**: Always store source name with rate for auditability
- **Pattern B**: Use Decimal(6) for rates, Decimal(2) for converted amounts
- **Pattern C**: Prefer historical rates over real-time for reporting
- **Pattern D**: Persist derived report-side rates with `source` values such as `derived:inverse:SGD/HKD`, `derived:bridge:USD`, or `yahoo_finance`.
- **Pattern E**: Persist only positive FX rates and stock prices; invalid
  zero/negative provider outputs are rejected at the database boundary.

### ⛔ Prohibited Patterns
- **Anti-pattern A**: **NEVER** hardcode exchange rates
- **Anti-pattern B**: **NEVER** silently invent rates when direct, inverse, bridge, and provider lookup all fail

---

## 8. Error Handling

| Error | Action |
|-------|--------|
| Missing direct rate | Try inverse and bridge rates from `fx_rates` |
| Source timeout | Log warning and continue to report error handling |
| Missing rate for date | Use the latest stored/provider date on or before the requested date |
| All lazy paths failed | Raise `FxRateError`; report APIs surface a controlled `ReportError` |

---

## 9. Verification

| Behavior | Test Method | Status |
|----------|-------------|--------|
| Inverse lazy resolution | `test_get_exchange_rate_lazy_derives_inverse` | ✅ Implemented |
| Provider lazy resolution | `test_get_exchange_rate_lazy_fetches_provider_when_enabled` | ✅ Implemented |
| Report HKD/SGD bridge resolution | `test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates` | ✅ Implemented |
| Cache hit/miss | `test_fx_cache` | ✅ Implemented |
| Provider disagreement blocks persistence | `test_stock_provider_disagreement_is_reported_without_persisting` | ✅ Implemented |
| Daily stock/FX sync | `test_sync_stock_prices_inserts_missing_daily_rows_and_is_idempotent`, `test_sync_fx_rates_starts_after_last_stored_date` | ✅ Implemented |
| Provider-backed stock and lazy FX E2E | `test_market_data_provider_sync_feeds_fx_and_stock_price_paths` | ✅ Implemented |
| Long-history range sync | `test_sync_stock_prices_fetches_decade_range_once` | ✅ Implemented |
| Report-time 24h freshness check | `test_market_data_freshness_sync_runs_once_after_24h`, `test_report_endpoint_runs_market_data_freshness_check` | ✅ Implemented |
| Ordinary-user staging report refresh | `test_market_data_provider_sync_feeds_fx_and_stock_price_paths`, `test_market_data_status_endpoint_returns_authenticated_scope_freshness` | ✅ Implemented |
| Nightly scheduler | `test_next_market_data_sync_at_uses_nightly_sgt_schedule` | ✅ Implemented |

---

## 10. FX Rate Seeding (Test Data)

For testing FX gain/loss calculations, use the seeding script.

### Script Usage

```bash
# Local development (from repo root)
uv run python tools/seed_fx_rates.py --env local

# Staging (requires DATABASE_URL)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  uv run python tools/seed_fx_rates.py --env staging
```

### Test Data Seeded

The script seeds FX rates for 2026-01-23:

| Base | Quote | Rate | Description |
|------|-------|------|-------------|
| USD | USD | 1.000000 | Base rate |
| SGD | SGD | 1.000000 | Base rate |
| EUR | EUR | 1.000000 | Base rate |
| USD | SGD | 1.280000 | 1 USD = 1.28 SGD |
| USD | EUR | 0.852000 | 1 USD = 0.852 EUR |
| SGD | USD | 0.781250 | 1 SGD = 1/1.28 USD |
| EUR | USD | 1.173709 | 1 EUR = 1/0.852 USD |

### Expected FX Calculation Example

With test data:
- **Historical cost**: 10,000 USD @ 1.25 = 12,500 SGD
- **Current value**: 10,000 USD @ 1.28 = 12,800 SGD
- **Unrealized FX gain**: 300 SGD

### Verification

```sql
-- Check database directly (via psql or DB client)
SELECT base_currency, quote_currency, rate, rate_date 
FROM fx_rates 
WHERE rate_date = '2026-01-23' 
ORDER BY base_currency, quote_currency;
```

---

## Used by

- [reporting.md](./reporting.md)
- [accounting.md](./accounting.md)
