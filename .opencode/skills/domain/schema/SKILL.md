---
name: schema
description: PostgreSQL database schema, table structures, relationships, and migration rules. Use this skill when working with SQLAlchemy models, Alembic migrations, or database design.
---

# Database Schema

> **Core Definition**: PostgreSQL table structures, the data-layering model, and
> migration/versioning rules.
> **SSOT**: [`docs/ssot/schema.md`](../../../../docs/ssot/schema.md) is authoritative.
> The full table/column/enum/index inventory is generated, not hand-maintained
> here — see the [Generated DB Schema Reference](../../../../docs/reference/db-schema.md)
> (`python tools/generate_db_schema_reference.py`).

## Data Layering (DIM / ODS / DWD / DWM / DWS / ADS)

- **Account is a DIM, conformed at DWD.** `account_id` is assigned when a DWD
  fact is built (`transaction_classification.account_id`,
  `journal_lines.account_id`, `statement_summaries.account_id`).
- **DWM/DWS/ADS resolve dimensions from DWD/DIM, never from ODS.** Matching,
  transfer logic, summaries, and reports must not reach back to a source-file row
  for account authority.
- **No reference data in code.** Non-user reference data that affects ADS lives
  in DIM tables or generated/config-owned contracts, not hard-coded constants.
- The legacy `bank_statement*` ODS tables and Layer-0 read path were **removed**
  (EPIC-011 Stage 3); transfer detection resolves custody from
  `statement_summaries` via `resolve_custody_account_id`.

## Append-Only Fact Versioning (Axiom A)

A stored *fact* (the recorded value of a financial quantity) is never edited in
place. Corrections append a new version and supersede the prior one; the live
value is the head of the chain.

- **Version-bearing unit**: the fact row carries a `version` integer plus a
  self-referential `superseded_by_id` (as on `reconciliation_matches`;
  `transaction_classification` uses the `superseded_by_id` chain alone). Not
  bitemporal `valid_from`/`valid_to`, not a separate version table.
- **Current head**: `superseded_by_id IS NULL`. Enforce key uniqueness with a
  **partial unique index over the head** (`WHERE superseded_by_id IS NULL`) so
  history rows accumulate freely. Default reads/aggregations filter to the head.
- **Fact vs. review-state**: append-only applies to *facts*. Mutable working
  state (status transitions, notes, reminders) may stay editable in place.
- First applied instance: `manual_valuation_snapshots` (ODS) — a re-submitted
  `(component_type, source, as_of_date)` appends a new version. See
  [EPIC-011 AC11.19](../../../../docs/project/EPIC-011.asset-lifecycle.md), #918.

## Core Entities

- **Users**, **Accounts** (chart of accounts: ASSET/LIABILITY/EQUITY/INCOME/EXPENSE)
- **JournalEntries** / **JournalLines** (debit/credit ledger facts)
- **ReconciliationMatches** (versioned match facts)
- **ManualValuationSnapshot** (versioned ODS valuation facts)

This is not the full inventory — consult the generated reference for the
complete table/column/enum list.

## Design Constraints

### Naming Conventions

- **Explicit Enums**: ALWAYS provide `name=` to SQLAlchemy `Enum`.
  - ❌ `sa.Column(sa.Enum(Status))`
  - ✅ `sa.Column(sa.Enum(Status, name="journal_entry_status"))`
  - Proof: `apps/backend/tests/infra/test_schema_guardrails.py::test_enums_have_explicit_names`
- **Migration IDs/descriptions**: keep short for filesystem/Docker-volume limits.

### Async Session Management

1. Use the `get_db` FastAPI dependency for routers.
2. Routers handle commit/rollback; services use `flush()`
   (see [`accounting`](../accounting/SKILL.md) async-tx-boundary rule).
3. Ensure every session is closed.

### Recommended Patterns

- `DECIMAL(18,2)` for monetary amounts; `created_at`/`updated_at` audit fields; UUID PKs.

### Prohibited Patterns

- **NEVER** use FLOAT for monetary amounts.
- **NEVER** directly delete posted entries — only void.

## Migration Contract

The authoritative build proof is **Alembic against Postgres**, not
`Base.metadata.create_all()` in unit fixtures. PR CI (`schema-migrations`) runs:

```bash
cd apps/backend
uv run alembic upgrade head
uv run alembic check
```

Preview/staging must not be the first environments to discover a broken chain or
model/migration drift.

## Source Files

- **Models**: `apps/backend/src/models/`
- **Migrations**: `apps/backend/migrations/`
- **Schemas**: `apps/backend/src/schemas/`
- **Generated reference**: `docs/reference/db-schema.md` (build output, git-ignored)
