# Base packages (value-type narrow waists)

> **SSOT Key**: `base_packages`
> **Core definition**: the family of shared value-type "narrow waist" packages,
> the rule for what qualifies, and the canonical structure every one must follow.

A *base package* is a small, dependency-light value type that makes a class of
bad states unrepresentable and is shared, by a **language-neutral standard**,
across every end (backend Python + frontend TypeScript). `money` (#1167) is the
reference instance; this doc generalises it so the family stays uniform and
bounded.

## 1. What qualifies (all five must hold)

A domain earns a base package only if it is **all** of:

1. **A shared algorithm** — real computation, not just a DTO.
2. **Cross-language** — computed/rendered on both backend and frontend, so the two
   can drift.
3. **Correctness-critical** — a wrong value is a real bug.
4. **Currently ad-hoc / duplicated** — no single standard today.
5. **A primitive, not business logic** — domain-specific weights/policies
   (reconciliation scoring, attention ranking, source-type rules) do **not**
   qualify; they consume primitives, they are not primitives.

## 2. The family (bounded on purpose)

| Package | Value type | Quantum / policy | Status |
|---------|-----------|------------------|--------|
| `money` | `Money` (amount + `Currency`), plus typed `ExchangeRate` for conversion | 2 dp, **ROUND_HALF_EVEN** (banker's); FX rates positive Decimal | ✅ shipped (#1167, EPIC-012 AC12.30) |
| `ratio` | `Ratio` (dimensionless) | percent 2 dp, **ROUND_HALF_UP** | ✅ shipped (#1167, EPIC-012 AC12.9) |
| `quantity` | `Quantity` (shares/units/contracts) + `Unit` | 6 dp, **ROUND_HALF_UP** | ✅ shipped (EPIC-012 AC12.30) |

`Currency` lives **inside** `money` (not separate). `ExchangeRate` is also
inside `money`: it is the typed parameter for the single cross-currency
conversion primitive, not a fourth base package. `Price` / unit price is a
derived composite (`Money / Quantity`) and remains outside the primitive family
until portfolio/market-data migration proves a separate package is needed.
Nothing else currently qualifies — see the per-domain verdicts in the #1167
audit (date/period, confidence scoring, source-type, lineage, attention are app
logic or presentation, not base packages).

## 3. Raw Decimal boundary policy

`Decimal` is the storage/interchange substrate for exact numeric values; it is
not, by itself, a business value type. Once a value crosses into service/domain
logic, code should use the MECE base element that owns the semantics:

- `Money` for currency amounts and same-currency arithmetic;
- `ExchangeRate` inside `money` for directed cross-currency conversion;
- `Ratio` for dimensionless proportions, percentages, and shares of a whole;
- `Quantity` for shares, units, lots, contracts, and quantity comparisons.

### Allowed raw Decimal boundaries

Raw `Decimal` is allowed only where the surrounding layer is explicitly a
boundary or test fixture:

1. **Base packages** — `common/money`, `common/ratio`, `common/quantity` and the
   backend/frontend runtime copies may use `Decimal`/`decimal.js` internally.
2. **DB models and migrations** — SQLAlchemy `Numeric` columns, Alembic
   migrations, and repository/query predicates store exact numeric values.
3. **Schemas and API contracts** — Pydantic/TypeScript API shapes may expose
   exact decimals as string-backed fields while preserving existing wire shapes.
4. **Parser and provider adapters** — OCR, CSV/PDF parsers, market-data
   providers, and import adapters may parse external numbers into raw
   `Decimal` before handing them to domain services.
5. **Tests, fixtures, and generated code** — tests may build exact inputs and
   assert exact outputs; generated API types may mirror the wire contract.

### Forbidden raw Decimal zones

Raw `Decimal` is forbidden as naked business semantics in migrated
service/domain calculations and frontend application code. In those zones:

- money math must construct `Money`, and cross-currency conversion must call
  `money.convert(Money, ExchangeRate)`;
- percentage/proportion math must construct `Ratio`;
- quantity comparisons and quantity arithmetic must construct `Quantity`;
- frontend app pages/components must not import `decimal.js` types directly;
  they should consume `lib/money`, `lib/ratio`, or `lib/quantity` helpers.

Legacy code that has not yet crossed this boundary must be either migrated or
kept behind a narrow, documented adapter. New raw-`Decimal` service/application
hotspots require an AC/test update that explains the boundary.

## 4. The canonical structure (every base package has these)

1. **Value type** — immutable/frozen, Decimal-backed, carries its unit; **rejects
   `float`** at construction.
2. **Construction + validation** — normalise input, validate the unit, reject
   `float`/`bool`.
3. **Same-unit arithmetic** — `add`/`sub`/`compare`/`neg`/`*scalar`;
   **cross-unit raises** (no implicit mixing).
4. **Quantization** — one defined quantum + rounding policy + explicit override.
5. **Single conversion primitive** — the one allowed cross-unit move
   (money: `convert(ExchangeRate)`; ratio: `fraction(part, whole)` / `↔ percent`;
   quantity: `Quantity / Quantity -> Ratio`).
6. **Per-key container** (where applicable) — aggregation that makes cross-key
   summing structurally impossible (money: `CurrencyBalances`).
7. **Serialization** — to/from the wire as **strings** (never JSON float).
8. **Typed error hierarchy** — base `XError` → `FloatNotAllowed` / `Invalid…` /
   `…Mismatch`.
9. **The language-neutral standard** — `contract/<x>.contract.md` (interface) +
   `conformance/vectors.json` (golden cases) + `shared_api` (identifier set).
10. **Per-end implementations** — Python reference (`common/<x>`), backend runtime
    (`apps/backend/src/<x>`), frontend (`apps/frontend/src/lib/<x>`) — each
    conformance-tested against the **same** vectors.
11. **Three guards** — no-`float` (the money narrow-waist guard), one conformance
    suite per stack, and identifier-parity (`test_<x>_api_parity.py`).

## 5. Why per-end copies (not one shared runtime)

The frontend is TypeScript and cannot import the Python package; the deployed
images do not ship `common/`. So the **standard** (contract + conformance
vectors) is shared at *test time*, and each end keeps its own idiomatic
implementation verified against it. `common/<x>` is the reference + the home of
the standard; it is dev/test-time only, never shipped into a runtime image.

## Used by

- `money`: [accounting.md#money-type](accounting.md), `common/money/`, `apps/backend/src/money/`, `apps/frontend/src/lib/money/`
- `ratio`: [EPIC-012 AC12.9](../project/EPIC-012.foundation-libs.md), `common/ratio/`, `apps/backend/src/ratio/`, `apps/frontend/src/lib/ratio/`
- `quantity`: [EPIC-012 AC12.30](../project/EPIC-012.foundation-libs.md), `common/quantity/`, `apps/backend/src/quantity/`, `apps/frontend/src/lib/quantity/`
