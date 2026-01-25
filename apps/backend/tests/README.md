# Backend Tests

Test suite for the Finance Report backend, organized by domain.

## Directory Structure

```
tests/
├── conftest.py          # Shared fixtures (db, client, test_user)
├── fixtures/            # Test data files (JSON fixtures)
│
├── accounting/          # Double-entry bookkeeping, journal entries
├── ai/                  # AI advisor, chat, OpenRouter integration
├── api/                 # Generic API endpoint tests
├── assets/              # Asset tracking and management
├── auth/                # Authentication, users, sessions
├── extraction/          # PDF parsing, statement upload, storage
├── fx/                  # Foreign exchange rates
├── infra/               # Config, logging, rate limiting, migrations
├── reconciliation/      # Bank statement matching engine
└── reporting/           # Financial reports (balance sheet, P&L)
```

## Running Tests

```bash
# Run all tests (requires DB)
moon run backend:test

# Run specific domain
uv run pytest tests/accounting/ -v

# Run without DB (unit tests only)
uv run pytest tests/infra/ tests/ai/test_models_repr.py -v

# Run with coverage
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## Domain Mapping

| Domain | Source Files | Key Concepts |
|--------|-------------|--------------|
| `accounting/` | `services/accounting.py`, `routers/journal.py` | Journal entries, account balances, double-entry |
| `ai/` | `services/ai_advisor.py`, `routers/chat.py` | AI chat, OpenRouter, streaming |
| `assets/` | `services/assets.py`, `routers/assets.py` | Asset tracking, valuation |
| `auth/` | `auth.py`, `security.py`, `routers/auth.py` | JWT, sessions, user management |
| `extraction/` | `services/extraction.py`, `routers/statements.py` | PDF parsing, S3 storage |
| `fx/` | `services/fx.py` | Exchange rates, currency conversion |
| `infra/` | `config.py`, `logger.py`, `rate_limit.py` | Infrastructure, configuration |
| `reconciliation/` | `services/reconciliation.py` | Matching engine, scoring |
| `reporting/` | `services/reporting.py`, `routers/reports.py` | Financial statements |

## Fixtures

Shared fixtures in `conftest.py`:

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db_engine` | function | Creates test database, drops after test |
| `db` | function | Async SQLAlchemy session |
| `test_user` | function | Creates a test user for auth |
| `client` | function | Authenticated AsyncClient |
| `public_client` | function | Unauthenticated AsyncClient |

Test data in `fixtures/`:
- `*.json` - Parsed bank statement examples for extraction tests
