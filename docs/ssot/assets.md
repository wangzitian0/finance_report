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
2. **Lookup** existing `ManagedPosition` by `(account_id, asset_identifier)`
3. **Update** if found — refresh quantity, cost_basis, currency, metadata, clear disposal
4. **Create** if not found — new ACTIVE position with auto-created broker account
5. **Dispose** any existing managed positions not seen in the latest snapshot → set `status=DISPOSED`, `disposal_date=today`

### Broker Account Auto-Creation

`_get_or_create_broker_account` automatically creates an `ASSET`-type account for each broker encountered during reconciliation. Broker name falls back to `"Unknown Broker"` when not provided.

---

## 3. API Endpoints

> Full API layer details documented in [schema.md Section 7](./schema.md#7-api-layer-assets).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/assets/positions` | List all managed positions (with optional filters) |
| `GET` | `/assets/positions/{id}` | Get single position by ID |
| `POST` | `/assets/reconcile` | Trigger position reconciliation from atomic data |
| `GET` | `/assets/positions/{id}/depreciation` | Calculate depreciation schedule |
| `POST` | `/assets/valuation-snapshots` | Create manual valuation snapshot |
| `GET` | `/assets/valuation-snapshots` | List manual valuation snapshots |
| `GET` | `/assets/valuation-snapshots/{id}` | Get one manual valuation snapshot |
| `PATCH` | `/assets/valuation-snapshots/{id}` | Update manual valuation snapshot |
| `DELETE` | `/assets/valuation-snapshots/{id}` | Delete manual valuation snapshot |

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

### ManagedPosition (Layer 3)

```sql
CREATE TABLE managed_positions (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id),
    asset_identifier VARCHAR(100) NOT NULL,
    quantity NUMERIC(18,6) NOT NULL,
    cost_basis NUMERIC(18,2) NOT NULL,
    acquisition_date TIMESTAMP,
    disposal_date TIMESTAMP,
    status position_status_enum NOT NULL DEFAULT 'ACTIVE',
    currency VARCHAR(3),
    position_metadata JSONB,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

### PositionStatus Enum

| Value | Meaning |
|-------|---------|
| `ACTIVE` | Currently held position |
| `DISPOSED` | Position closed or quantity went to zero |

### ManualValuationSnapshot (Layer 3)

```sql
CREATE TABLE manual_valuation_snapshots (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    component_type manual_valuation_component_type_enum NOT NULL,
    liquidity_class manual_valuation_liquidity_class_enum NOT NULL,
    as_of_date DATE NOT NULL,
    value NUMERIC(18,2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    source VARCHAR(120) NOT NULL,
    notes TEXT,
    recurrence_days INTEGER,
    reminder_date DATE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE (user_id, component_type, source, as_of_date)
);
```

Manual snapshots cover property value, mortgage or loan balance, CPF or long-term savings, tax payable/refund, insurance cash value, ESOP, RSU, stock options, and generic assets/liabilities. The value is always stored as a positive `Decimal`; the liquidity class determines whether it contributes to assets, liabilities, restricted, or illiquid net worth presentation.

---

## 7. Design Constraints

### ✅ Recommended Patterns
- **Pattern A**: Use `Decimal` for all monetary/quantity fields (never `float`)
- **Pattern B**: `cost_basis` uses `market_value` as proxy — true FIFO/LIFO lot tracking is future scope
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
- [schema.md](./schema.md) (Section 7)
