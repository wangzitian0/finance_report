# Database Schema SSOT

> **SSOT Key**: `schema`
> **Core Definition**: PostgreSQL model rationale, data-layer rules, enum naming, and migration guardrails.

This file owns the schema language and guardrails. It does **not** own the
mutable table, column, enum, index, or endpoint inventory.

| Contract | Owner |
|---|---|
| Table/column/enum/index/FK inventory | [Generated DB Schema Reference](../reference/db-schema.md) |
| Deployable schema chain | `apps/backend/migrations/` Alembic revisions |
| Model metadata | `apps/backend/src/models/` SQLAlchemy models |
| Request/response and endpoint inventory | [Generated API Reference](../reference/api.md) |
| Schema validation payloads | `apps/backend/src/schemas/` Pydantic schemas |

> Local dev no longer treats `Base.metadata.create_all()` as the schema
> authority. Alembic `upgrade head` plus `alembic check` is the deterministic
> schema contract for PR CI and local escalation.

---

<a id="data-layering"></a>

## 1. Data Layering Model

The data tables use a data-warehouse layering vocabulary instead of the earlier
ad-hoc "Layer 0/1/2/3/4" numbering. A table belongs to exactly one data layer
unless it is an application-plane or audit-plane table. If code, model metadata,
or migrations place a value in the wrong layer, fix the drift instead of adding
a prose exception.

| Layer | Meaning | Typical source | Account boundary | Mutability |
|---|---|---|---|---|
| **DIM** | Conformed reference data owned by the application | App / curated reference data | Defines or references accounts | Slowly changing |
| **ODS** | User-side source data landed 1:1 as received | User upload or manual entry | Must not be downstream account authority | Append-mostly |
| **DWD** | Cleaned, deduplicated detail facts | Derived from ODS plus DIM | Carries conformed DIM keys where needed | Immutable / posted |
| **DWM** | Thin cross-fact process layer | Derived from DWD plus DIM | Resolves process state through DWD/DIM | Process state |
| **DWS** | Subject-oriented summaries and maintained derived state | Derived from DWD/DWM | Uses conformed facts | Recomputed |
| **ADS** | Application/report outputs consumed by UI | Derived from DWS/DWD | Report-facing snapshot | Snapshot |

Examples:

| Layer | Examples |
|---|---|
| DIM | `accounts`, `classification_rules`, market/security/institution reference data |
| ODS | `uploaded_documents`, `manual_valuation_snapshots` |
| DWD | `atomic_transactions`, `atomic_positions`, `statement_summaries`, `journal_entries`, `journal_lines` |
| DWM | `reconciliation_matches`, `consistency_checks` |
| DWS | `managed_positions`, `investment_lots`, derived balances and period aggregates |
| ADS | `report_snapshots` |
| Application / audit plane | `users`, chat/workflow tables, evidence graph tables, feedback/correction tables, `confidence_metric_snapshots` (append-only North-Star metric series) |

The generated DB reference owns the current table inventory. Keep the layer list
above as domain vocabulary and examples, not as a second column-by-column schema
catalog.

### Cross-Layer Rules

1. **Account is DIM, conformed at DWD.** `account_id` is assigned when a DWD fact
   is built, such as `transaction_classification.account_id`,
   `journal_lines.account_id`, or `statement_summaries.account_id`.
2. **DWM/DWS/ADS resolve dimensions from DWD/DIM, never from ODS.** Matching,
   transfer logic, summaries, and reports must not reach back to a source-file
   row for account authority.
3. **No reference data in code.** Non-user reference data that affects ADS
   belongs in DIM tables or generated/config-owned contracts, not hard-coded
   Python constants.
4. **DWM stays thin.** Add DWM only for genuinely complex cross-fact process
   state. Default new work to DWD or DWS.

> **Drift closed (EPIC-011 Stage 3, completed):** reconciliation transfer
> detection resolves custody account from DWD (`statement_summaries` through
> `resolve_custody_account_id`). The legacy `bank_statement*` ODS tables and
> Layer-0 read path were removed. See
> [EPIC-011](../project/EPIC-011.asset-lifecycle.md).

### Append-Only Fact Versioning (Axiom A)

A stored *fact* — the recorded value of a financial quantity — is never edited in
place. When a fact is corrected, a new version is appended and the prior one is
superseded; the live value is the head of the chain, history stays retrievable,
and one version maps to exactly one value (vision Axiom A).

- **Version-bearing unit.** The fact row itself carries the version. The native
  idiom is a `version` integer plus a self-referential `superseded_by_id` (as on
  `reconciliation_matches`; `transaction_classification` uses the
  `superseded_by_id` supersede chain alone), not bitemporal `valid_from`/`valid_to`
  columns and not a separate version table.
- **Current head.** The head of a chain has `superseded_by_id IS NULL`. Where a
  key must stay unique, enforce it with a **partial unique index over the head**
  (`WHERE superseded_by_id IS NULL`) so superseded history rows accumulate
  freely. Default read and aggregation paths filter to the head.
- **Fact vs. review-state.** Append-only applies to *facts* (recorded values).
  Working review-state and annotations (status transitions, notes, reminders)
  may stay mutable in place. Draw this line per table; do not make review
  workflow append-only just because it shares a row with a fact.

Owner of the first applied instance: `manual_valuation_snapshots` (ODS), where a
re-submitted `(component_type, source, as_of_date)` appends a new version. See
[EPIC-011 AC11.19](../project/EPIC-011.asset-lifecycle.md) and issue #918.

---

<a id="er-model"></a>

## 2. Generated Schema Reference

The generated DB schema reference is the public schema inventory:

- [Generated DB Schema Reference](../reference/db-schema.md)
- Command: `python tools/generate_db_schema_reference.py`
- Build hook: `docs/hooks.py`
- Drift gate: generate, then run `python tools/generate_db_schema_reference.py --check`
- CI step: `Generated DB Schema Reference Check`
- Git policy: the generated `docs/reference/db-schema.md` page is intentionally
  ignored; it is present in MkDocs output, not maintained in source control.

The generated page lists:

- tables and primary keys;
- columns, PostgreSQL types, nullability, defaults, and FK targets;
- constraints and indexes;
- native enum type names, enum values, and enum-using columns;
- foreign-key edges.

Do not add hand-maintained table, column, enum, index, endpoint, or response
tables to this SSOT. If a reader needs mutable inventory, link to generated
references. If a concept needs rationale, keep it in this SSOT and link to the
code owner and proof test.

---

## 3. Migration and Naming Guardrails

### Naming Conventions

<a id="enum-naming"></a>

**Explicit enum names are mandatory.** Every SQLAlchemy `Enum` must declare an
explicit `name="..."` parameter. This prevents SQLAlchemy from deriving
inconsistent PostgreSQL type names that can drift from Alembic migrations.

```python
# Bad: implicit PostgreSQL type name
sa.Column(sa.Enum(Status))

# Good: explicit PostgreSQL type name
sa.Column(sa.Enum(Status, name="journal_entry_status"))
```

Automated proof:

- `apps/backend/tests/infra/test_schema_guardrails.py::test_enums_have_explicit_names`
- [Generated DB Schema Reference](../reference/db-schema.md#enum-types)

Migration file names and revision IDs must stay short enough for common
filesystems and Docker volumes. Use concise Alembic descriptions and manually
set short revision IDs when autogeneration would produce long or colliding IDs.

### Migration Contract

The authoritative schema build proof is Alembic against Postgres, not
`Base.metadata.create_all()` inside backend unit fixtures. PR CI runs
`schema-migrations` with:

```bash
cd apps/backend
uv run alembic upgrade head
uv run alembic check
```

Preview and staging validate deployed runtime health after merge or during PR
preview deployment. They must not be the first environments that discover a
broken migration chain or model/migration drift.

### Backend Test Schema Fidelity

Backend tests use three deliberately separate schema proof modes:

| Mode | Builder | Purpose | Authority |
|---|---|---|---|
| Fast fixture schema | `Base.metadata.create_all()` inside `apps/backend/tests/conftest.py` | Keep broad backend feedback fast by creating the model schema once per worker and truncating data per test. This lane is intentionally non-authoritative while legacy detached-owner tests are burned down. | Fast regression only |
| PR Alembic schema proof | `uv run alembic upgrade head` plus `uv run alembic check` in CI | Prove the deployable migration chain can build the production schema and that SQLAlchemy metadata does not drift from migrations. | Schema merge authority |
| production-faithful backend business persistence | A focused backend integration lane that creates an isolated database from Alembic and exercises representative business writes without weakening user foreign keys. | Prove Tier-1 persistence semantics do not rely on the fast fixture schema. | Business persistence proof |

The fast fixture schema currently strips `users.id` foreign keys after
`create_all()` because some tests create detached-owner rows with direct
`user_id=uuid4()` shortcuts instead of real `User` rows. New tests should create
real users through fixtures or factories. `tools/check_detached_owner_shortcuts.py`
counts the real foreign-key risk — only **persisted** detached owners (a
`user_id=uuid4()` construction added via `db.add` / `db.add_all`) — and fails on
count growth. Transient in-memory constructions and bare service arguments carry
no production foreign key and are not counted, which is why the count reflects a
handful of rows (intentional cross-user isolation tests) rather than every inline
`uuid4()`.

### Migration Risk Classification

Clean-schema Alembic proof does not guarantee production data migration safety.
Production data can contain historical rows, old enum values, production-only
volume, and edge cases that CI and staging will never reproduce perfectly.

The machine-readable owner for migration risk is
[migration-risk.yaml](./migration-risk.yaml), validated by
`tools/check_migration_risk.py`.

| Risk | Meaning | Default proof |
|---|---|---|
| low | Additive or clean-schema-only change | PR `schema-migrations` is usually enough |
| medium | Compatibility-sensitive schema, enum/type, index, or constraint change | PR proof plus staging deploy proof |
| high | Data rewrite, backfill, read-path cutover, large-table concern, or production-volume concern | PR proof plus staging evidence plus production preflight/rollback notes |
| critical | Destructive or irreversible production change, such as dropping legacy tables or columns | High-risk proof plus explicit destructive-change confirmation |

This contract is a risk-classification gate, not a production guarantee.
Production residual risk is managed through backups, expand/contract sequencing,
feature flags, idempotent backfills, preflight queries, rollback notes, and
post-deploy detectors.

### Async Session Management

To prevent connection leaks and transaction-boundary drift:

1. Routers use the `get_db` FastAPI dependency and own high-level
   `commit()`/rollback.
2. Services use `flush()` when they need generated IDs and avoid `commit()`
   unless deliberately implemented as a closed-loop transaction.
3. Sessions are closed by the dependency generator or explicit test/session
   lifecycle helpers.

### Recommended Patterns

- Use `Decimal` / SQL `DECIMAL` for monetary amounts; never `float`.
- Use `created_at` and `updated_at` audit fields on mutable records.
- Use UUID primary keys for distributed compatibility unless a table is
  deliberately local/sentinel state.
- Keep ledger correction paths explicit: posted/reconciled facts are corrected
  through void/reversal or approved promotion paths, not direct mutation.

### Prohibited Patterns

- **Never** store monetary amounts as floating-point values.
- **Never** create `sa.Enum` without `name="..."`.
- **Never** treat unit-test `create_all()` fixtures as migration proof.
- **Never** document endpoint or table inventories by hand when generated
  references can own the mutable facts.

---

## 4. Ownership Boundaries

| Question | Go to |
|---|---|
| What tables, columns, indexes, enums, constraints, and FKs exist now? | [Generated DB Schema Reference](../reference/db-schema.md) |
| What endpoints and request/response schemas exist now? | [Generated API Reference](../reference/api.md) |
| Why does the schema use DIM/ODS/DWD/DWM/DWS/ADS? | This file, [Data Layering Model](#data-layering) |
| What is the enum naming rule? | This file, [enum naming](#enum-naming) |
| What migration proof is required? | This file plus [CI/CD SSOT](./ci-cd.md) and [migration-risk.yaml](./migration-risk.yaml) |
| What are accounting invariants? | [Accounting SSOT](./accounting.md) |

## Used By

- [AGENTS.md](https://github.com/wangzitian0/finance_report/blob/main/AGENTS.md)
- [Accounting SSOT](./accounting.md)
- [Reconciliation SSOT](./reconciliation.md)
- [CI/CD SSOT](./ci-cd.md)
- [Generated DB Schema Reference](../reference/db-schema.md)
