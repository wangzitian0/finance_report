# Accounts API

Manage the Chart of Accounts.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/accounts` | List all accounts |
| `POST` | `/api/accounts` | Create account |
| `GET` | `/api/accounts/{id}` | Get account |
| `PUT` | `/api/accounts/{id}` | Update account |
| `GET` | `/api/accounts/{id}/balance` | Get account balance |
| `GET` | `/api/accounts/balances` | Get all balances |

## List Accounts

```http
GET /api/accounts
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `type` | string | Filter by account type |
| `is_active` | boolean | Filter by active status |
| `page` | integer | Page number |
| `per_page` | integer | Items per page |

### Response

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Chase Checking",
      "type": "ASSET",
      "currency": "USD",
      "description": "Primary checking account",
      "is_active": true,
      "parent_id": null,
      "created_at": "2026-01-10T12:00:00Z",
      "updated_at": "2026-01-10T12:00:00Z"
    }
  ],
  "total": 15,
  "page": 1,
  "per_page": 20
}
```

### Example

```bash
# List all asset accounts
curl "https://report.zitian.party/api/accounts?type=ASSET"
```

## Create Account

```http
POST /api/accounts
```

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Account name (unique) |
| `type` | enum | ✅ | ASSET, LIABILITY, EQUITY, INCOME, EXPENSE |
| `currency` | string | ❌ | ISO 4217 code (default: USD) |
| `description` | string | ❌ | Optional description |
| `parent_id` | UUID | ❌ | Parent account for hierarchy |

### Request

```json
{
  "name": "Savings Account",
  "type": "ASSET",
  "currency": "USD",
  "description": "Emergency fund"
}
```

### Response

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "name": "Savings Account",
  "type": "ASSET",
  "currency": "USD",
  "description": "Emergency fund",
  "is_active": true,
  "parent_id": null,
  "created_at": "2026-01-10T12:00:00Z",
  "updated_at": "2026-01-10T12:00:00Z"
}
```

### Example

```bash
curl -X POST https://report.zitian.party/api/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Investment Account",
    "type": "ASSET",
    "description": "Brokerage account"
  }'
```

## Get Account

```http
GET /api/accounts/{id}
```

### Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Chase Checking",
  "type": "ASSET",
  "currency": "USD",
  "description": "Primary checking account",
  "is_active": true,
  "parent_id": null,
  "created_at": "2026-01-10T12:00:00Z",
  "updated_at": "2026-01-10T12:00:00Z"
}
```

### Errors

| Code | Description |
|------|-------------|
| `404` | Account not found |

## Update Account

```http
PUT /api/accounts/{id}
```

### Request Body

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Updated name |
| `description` | string | Updated description |
| `is_active` | boolean | Active status |

!!! note "Type Cannot Change"
    Account type cannot be changed after creation.

### Request

```json
{
  "description": "Primary checking - Chase Bank",
  "is_active": true
}
```

### Example

```bash
# Deactivate an account
curl -X PUT https://report.zitian.party/api/accounts/{id} \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

## Get Account Balance

```http
GET /api/accounts/{id}/balance
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `as_of` | date | Balance as of date (default: today) |

### Response

```json
{
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "balance": "5234.50",
  "currency": "USD",
  "as_of": "2026-01-10"
}
```

### Example

```bash
# Get balance as of specific date
curl "https://report.zitian.party/api/accounts/{id}/balance?as_of=2025-12-31"
```

## Get All Balances

```http
GET /api/accounts/balances
```

### Response

```json
{
  "balances": [
    {
      "account_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Chase Checking",
      "type": "ASSET",
      "balance": "5234.50",
      "currency": "USD"
    },
    {
      "account_id": "660e8400-e29b-41d4-a716-446655440001",
      "name": "Savings Account",
      "type": "ASSET",
      "balance": "12500.00",
      "currency": "USD"
    }
  ],
  "as_of": "2026-01-10"
}
```

## Account Schema

```typescript
interface Account {
  id: string;           // UUID
  name: string;         // Unique name
  type: AccountType;    // ASSET | LIABILITY | EQUITY | INCOME | EXPENSE
  currency: string;     // ISO 4217 (e.g., "USD")
  description?: string; // Optional description
  is_active: boolean;   // Can be used in entries
  parent_id?: string;   // UUID of parent account
  created_at: string;   // ISO 8601 datetime
  updated_at: string;   // ISO 8601 datetime
}

type AccountType = "ASSET" | "LIABILITY" | "EQUITY" | "INCOME" | "EXPENSE";
```

## Error Codes

| Status | Code | Description |
|--------|------|-------------|
| 400 | `INVALID_TYPE` | Invalid account type |
| 400 | `DUPLICATE_NAME` | Account name already exists |
| 404 | `NOT_FOUND` | Account not found |
| 409 | `HAS_ENTRIES` | Cannot delete account with entries |
