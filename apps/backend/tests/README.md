# Backend Tests

Test suite for the Finance Report backend, organized by domain.

> **SSOT Alignment**: Test directories are named to match [SSOT domain documents](../../../docs/ssot/README.md#-module-mapping-cross-layer-alignment).

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
├── infra/               # Config, logging, rate limiting, migrations
├── market_data/         # Foreign exchange rates, stock prices
├── reconciliation/      # Bank statement matching engine
└── reporting/           # Financial reports (balance sheet, P&L)
```

## Running Tests

```bash
# Run all tests (requires DB)
moon run :test

# Run specific domain
uv run pytest tests/accounting/ -v

# Run without DB (unit tests only)
uv run pytest tests/infra/ tests/ai/test_models_repr.py -v

# Run with coverage
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## SSOT ↔ Code Mapping

Test directories are aligned with SSOT documents. When code paths differ from SSOT naming, this table shows the mapping:

| Test Dir | SSOT Doc | Backend Router | Backend Service |
|----------|----------|----------------|-----------------|
| `accounting/` | [accounting.md](../../../docs/ssot/accounting.md) | `journal.py`, `accounts.py` | `accounting.py` |
| `ai/` | [ai.md](../../../docs/ssot/ai.md) | `chat.py`, `ai_models.py` | `ai_advisor.py` |
| `assets/` | *(planned)* | `assets.py` | `assets.py` |
| `auth/` | [auth.md](../../../docs/ssot/auth.md) | `auth.py`, `users.py` | — |
| `extraction/` | [extraction.md](../../../docs/ssot/extraction.md) | `statements.py` | `extraction.py` |
| `infra/` | [development.md](../../../docs/ssot/development.md) | — | — |
| `market_data/` | [market_data.md](../../../docs/ssot/market_data.md) | — | `fx.py` |
| `reconciliation/` | [reconciliation.md](../../../docs/ssot/reconciliation.md) | `reconciliation.py` | `reconciliation.py` |
| `reporting/` | [reporting.md](../../../docs/ssot/reporting.md) | `reports.py` | `reporting.py` |

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
