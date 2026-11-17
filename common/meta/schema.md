# Database Schema SSOT

> **SSOT Key**: `schema` | PostgreSQL layering, enum naming, and migration guardrails. Live DDL inventory: [db-schema.md](../../docs/reference/db-schema.md) (`tools/generate_db_schema_reference.py`). API inventory: [api.md](../../docs/reference/api.md).

<a id="data-layering"></a>
## 1. Data Layering Model

Tables belong to one warehouse layer (`DIM` conformed references like `accounts`; `ODS` raw uploads/snapshots; `DWD` cleaned immutable facts; `DWM` cross-fact processes like `reconciliation_matches`/`fx_conversions`; `DWS` summaries like `managed_positions`/`investment_lots`; `ADS` `report_snapshots`) plus app/audit tables (`users`, `trace_records`). Facts use append-only `(version, superseded_by_id)` chains with partial unique indexes `WHERE superseded_by_id IS NULL`.

<a id="er-model"></a>
## 2. Migration & Schema Proof

<a id="enum-naming"></a>
- **Explicit enum names mandatory**: Every `sa.Enum(..., name="...")` requires an explicit name (`test_enums_have_explicit_names`).
- **PR schema authority**: `cd apps/backend && uv run alembic upgrade head && uv run alembic check`.
- **Backend test schema fidelity**: Fast unit tests use a **fast fixture schema** built with `Base.metadata.create_all()` (stripping `users.id` FKs only for legacy `detached-owner` rows tracked by `tools/check_detached_owner_shortcuts.py`), while **production-faithful backend business persistence** runs isolated integration tests directly against Alembic migrations.
- **Migration risk**: Classified in `common/meta/data/migration-risk.yaml` (`tools/check_migration_risk.py`).
- **Async sessions & Decimal**: Routers own `commit()`/rollback (`get_db`); services call `flush()`. Use `DECIMAL`/`Decimal`, never `float`.
