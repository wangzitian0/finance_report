# FX Rate Seeding Instructions

This document explains how to seed FX rates for testing FX gain/loss calculations.

## Script Usage

The script `scripts/seed_fx_rates.py` seeds the `fx_rates` table with test data:

### Local Development

```bash
cd apps/backend
uv run python ../../scripts/seed_fx_rates.py --env local
```

### Staging Environment

```bash
# First, get the staging DATABASE_URL from Dokploy/Vault
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  python scripts/seed_fx_rates.py --env staging

# Or run from backend directory:
cd apps/backend
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  uv run python ../../scripts/seed_fx_rates.py --env staging
```

## Test Data Seeded

The script seeds the following FX rates for 2026-01-23:

| Base | Quote | Rate | Description |
|-------|--------|-------|-------------|
| USD | USD | 1.000000 | Base rate |
| SGD | SGD | 1.000000 | Base rate |
| EUR | EUR | 1.000000 | Base rate |
| USD | SGD | 1.280000 | 1 USD = 1.28 SGD |
| USD | EUR | 0.852000 | 1 USD = 0.852 EUR |
| SGD | USD | 0.781250 | 1 SGD = 1/1.28 USD |
| EUR | USD | 1.173709 | 1 EUR = 1/0.852 USD |

## Expected FX Calculation

With your test data:
- **Historical cost**: 10,000 USD @ 1.25 = 12,500 SGD
- **Current value**: 10,000 USD @ 1.28 = 12,800 SGD  
- **Unrealized FX gain**: 300 SGD

## Getting Staging Database URL

To get the DATABASE_URL for staging:

1. **Via Dokploy API**:
   ```bash
   curl -H "Authorization: Bearer $DOKPLOY_API_KEY" \
        "https://staging.dokploy.com/api/apps?search=finance-report-backend-staging"
   ```

2. **Via Vault** (if you have access):
   ```bash
   # Connect to staging VPS
   ssh root@$STAGING_VPS_HOST
   
   # Get secrets from Vault
   vault kv get -field=DATABASE_URL secret/finance_report/staging
   ```

3. **Via Environment** (if running on staging server):
   ```bash
   echo $DATABASE_URL
   ```

## Verification

After seeding, verify the FX rates are available:

1. **Check database directly**:
   ```sql
   SELECT base_currency, quote_currency, rate, rate_date 
   FROM fx_rates 
   WHERE rate_date = '2026-01-23' 
   ORDER BY base_currency, quote_currency;
   ```

2. **Via API** (when backend is running):
   ```bash
   curl -H "X-User-Id: $USER_ID" \
        "http://localhost:8000/api/v1/market-data/fx-rates?date=2026-01-23"
   ```

3. **Check balance sheet**:
   - Login to the frontend
   - Navigate to Balance Sheet report
   - Verify the USD Savings account shows:
     - Historical cost: 12,500 SGD
     - Current value: 12,800 SGD
     - Unrealized FX gain: 300 SGD

## Troubleshooting

### Connection Issues
- Ensure DATABASE_URL uses `postgresql+asyncpg://` for async support
- Verify the database host is accessible from your location
- Check if SSL certificates are required

### Permission Issues
- Ensure the database user has INSERT/SELECT permissions on fx_rates table
- Check if there are any RLS (Row Level Security) policies

### Missing Table
- Run migrations: `moon run backend:migrate`
- Verify table exists: `\dt fx_rates` in psql