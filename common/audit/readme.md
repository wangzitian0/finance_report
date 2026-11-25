# `audit` — the number governor

Peer to [`meta`](../meta/readme.md): `audit.base` defines the Shared-Kernel value types (`Money`, `Currency`, `ExchangeRate`, `CurrencyBalances`, `Ratio`, `Quantity`, `Unit`, `UnitPrice`) and the `TraceRecord` boundary; `audit.data` owns `TraceRecord` heads. One physical Python kernel lives in `apps/backend/src/audit/`, bridged by `common/audit/__init__.py` and mirrored to `apps/frontend/src/lib/audit/` via `conformance/vectors.json`. Digests (`canonical_json_digest`, `text_digest`) are single-owned in `apps/backend/src/audit/digest.py`. See: common/ledger/readme.md#decimal-rule.

## TraceRecord assurance boundary

`TraceRecord` (`trace/contract/trace_record.contract.md`) is append-only (UUID5 ids, immutable triggers, `supersedes_id` chains). `OBSERVATION` records measurements; `DECISION` folds direct/manifest parent records under transaction-scoped locks via `TraceEmitter` and caller UoW (`current_authoritative_trace_decision_projection` / `current_authoritative_trace_decisions` + `shared_current_authority`). `TerminalAuditVerifier` verifies frozen package decisions.

## Source-type trust hierarchy (provenance)

`JournalEntrySourceType` ranks user provenance `manual > user_confirmed > auto_matched > auto_parsed` (`common/reconciliation/readme.md#thresholds`). Conflicting facts never downgrade higher-trust provenance or overwrite `manual` entries automatically.

<a id="base-packages"></a>
## Base packages (value-type narrow waists)

Shared-Kernel value types prevent raw `float` or unit mixing (`Money`/`ExchangeRate`: 2 dp `ROUND_HALF_EVEN`; `Ratio`: percent 2 dp `ROUND_HALF_UP`; `Quantity`: 6 dp `ROUND_HALF_UP`; `UnitPrice`: 6 dp `ROUND_HALF_UP`).

### Raw Decimal boundary policy

`Decimal` is the storage/interchange substrate, not a business type inside service/domain calculations.

#### Allowed raw Decimal boundaries

1. **Base packages** (`common/audit/*` and mirrors).
2. **DB models and migrations** (`Numeric` columns -> wrap into `Money`/`Ratio`/`Quantity` on entry).
3. **Schemas and API contracts** (string-backed decimal fields).
4. **Parser and provider adapters** (external parse before domain handoff).
5. **Tests, fixtures, and generated code**.

#### No Python boundary codec

The Python kernel keeps no wire codec (`wire.py` and `Invalid*PayloadError` removed); coercion lives in `decimal_scalar.py`.

#### Forbidden raw Decimal zones

Raw `Decimal` business math is forbidden in migrated `service/domain calculations` and frontend components (use `Money` + `ExchangeRate`, `Ratio`, `Quantity`, `UnitPrice`, and `lib/audit/*`).

Related: [common/audit/money/readme.md#money-type](money/readme.md#money-type) · [`../meta/readme.md`](../meta/readme.md)
