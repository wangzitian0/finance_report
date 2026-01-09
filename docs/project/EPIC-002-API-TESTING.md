# EPIC-002 API Testing Guide

## Quick Start

### 1. Start the Backend

```bash
cd apps/backend
uv run uvicorn src.main:app --reload
```

The API will be available at `http://localhost:8000`

### 2. View API Documentation

Open your browser and visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Example API Calls

### Create Asset Account (Bank Account)

```bash
curl -X POST "http://localhost:8000/api/accounts" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "DBS Checking Account",
    "code": "1100",
    "type": "ASSET",
    "currency": "SGD",
    "description": "Primary bank account"
  }'
```

### Create Income Account (Salary)

```bash
curl -X POST "http://localhost:8000/api/accounts" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Salary Income",
    "code": "4100",
    "type": "INCOME",
    "currency": "SGD"
  }'
```

### List All Accounts

```bash
curl "http://localhost:8000/api/accounts"
```

### Get Account Details with Balance

```bash
# Replace {account_id} with actual UUID from create response
curl "http://localhost:8000/api/accounts/{account_id}"
```

### Create Journal Entry (Salary Deposit)

```bash
curl -X POST "http://localhost:8000/api/journal-entries" \
  -H "Content-Type: application/json" \
  -d '{
    "entry_date": "2026-01-10",
    "memo": "January 2026 Salary",
    "source_type": "manual",
    "lines": [
      {
        "account_id": "BANK_ACCOUNT_UUID_HERE",
        "direction": "DEBIT",
        "amount": "5000.00",
        "currency": "SGD"
      },
      {
        "account_id": "SALARY_ACCOUNT_UUID_HERE",
        "direction": "CREDIT",
        "amount": "5000.00",
        "currency": "SGD"
      }
    ]
  }'
```

### List Journal Entries

```bash
# All entries
curl "http://localhost:8000/api/journal-entries"

# Filter by status
curl "http://localhost:8000/api/journal-entries?status_filter=draft"

# Filter by date range
curl "http://localhost:8000/api/journal-entries?start_date=2026-01-01&end_date=2026-01-31"
```

### Post Journal Entry (Draft → Posted)

```bash
# Replace {entry_id} with actual UUID
curl -X POST "http://localhost:8000/api/journal-entries/{entry_id}/post"
```

### Void Journal Entry

```bash
curl -X POST "http://localhost:8000/api/journal-entries/{entry_id}/void" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Incorrect amount entered"
  }'
```

## Testing Workflow

### Scenario: Recording a Salary Payment

1. **Create Accounts**
   ```bash
   # Create bank account
   BANK_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/accounts" \
     -H "Content-Type: application/json" \
     -d '{"name":"DBS Bank","type":"ASSET","currency":"SGD"}')
   
   BANK_ID=$(echo $BANK_RESPONSE | jq -r '.id')
   
   # Create salary account
   SALARY_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/accounts" \
     -H "Content-Type: application/json" \
     -d '{"name":"Salary Income","type":"INCOME","currency":"SGD"}')
   
   SALARY_ID=$(echo $SALARY_RESPONSE | jq -r '.id')
   ```

2. **Create Draft Entry**
   ```bash
   ENTRY_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/journal-entries" \
     -H "Content-Type: application/json" \
     -d "{
       \"entry_date\": \"2026-01-10\",
       \"memo\": \"January Salary\",
       \"lines\": [
         {\"account_id\":\"$BANK_ID\",\"direction\":\"DEBIT\",\"amount\":\"5000.00\",\"currency\":\"SGD\"},
         {\"account_id\":\"$SALARY_ID\",\"direction\":\"CREDIT\",\"amount\":\"5000.00\",\"currency\":\"SGD\"}
       ]
     }")
   
   ENTRY_ID=$(echo $ENTRY_RESPONSE | jq -r '.id')
   ```

3. **Post the Entry**
   ```bash
   curl -X POST "http://localhost:8000/api/journal-entries/$ENTRY_ID/post"
   ```

4. **Verify Balances**
   ```bash
   # Check bank account balance (should be 5000.00)
   curl "http://localhost:8000/api/accounts/$BANK_ID"
   
   # Check salary account balance (should be -5000.00)
   curl "http://localhost:8000/api/accounts/$SALARY_ID"
   ```

## Validation Tests

### Test 1: Unbalanced Entry (Should Fail)

```bash
curl -X POST "http://localhost:8000/api/journal-entries" \
  -H "Content-Type: application/json" \
  -d '{
    "entry_date": "2026-01-10",
    "memo": "Unbalanced test",
    "lines": [
      {"account_id":"'$BANK_ID'","direction":"DEBIT","amount":"100.00","currency":"SGD"},
      {"account_id":"'$SALARY_ID'","direction":"CREDIT","amount":"90.00","currency":"SGD"}
    ]
  }'
```

Expected: 422 error with message "Journal entry not balanced"

### Test 2: Single Line Entry (Should Fail)

```bash
curl -X POST "http://localhost:8000/api/journal-entries" \
  -H "Content-Type: application/json" \
  -d '{
    "entry_date": "2026-01-10",
    "memo": "Single line test",
    "lines": [
      {"account_id":"'$BANK_ID'","direction":"DEBIT","amount":"100.00","currency":"SGD"}
    ]
  }'
```

Expected: 422 error with message about minimum 2 lines

### Test 3: Post Non-Draft Entry (Should Fail)

```bash
# Try to post an already posted entry
curl -X POST "http://localhost:8000/api/journal-entries/$ENTRY_ID/post"
```

Expected: 400 error "Can only post draft entries"

## Health Check

```bash
curl "http://localhost:8000/health"
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2026-01-10T..."
}
```

## Common Issues

### Issue: Account not found
**Solution**: Make sure you're using valid UUIDs from account creation responses

### Issue: Entry not balanced
**Solution**: Ensure sum(DEBIT amounts) == sum(CREDIT amounts)

### Issue: Cannot post entry
**Solution**: Check entry status is "draft" and all accounts are active

### Issue: Database connection error
**Solution**: Ensure PostgreSQL is running via `docker compose up -d`

## Next Steps

1. Test all endpoints via Swagger UI
2. Verify accounting equation holds after multiple entries
3. Test void/reversal functionality
4. Integrate with frontend (EPIC-002 continuation)
