# Reconciliation API

Match bank transactions with journal entries.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/reconciliation/run` | Run matching |
| `GET` | `/api/reconciliation/pending` | Get pending reviews |
| `POST` | `/api/reconciliation/matches/{id}/accept` | Accept match |
| `POST` | `/api/reconciliation/matches/{id}/reject` | Reject match |
| `POST` | `/api/reconciliation/batch-accept` | Batch accept |
| `GET` | `/api/reconciliation/stats` | Get statistics |
| `GET` | `/api/reconciliation/unmatched` | Get unmatched |

## Run Matching

```http
POST /api/reconciliation/run
```

Executes the matching algorithm for a statement or account.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `statement_id` | UUID | ❌* | Statement to reconcile |
| `account_id` | UUID | ❌* | Account to reconcile |
| `start_date` | date | ❌ | Filter from date |
| `end_date` | date | ❌ | Filter to date |

*Either `statement_id` or `account_id` is required.

### Request

```json
{
  "statement_id": "aa0e8400-e29b-41d4-a716-446655440000"
}
```

### Response

```json
{
  "run_id": "bb0e8400-e29b-41d4-a716-446655440001",
  "status": "completed",
  "summary": {
    "total_transactions": 50,
    "auto_accepted": 35,
    "pending_review": 10,
    "unmatched": 5
  },
  "completed_at": "2026-01-10T12:30:00Z"
}
```

## Get Pending Reviews

```http
GET /api/reconciliation/pending
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `account_id` | UUID | Filter by account |
| `min_score` | integer | Minimum score (default: 60) |
| `max_score` | integer | Maximum score (default: 84) |
| `page` | integer | Page number |
| `per_page` | integer | Items per page |

### Response

```json
{
  "items": [
    {
      "id": "cc0e8400-e29b-41d4-a716-446655440002",
      "status": "pending_review",
      "score": 78,
      "score_breakdown": {
        "amount": 100,
        "date": 100,
        "description": 45,
        "business": 80,
        "history": 60
      },
      "bank_transaction": {
        "id": "dd0e8400-e29b-41d4-a716-446655440003",
        "date": "2026-01-06",
        "description": "WHOLE FOODS #1234",
        "amount": "87.50",
        "type": "debit"
      },
      "journal_entries": [
        {
          "id": "770e8400-e29b-41d4-a716-446655440000",
          "entry_date": "2026-01-06",
          "memo": "Groceries - Whole Foods",
          "total_amount": "87.50"
        }
      ],
      "created_at": "2026-01-10T12:00:00Z"
    }
  ],
  "total": 10,
  "page": 1,
  "per_page": 20
}
```

## Accept Match

```http
POST /api/reconciliation/matches/{id}/accept
```

### Response

```json
{
  "id": "cc0e8400-e29b-41d4-a716-446655440002",
  "status": "accepted",
  "accepted_at": "2026-01-10T12:35:00Z"
}
```

### Errors

| Code | Description |
|------|-------------|
| 400 | Match already processed |
| 404 | Match not found |

## Reject Match

```http
POST /api/reconciliation/matches/{id}/reject
```

### Request

```json
{
  "reason": "Wrong transaction - different payee"
}
```

### Response

```json
{
  "id": "cc0e8400-e29b-41d4-a716-446655440002",
  "status": "rejected",
  "reject_reason": "Wrong transaction - different payee",
  "rejected_at": "2026-01-10T12:36:00Z"
}
```

## Batch Accept

```http
POST /api/reconciliation/batch-accept
```

Accept all pending matches above a score threshold.

### Request

```json
{
  "min_score": 80,
  "account_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Response

```json
{
  "accepted_count": 25,
  "match_ids": [
    "cc0e8400-e29b-41d4-a716-446655440002",
    "cc0e8400-e29b-41d4-a716-446655440003",
    ...
  ]
}
```

## Get Statistics

```http
GET /api/reconciliation/stats
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `account_id` | UUID | Filter by account |
| `start_date` | date | Stats from date |
| `end_date` | date | Stats to date |

### Response

```json
{
  "total_transactions": 150,
  "reconciled": 142,
  "pending_review": 5,
  "unmatched": 3,
  "reconciliation_rate": 94.67,
  "average_score": 88.5,
  "score_distribution": {
    "85_100": 120,
    "60_84": 22,
    "0_59": 8
  },
  "by_account": [
    {
      "account_id": "550e8400-e29b-41d4-a716-446655440000",
      "account_name": "Chase Checking",
      "reconciled": 100,
      "pending": 3,
      "unmatched": 2
    }
  ]
}
```

## Get Unmatched

```http
GET /api/reconciliation/unmatched
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `account_id` | UUID | Filter by account |
| `type` | enum | bank_transaction, journal_entry |
| `page` | integer | Page number |
| `per_page` | integer | Items per page |

### Response

```json
{
  "items": [
    {
      "type": "bank_transaction",
      "transaction": {
        "id": "ee0e8400-e29b-41d4-a716-446655440004",
        "date": "2026-01-08",
        "description": "BANK FEE",
        "amount": "15.00",
        "type": "debit"
      },
      "suggested_action": "create_entry",
      "suggested_accounts": [
        {
          "id": "ff0e8400-e29b-41d4-a716-446655440005",
          "name": "Bank Fees",
          "confidence": 0.85
        }
      ]
    }
  ],
  "total": 3,
  "page": 1,
  "per_page": 20
}
```

## Match Schema

```typescript
interface ReconciliationMatch {
  id: string;                    // UUID
  status: MatchStatus;
  score: number;                 // 0-100
  score_breakdown: ScoreBreakdown;
  bank_transaction: BankTransaction;
  journal_entries: JournalEntry[];
  version: number;               // For optimistic locking
  superseded_by_id?: string;     // If replaced
  created_at: string;
  updated_at: string;
  accepted_at?: string;
  rejected_at?: string;
  reject_reason?: string;
}

interface ScoreBreakdown {
  amount: number;      // 0-100, weight 40%
  date: number;        // 0-100, weight 25%
  description: number; // 0-100, weight 20%
  business: number;    // 0-100, weight 10%
  history: number;     // 0-100, weight 5%
}

type MatchStatus = 
  | "pending"
  | "auto_accepted"
  | "pending_review"
  | "accepted"
  | "rejected"
  | "superseded";
```

## Scoring Details

| Dimension | Weight | 100 Score | 0 Score |
|-----------|--------|-----------|---------|
| **Amount** | 40% | Exact match | >$50 difference |
| **Date** | 25% | Same day | >30 days apart |
| **Description** | 20% | Exact text match | No similarity |
| **Business** | 10% | Valid account types | Type mismatch |
| **History** | 5% | Known pattern | New payee |

### Thresholds

| Score | Action |
|-------|--------|
| ≥ 85 | Auto-accept |
| 60-84 | Pending review |
| < 60 | Unmatched |

!!! note "Environment Override"
    Thresholds can be configured via environment variables:
    
    - `RECONCILIATION_AUTO_ACCEPT_THRESHOLD`
    - `RECONCILIATION_REVIEW_THRESHOLD`

## Error Codes

| Status | Code | Description |
|--------|------|-------------|
| 400 | `ALREADY_PROCESSED` | Match already accepted/rejected |
| 400 | `SUPERSEDED` | Match was replaced |
| 404 | `NOT_FOUND` | Match not found |
| 409 | `VERSION_CONFLICT` | Concurrent modification |
