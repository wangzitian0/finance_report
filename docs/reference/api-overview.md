# API Overview

Finance Report provides a RESTful API built with FastAPI. All endpoints are documented with OpenAPI (Swagger).

## Base URL

```
https://report.zitian.party/api
```

## Interactive Documentation

- **Swagger UI**: [/api/docs](https://report.zitian.party/api/docs)
- **ReDoc**: [/api/redoc](https://report.zitian.party/api/redoc)

## Authentication

!!! note "Coming Soon"
    Authentication is being implemented. Currently, the API is open for demo purposes.

Future authentication will use JWT tokens:

```bash
curl -X POST /api/auth/login \
  -d '{"email": "user@example.com", "password": "secret"}'
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer"
}
```

Use the token in subsequent requests:
```bash
curl -H "Authorization: Bearer <token>" /api/accounts
```

## Response Format

All responses follow a consistent format:

### Success Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Checking Account",
  "type": "ASSET",
  "created_at": "2026-01-10T12:00:00Z"
}
```

### List Response

```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "per_page": 20
}
```

### Error Response

```json
{
  "detail": "Account not found",
  "status_code": 404
}
```

## HTTP Status Codes

| Code | Description |
|------|-------------|
| `200` | Success |
| `201` | Created |
| `204` | No Content (delete) |
| `400` | Bad Request |
| `401` | Unauthorized |
| `404` | Not Found |
| `422` | Validation Error |
| `500` | Server Error |

## Common Parameters

### Pagination

```bash
GET /api/accounts?page=1&per_page=20
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number |
| `per_page` | integer | 20 | Items per page (max: 100) |

### Filtering

```bash
GET /api/journal-entries?status=posted&start_date=2026-01-01
```

### Sorting

```bash
GET /api/accounts?sort=name&order=asc
```

## Data Types

### UUID

All IDs are UUID v4:
```
550e8400-e29b-41d4-a716-446655440000
```

### Dates

ISO 8601 format:
```
2026-01-10              # Date only
2026-01-10T12:30:00Z    # With time (UTC)
```

### Monetary Values

Decimal strings with 2 decimal places:
```json
{
  "amount": "1234.56",
  "currency": "USD"
}
```

!!! warning "Use Strings"
    Always use strings for monetary values to preserve precision.

### Enums

| Field | Values |
|-------|--------|
| `account_type` | ASSET, LIABILITY, EQUITY, INCOME, EXPENSE |
| `direction` | DEBIT, CREDIT |
| `entry_status` | draft, posted, void |
| `source_type` | manual, import, system, reconciliation |
| `match_status` | pending, auto_accepted, pending_review, accepted, rejected, superseded |

## Rate Limiting

!!! info "Current Limits"
    Rate limiting is not currently enforced but may be added in the future.

Expected limits:
- 100 requests per minute per IP
- 1000 requests per hour per user

## Versioning

The API is currently v1. Version is not included in the URL path.

Future versions will use:
```
/api/v2/accounts
```

## Endpoints Summary

### Core Resources

| Resource | Endpoint | Description |
|----------|----------|-------------|
| **Health** | `GET /api/health` | API health check |
| **Accounts** | `/api/accounts` | [Account management](api-accounts.md) |
| **Journal Entries** | `/api/journal-entries` | [Transaction recording](api-journal.md) |
| **Reconciliation** | `/api/reconciliation` | [Bank matching](api-reconciliation.md) |
| **Statements** | `/api/statements` | Statement upload & parsing |
| **Reports** | `/api/reports` | Financial reports |

### Health Check

```bash
curl https://report.zitian.party/api/health
```

```json
{
  "status": "healthy",
  "timestamp": "2026-01-10T17:52:32.225721+00:00"
}
```

## SDK & Libraries

Official SDKs are planned for:

- Python
- TypeScript/JavaScript
- Go

## Next Steps

- [Accounts API](api-accounts.md)
- [Journal Entries API](api-journal.md)
- [Reconciliation API](api-reconciliation.md)
