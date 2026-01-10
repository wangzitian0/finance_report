# Journal Entries API

Record and manage financial transactions.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/journal-entries` | List entries |
| `POST` | `/api/journal-entries` | Create entry |
| `GET` | `/api/journal-entries/{id}` | Get entry |
| `PUT` | `/api/journal-entries/{id}` | Update draft entry |
| `POST` | `/api/journal-entries/{id}/post` | Post entry |
| `POST` | `/api/journal-entries/{id}/void` | Void entry |

## List Entries

```http
GET /api/journal-entries
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | enum | draft, posted, void |
| `start_date` | date | Filter from date |
| `end_date` | date | Filter to date |
| `account_id` | UUID | Filter by account |
| `source_type` | enum | manual, import, system, reconciliation |
| `page` | integer | Page number |
| `per_page` | integer | Items per page |

### Response

```json
{
  "items": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440000",
      "entry_date": "2026-01-10",
      "memo": "January salary",
      "status": "posted",
      "source_type": "manual",
      "lines": [
        {
          "id": "880e8400-e29b-41d4-a716-446655440001",
          "account_id": "550e8400-e29b-41d4-a716-446655440000",
          "account_name": "Chase Checking",
          "direction": "DEBIT",
          "amount": "5000.00",
          "currency": "USD"
        },
        {
          "id": "880e8400-e29b-41d4-a716-446655440002",
          "account_id": "660e8400-e29b-41d4-a716-446655440001",
          "account_name": "Salary",
          "direction": "CREDIT",
          "amount": "5000.00",
          "currency": "USD"
        }
      ],
      "created_at": "2026-01-10T12:00:00Z",
      "updated_at": "2026-01-10T12:00:00Z"
    }
  ],
  "total": 100,
  "page": 1,
  "per_page": 20
}
```

### Example

```bash
# List posted entries for January
curl "https://report.zitian.party/api/journal-entries?status=posted&start_date=2026-01-01&end_date=2026-01-31"
```

## Create Entry

```http
POST /api/journal-entries
```

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `entry_date` | date | ✅ | Transaction date |
| `memo` | string | ❌ | Description |
| `lines` | array | ✅ | Journal lines (min 2) |
| `auto_post` | boolean | ❌ | Post immediately (default: false) |

#### Line Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `account_id` | UUID | ✅ | Target account |
| `direction` | enum | ✅ | DEBIT or CREDIT |
| `amount` | string | ✅ | Decimal amount |
| `currency` | string | ❌ | Currency (default: USD) |

### Request

```json
{
  "entry_date": "2026-01-10",
  "memo": "Grocery shopping at Whole Foods",
  "lines": [
    {
      "account_id": "660e8400-e29b-41d4-a716-446655440001",
      "direction": "DEBIT",
      "amount": "150.00",
      "currency": "USD"
    },
    {
      "account_id": "550e8400-e29b-41d4-a716-446655440000",
      "direction": "CREDIT",
      "amount": "150.00",
      "currency": "USD"
    }
  ]
}
```

### Response

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "entry_date": "2026-01-10",
  "memo": "Grocery shopping at Whole Foods",
  "status": "draft",
  "source_type": "manual",
  "lines": [...],
  "created_at": "2026-01-10T12:00:00Z",
  "updated_at": "2026-01-10T12:00:00Z"
}
```

### Validation Rules

!!! warning "Balance Required"
    Total debits must equal total credits (tolerance: $0.01)

```json
// ❌ Invalid - unbalanced
{
  "lines": [
    {"direction": "DEBIT", "amount": "100.00"},
    {"direction": "CREDIT", "amount": "99.00"}
  ]
}

// ✅ Valid - balanced
{
  "lines": [
    {"direction": "DEBIT", "amount": "100.00"},
    {"direction": "CREDIT", "amount": "100.00"}
  ]
}
```

## Get Entry

```http
GET /api/journal-entries/{id}
```

### Response

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "entry_date": "2026-01-10",
  "memo": "Grocery shopping at Whole Foods",
  "status": "posted",
  "source_type": "manual",
  "lines": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440001",
      "account_id": "660e8400-e29b-41d4-a716-446655440001",
      "account_name": "Groceries",
      "direction": "DEBIT",
      "amount": "150.00",
      "currency": "USD"
    },
    {
      "id": "880e8400-e29b-41d4-a716-446655440002",
      "account_id": "550e8400-e29b-41d4-a716-446655440000",
      "account_name": "Chase Checking",
      "direction": "CREDIT",
      "amount": "150.00",
      "currency": "USD"
    }
  ],
  "created_at": "2026-01-10T12:00:00Z",
  "updated_at": "2026-01-10T12:00:00Z"
}
```

## Update Entry

```http
PUT /api/journal-entries/{id}
```

!!! note "Draft Only"
    Only draft entries can be updated. Posted entries must be voided and recreated.

### Request

```json
{
  "memo": "Updated memo",
  "entry_date": "2026-01-11",
  "lines": [...]
}
```

## Post Entry

```http
POST /api/journal-entries/{id}/post
```

Finalizes a draft entry. Posted entries affect account balances.

### Response

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "status": "posted",
  "posted_at": "2026-01-10T12:30:00Z",
  ...
}
```

### Errors

| Code | Description |
|------|-------------|
| 400 | Entry already posted |
| 400 | Entry is void |
| 400 | Entry is unbalanced |
| 400 | Account is inactive |

## Void Entry

```http
POST /api/journal-entries/{id}/void
```

Cancels a posted entry by creating a reversal entry.

### Request

```json
{
  "reason": "Duplicate entry"
}
```

### Response

```json
{
  "voided_entry": {
    "id": "770e8400-e29b-41d4-a716-446655440000",
    "status": "void",
    ...
  },
  "reversal_entry": {
    "id": "990e8400-e29b-41d4-a716-446655440003",
    "memo": "Void: Grocery shopping at Whole Foods (Duplicate entry)",
    "status": "posted",
    "source_type": "system",
    ...
  }
}
```

### Errors

| Code | Description |
|------|-------------|
| 400 | Entry not posted |
| 400 | Entry already void |

## Entry Schema

```typescript
interface JournalEntry {
  id: string;              // UUID
  entry_date: string;      // ISO date (YYYY-MM-DD)
  memo?: string;           // Description
  status: EntryStatus;     // draft | posted | void
  source_type: SourceType; // manual | import | system | reconciliation
  lines: JournalLine[];    // Min 2 lines
  created_at: string;      // ISO 8601 datetime
  updated_at: string;      // ISO 8601 datetime
  posted_at?: string;      // When posted
  voided_at?: string;      // When voided
  void_reason?: string;    // Reason for voiding
}

interface JournalLine {
  id: string;              // UUID
  account_id: string;      // UUID
  account_name?: string;   // Included in responses
  direction: Direction;    // DEBIT | CREDIT
  amount: string;          // Decimal string
  currency: string;        // ISO 4217
}

type EntryStatus = "draft" | "posted" | "void";
type SourceType = "manual" | "import" | "system" | "reconciliation";
type Direction = "DEBIT" | "CREDIT";
```

## Error Codes

| Status | Code | Description |
|--------|------|-------------|
| 400 | `UNBALANCED` | Debits don't equal credits |
| 400 | `TOO_FEW_LINES` | Less than 2 lines |
| 400 | `INVALID_STATUS` | Invalid status transition |
| 400 | `INACTIVE_ACCOUNT` | Account is deactivated |
| 404 | `NOT_FOUND` | Entry not found |
