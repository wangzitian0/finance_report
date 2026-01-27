# Market Data SSOT

> **SSOT Key**: `market_data`
> **Core Definition**: FX rates and stock prices data sources, sync schedule, and caching strategy.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Sync Logic** | `apps/backend/src/services/market_data.py` | Data fetching |
| **Rate Storage** | `fx_rates` table | Historical rates |
| **Price Storage** | `stock_prices` table | Historical prices |

---

## 2. Data Sources

### Primary: yfinance
- **Type**: Python library (free)
- **Data**: FX rates, stock prices
- **Rate Limit**: Unofficial, ~2000 requests/hour
- **Fallback**: Twelve Data

### Secondary: Twelve Data
- **Type**: REST API (API key required)
- **Data**: FX rates, stock prices
- **Rate Limit**: 800 requests/day (free tier)
- **Use Case**: Fallback when yfinance fails

### Source Priority
```python
MARKET_DATA_SOURCES = [
    {"name": "yfinance", "priority": 1},
    {"name": "twelve_data", "priority": 2},
]

async def get_fx_rate(base: str, quote: str, date: date) -> Decimal:
    for source in sorted(MARKET_DATA_SOURCES, key=lambda x: x["priority"]):
        try:
            return await fetch_rate(source["name"], base, quote, date)
        except SourceError:
            continue
    raise MarketDataUnavailable(f"No source available for {base}/{quote}")
```

---

## 3. Sync Schedule

### FX Rates
- **Frequency**: Daily at 08:00 UTC
- **Pairs**: USD/SGD, USD/CNY, USD/HKD, EUR/USD, GBP/USD
- **History**: Keep 2 years of daily rates

### Stock Prices
- **Frequency**: Daily at 22:00 UTC (after US market close)
- **Symbols**: User-configured holdings
- **History**: Keep 2 years of daily prices

### Sync Workflow (via Activepieces)
```yaml
trigger:
  type: schedule
  cron: "0 8 * * *"  # Daily 08:00 UTC

actions:
  - name: fetch_fx_rates
    endpoint: POST /api/v1/market-data/sync/fx
  - name: fetch_stock_prices
    endpoint: POST /api/v1/market-data/sync/stocks
```

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
    UNIQUE(symbol, price_date)
);

CREATE INDEX idx_stock_prices_lookup 
    ON stock_prices(symbol, price_date);
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

### Redis Cache
- **Key format**: `fx:{base}:{quote}:{date}`
- **TTL**: 24 hours
- **Fallback**: Database lookup if cache miss

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
    
    # Fetch from source
    rate = await fetch_from_source(base, quote, date)
    await save_to_db(rate)
    await redis.setex(cache_key, 86400, str(rate))
    return rate
```

---

## 7. Design Constraints

### ✅ Recommended Patterns
- **Pattern A**: Always store source name with rate for auditability
- **Pattern B**: Use Decimal(6) for rates, Decimal(2) for converted amounts
- **Pattern C**: Prefer historical rates over real-time for reporting

### ⛔ Prohibited Patterns
- **Anti-pattern A**: **NEVER** hardcode exchange rates
- **Anti-pattern B**: **NEVER** use single source without fallback

---

## 8. Error Handling

| Error | Action |
|-------|--------|
| Source timeout | Retry 3x, then try next source |
| Missing rate for date | Use previous day's rate |
| All sources failed | Log alert, use last known rate |

---

## 9. Verification

| Behavior | Test Method | Status |
|----------|-------------|--------|
| yfinance fetch | `test_yfinance_fx` | ⏳ Pending |
| Twelve Data fallback | `test_twelve_data_fallback` | ⏳ Pending |
| Cache hit/miss | `test_fx_cache` | ⏳ Pending |
| Missing rate handling | `test_missing_rate` | ⏳ Pending |

---

## 10. FX Rate Seeding (Test Data)

For testing FX gain/loss calculations, use the seeding script.

### Script Usage

```bash
# Local development (from repo root)
uv run python scripts/seed_fx_rates.py --env local

# Staging (requires DATABASE_URL)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  uv run python scripts/seed_fx_rates.py --env staging
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
