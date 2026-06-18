# Assets SSOT

> **SSOT Key**: `assets`
> **Core Definition**: Investment position lifecycle — reconciliation from atomic broker data, managed position tracking, and depreciation calculations.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Model** | `apps/backend/src/models/layer3.py` (`ManagedPosition`, `ManualValuationSnapshot`) | Position storage, status tracking, manual valuation snapshots |
| **Service** | `apps/backend/src/services/assets.py` (`AssetService`) | Reconciliation, depreciation logic, manual valuation component aggregation |
| **Router** | `apps/backend/src/routers/assets.py` | REST endpoints (`/assets`) |
| **Schemas** | `apps/backend/src/schemas/assets.py` | Request/response validation |
| **Source Data** | `apps/backend/src/models/layer2.py` (`AtomicPosition`) | Raw broker position snapshots |
| **Tests** | `apps/backend/tests/assets/` | 52 tests across 5 files |

---

## 2. Architecture

### Reconciliation Pipeline

```
AtomicPosition (Layer 2)          ManagedPosition (Layer 3)
┌─────────────────────┐            ┌─────────────────────┐
│ Raw broker snapshots │──window──▶│ Deduplicated, latest │
│ (multiple per asset) │  function │ positions per asset  │
└─────────────────────┘            └─────────────────────┘
```

**Window Function Strategy**: For each `(asset_identifier, broker)` group, select the row with the latest `snapshot_date` using:

```sql
ROW_NUMBER() OVER (
    PARTITION BY asset_identifier, broker
    ORDER BY snapshot_date DESC
) AS rn
-- WHERE rn = 1
```

### Reconcile → Upsert Logic

For each latest atomic position:

1. **Skip** if `quantity` or `market_value` is NULL → recorded in `skipped_assets`
2. **Lookup** existing `ManagedPosition` by `(user_id, account_id, asset_identifier)`
3. **Update** if found — refresh quantity, cost_basis, currency, metadata, clear disposal
4. **Create** if not found — new ACTIVE position with auto-created broker account
5. **Dispose** any existing managed positions not seen in the latest snapshot → set `status=DISPOSED`, `disposal_date=today`

### Broker Account Auto-Creation

`_get_or_create_broker_account` automatically creates an `ASSET`-type account for each broker encountered during reconciliation. Broker name falls back to `"Unknown Broker"` when not provided.

### Latest Holdings Valuation Date

`GET /portfolio/holdings` without `as_of_date` returns the latest portfolio value from `ManagedPosition` plus the latest eligible price snapshot. The valuation date is `today` unless the user's latest imported `AtomicPosition.snapshot_date` is newer, which can happen for current-month brokerage statement fixtures or provider outputs that normalize month-only periods to month end.

Explicit `as_of_date` requests are point-in-time views: holdings are derived from the latest immutable `AtomicPosition` snapshot per `(asset_identifier, broker)` at or before the requested date. Quantity and market value must come from that selected snapshot, and future snapshots must not be used. When structured brokerage transactions are available, `InvestmentTransaction` and `InvestmentLot` provide the auditable cost-basis trail for buy/sell/dividend accounting; snapshot-only imports still use market value as the fallback cost-basis proxy.

### Investment Accounting Pipeline

Structured brokerage transactions are posted through `InvestmentAccountingService`:

1. **Buy**: debit the investment asset account, credit brokerage cash, create an `InvestmentTransaction`, create an `InvestmentLot`, and increase `ManagedPosition.quantity` plus `cost_basis`.
2. **Sell**: consume open lots by the explicit `CostBasisMethod` (`FIFO`, `LIFO`, or `AvgCost`), debit brokerage cash, credit the investment asset account at consumed cost basis, record realized gain/loss to the realized P&L income account, and update `ManagedPosition.realized_pnl`.
3. **Dividend**: debit brokerage cash, credit dividend income, persist `DividendIncome`, and link the event to the position through `InvestmentTransaction`.

Investment-accounting journal entries use `source_type=system` for deterministic postings and preserve any upstream parser/source identifier in `source_id`. User-entered, parsed, matched, and confirmed statement entries follow the trust hierarchy in [source-type-priority.md](./source-type-priority.md).

### Portfolio Performance Cash Flows

Portfolio return calculations use investment-domain cash flows only:

- XIRR and money-weighted return use `InvestmentTransaction` rows up to `as_of_date`.
- Time-weighted return removes only investment-domain cash flows in the measurement period.
- General bank `AtomicTransaction` rows are excluded from portfolio performance because they include salary, bill payment, transfer, and other non-investment cash movements.
- BUY transactions are investor cash outflows for XIRR and positive contributions for TWR cash-flow adjustment.
- SELL and DIVIDEND transactions are investor cash inflows for XIRR and negative withdrawals for TWR cash-flow adjustment.

Portfolio summary YTD realized P&L and dividend income are presentation-currency values. Each transaction/dividend is converted from its source currency to the summary currency on its transaction/payment date before aggregation.

---

## 3. API Endpoints

The mutable endpoint inventory is generated from FastAPI OpenAPI:

- [Generated API Reference](../reference/api.md)
- Runtime Swagger UI: `/api/docs`
- Runtime ReDoc: `/api/redoc`

This SSOT owns asset-domain semantics. Do not hand-copy asset endpoint tables
here; add or update router/schema code and let the generated API reference carry
the path, parameter, request, and response inventory.

---

## 4. Reconciliation Logic

### ReconcileResult

```python
@dataclass
class ReconcileResult:
    created: int       # New positions created
    updated: int       # Existing positions refreshed
    disposed: int      # Positions marked DISPOSED (not in latest snapshot)
    skipped: int       # Positions skipped (null quantity/market_value)
    skipped_assets: list[str]  # Asset identifiers that were skipped
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| `quantity` is NULL | Skipped, asset_identifier added to `skipped_assets` |
| `market_value` is NULL | Skipped, asset_identifier added to `skipped_assets` |
| `quantity` is 0 | Treated as disposal — position marked DISPOSED |
| `quantity` is negative | Treated normally (represents short positions) |
| `broker` is NULL/empty | Falls back to `"Unknown Broker"` |
| Position exists but absent from snapshot | Marked DISPOSED with `disposal_date = today` |

---

## 5. Depreciation

Two methods supported, both operating on a single `ManagedPosition`:

### Straight-Line

```
period_depreciation = (cost_basis - salvage_value) / useful_life_years
```

### Double-Declining Balance

```
period_depreciation = (2 / useful_life_years) × book_value
```

Where `book_value = cost_basis - accumulated_depreciation`.

### DepreciationResult

```python
@dataclass
class DepreciationResult:
    position_id: UUID
    asset_identifier: str
    period_depreciation: Decimal
    accumulated_depreciation: Decimal
    book_value: Decimal
    method: str              # "straight_line" or "declining_balance"
    useful_life_years: int
    salvage_value: Decimal
```

---

## 6. Data Model

Mutable table, column, enum, index, constraint, and foreign-key inventory is
generated from SQLAlchemy metadata:

- [Generated DB Schema Reference](../reference/db-schema.md)
- Models: `apps/backend/src/models/layer3.py`, `apps/backend/src/models/portfolio.py`
- Migrations: `apps/backend/migrations/`

| Model | Table | Domain role |
|---|---|---|
| `ManagedPosition` | `managed_positions` | DWS maintained position state derived from source snapshots and investment transactions |
| `InvestmentTransaction` | `investment_transactions` | Auditable brokerage buy/sell/dividend event used for ledger posting and realized P&L |
| `InvestmentLot` | `investment_lots` | Lot-level cost-basis state for FIFO/LIFO/average-cost realized P&L |
| `ManualValuationSnapshot` | `manual_valuation_snapshots` | User-entered valuation fact for non-ledger net-worth components |

Keep field definitions, enum values, constraints, and foreign keys in model and
migration code; link to the generated DB reference from docs.

<a id="manual-valuation-snapshots"></a>

### Manual Valuation Snapshots

Manual snapshots cover property value, mortgage or loan balance, CPF/provident
fund balances, retirement accounts, personal social-security account balances,
long-term benefit assets, legacy long-term savings, tax payable/refund,
insurance cash value, ESOP, RSU, stock options, and generic assets/liabilities.
Insurance is represented only by its attributable cash/surrender value; coverage
amounts and future benefits are not recorded as assets. The value is always
stored as a positive `Decimal`; the liquidity class determines whether it
contributes to assets, liabilities, restricted, or illiquid net worth
presentation.
Reminder cadence is optional; when present, `recurrence_days` is positive.

Manual snapshot capture uses a controlled source vocabulary for new frontend submissions:
`manual`, `broker_portal`, `bank_portal`, `cpf_portal`, `tax_portal`,
`insurer_portal`, `employer_portal`, `property_valuation`, and
`other_document`. Historical source strings remain valid response data and
should be displayed as-is when they do not match a known vocabulary value.

Manual valuation snapshot and latest valuation component API responses expose
normalized read-model provenance as `provenance="manual"`. This field is a
separate user-trust signal from the snapshot's `source` basis string: `source`
describes where the user says the value came from, while `provenance` states
that the value was user-entered rather than imported or derived by the system.

<a id="guided-evidence-intake-contract"></a>

#### Guided Evidence Intake Contract (#706)

Guided evidence intake is the end-to-end contract for capturing a manual-trusted
value with a structured, auditable evidence basis. It binds the frontend guided
form, the persisted `valuation_basis` enum, the component classification, and the
report artifacts that surface the basis into one chain.

**Guided form → `component_type` → default `valuation_basis`.** The shared guided
form offers three source classes; each maps to a backend `component_type` and a
sensible default basis (the user may override the basis from the full enum):

| Guided source class | `component_type`   | Default `valuation_basis`   |
|---------------------|--------------------|-----------------------------|
| `esop_rsu_plan`     | `rsu`              | `employer_grant_document`   |
| `property_statement`| `property_value`   | `market_appraisal`          |
| `liability_statement`| `other_liability` | `bank_statement`            |

**`valuation_basis` enum values** (`ManualValuationBasis`, persisted on the
snapshot; nullable): `market_appraisal`, `broker_statement`,
`employer_grant_document`, `bank_statement`, `government_statement`,
`insurer_statement`, `self_estimate`. A current evidence-bearing snapshot that
carries no basis (and no legacy notes) surfaces a `missing_valuation_basis`
readiness blocker rather than being rejected (see AC11.9.5).

**Report artifacts that surface the basis.** The captured basis flows, null-safe
(falling back to `unspecified`), into the report outputs:

- **Annualized income schedule** (`GET /api/reports/package/annualized-income-schedule`):
  each restricted holding's `valuation_basis` carries the snapshot enum value
  (AC11.11.4).
- **Balance sheet / net worth**: manual snapshots aggregate into asset/liability
  and restricted/illiquid totals by `liquidity_class` (AC11.9.2–3).
- **Package "valuation-basis" note**: the package surfaces the
  `manual_valuation_snapshots` source state for the basis disclosure.
- **Traceability appendix** (`personal_report_package_traceability`): each manual
  snapshot's source-anchor detail records its `valuation_basis` enum value
  (AC11.9.10).

---

## 7. Design Constraints

### ✅ Recommended Patterns
- **Pattern A**: Use `Decimal` for all monetary/quantity fields (never `float`)
- **Pattern B**: Use `InvestmentLot` for realized P&L whenever buy/sell transactions are available; use snapshot market value as a fallback proxy only for position-snapshot imports without transaction detail.
- **Pattern C**: Reconciliation is idempotent — running twice with same data produces same result
- **Pattern D**: Always record `position_metadata` (JSONB) for audit trail of source data
- **Pattern E**: Manual valuation values are positive `Decimal` amounts; use `liquidity_class` to separate liquid, restricted, illiquid, and liability presentation.

### ⛔ Prohibited Patterns
- **Anti-pattern A**: **NEVER** use `float` for quantity or cost_basis
- **Anti-pattern B**: **NEVER** assume `managed_position.py` exists — model lives in `layer3.py`
- **Anti-pattern C**: **NEVER** delete positions — mark as DISPOSED instead
- **Anti-pattern D**: **NEVER** include a snapshot in liquid net worth unless it is economically liquid

---

## 8. Verification

| Behavior | Test File | Tests | Status |
|----------|-----------|-------|--------|
| Position CRUD / service logic | `test_asset_service.py` | Service-level create/read/update scenarios | ✅ Passing |
| Position lifecycle & reconciliation | `test_assets_positions_and_depreciation.py` | Position lifecycle, reconciliation, depreciation | ✅ Passing |
| Depreciation calculation | `test_asset_depreciation.py` | Straight-line, declining-balance | ✅ Passing |
| Router edge cases (nulls, zeros) | `test_assets_router_edge_cases.py` | Nulls, zeros, invalid payloads | ✅ Passing |
| API endpoints | `test_assets_router.py` | Router integration tests | ✅ Passing |
| Manual valuation snapshots | `test_manual_valuation_snapshots.py` | CRUD, Decimal aggregation, restricted toggle | ✅ Passing |

**Total**: 55+ tests, all passing in targeted verification.

---

## Used by

- [reporting.md](./reporting.md)
- [schema.md](./schema.md)
- [Generated DB Schema Reference](../reference/db-schema.md)
- [Generated API Reference](../reference/api.md)
