# Base packages (value-type narrow waists)

> **SSOT Key**: `base_packages`
> **Core definition**: the family of shared value-type "narrow waist" packages,
> the rule for what qualifies, and the canonical structure every one must follow.

A *base package* is a small, dependency-light value type that makes a class of
bad states unrepresentable and is shared, by a **language-neutral standard**,
across every end (backend Python + frontend TypeScript). `money` (#1167) is the
reference instance; this doc generalises it so the family stays uniform and
bounded.

In the package model this value family **is** the project's **Shared Kernel** —
the canonical ubiquitous language (`money`/`ratio`/`quantity`/`unit_price`) that
every package reuses, whose strategic role is "shared by everyone" and whose
implementation therefore lives in `common/`. The family's structure, layering,
and how each package migrates onto the model are owned by the package migration
standard: [`common/meta/migration-standard.md`](../../common/meta/migration-standard.md)
(see "Where files go" and "Completion state"). This doc owns the *membership rule*
(what earns a Shared-Kernel value package) and the per-package value contract.

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
| `unit_price` | `UnitPrice` (money-per-quantity: `rate` + `Currency` + `Unit`) | 6 dp, **ROUND_HALF_UP** (price/unit-rate quantum) | ✅ shipped (#1253, EPIC-012 AC12.32) |

`Currency` lives **inside** `money` (not separate). `ExchangeRate` is also
inside `money`: it is the typed parameter for the single cross-currency
conversion primitive, not a fourth base package.

`UnitPrice` is the **composite** member: money-per-quantity (a share price, a
unit cost, a per-contract rate). It was deliberately deferred until
portfolio/market-data migration proved the need — that threshold is now met (the
same `quantity.value * price` extension, `amount / quantity.value` rate, and a
local 6-dp `quantize` helper were duplicated across `investment_accounting`,
`market_data`, `portfolio`, and `reporting`). `UnitPrice` owns
`unit_price * quantity -> Money`, `UnitPrice.from_total(money, quantity)`
(`Money / Quantity`), and the price quantum, so that glue stops reappearing. It
depends on `money` (for `Currency`) and `quantity` (for `Unit`); applying a price
to a quantity yields `Money` only when the units agree.

Nothing else currently qualifies — see the per-domain verdicts in the #1167
audit (date/period, confidence scoring, source-type, lineage, attention are app
logic or presentation, not base packages).

**Composite operations** live *on* the elements, not as new packages: `Money`
owns `is_zero`/`is_positive`/`is_negative` and `Money.sum`; `Ratio` owns the
zero-denominator fallbacks `fraction_or_zero`/`fraction_or_none`. `MoneyTolerance`
(absolute + relative band, inside `money`) is a comparison *primitive*, not a
policy — which absolute/percent to use stays with the caller (e.g. reconciliation
config). These let business code stay typed instead of re-deriving
`sum(..., Decimal("0"))`, `amount <= Decimal("0")`, or `abs(a-b) < Decimal("0.01")`
(EPIC-012 AC12.33, #1253).

## 3. Raw Decimal boundary policy

`Decimal` is the storage/interchange substrate for exact numeric values; it is
not, by itself, a business value type. Once a value crosses into service/domain
logic, code should use the MECE base element that owns the semantics:

- `Money` for currency amounts and same-currency arithmetic;
- `ExchangeRate` inside `money` for directed cross-currency conversion;
- `Ratio` for dimensionless proportions, percentages, and shares of a whole;
- `Quantity` for shares, units, lots, contracts, and quantity comparisons.

### Allowed raw Decimal boundaries

Raw `Decimal` is allowed only as a physical substrate where the surrounding
layer is explicitly a boundary or test fixture. Hand-written semantic conversion
at those boundaries must route through the owning base-package codec/adapter,
not through local `Decimal(str(...))` helpers.

1. **Base packages** — `common/money`, `common/ratio`, `common/quantity` and the
   backend/frontend runtime copies may use `Decimal`/`decimal.js` internally.
2. **DB models and migrations** — SQLAlchemy `Numeric` columns, Alembic
   migrations, and repository/query predicates store exact numeric values; code
   that turns storage fields into business values must call the package DB
   adapters such as `money_from_db_fields`, `ratio_from_db_value`, or
   `quantity_from_db_fields`.
3. **Schemas and API contracts** — Pydantic/TypeScript API shapes may expose
   exact decimals as string-backed fields while preserving existing wire shapes;
   hand-authored JSON conversion must use the package wire codecs.
4. **Parser and provider adapters** — OCR, CSV/PDF parsers, market-data
   providers, and import adapters may parse external numbers into raw
   `Decimal` before handing them to domain services, then immediately cross the
   boundary through the typed package.
5. **Tests, fixtures, and generated code** — tests may build exact inputs and
   assert exact outputs; generated API types may mirror the wire contract.

### Boundary codec surface

Each base package owns the codecs that cross storage/wire boundaries:

| Package | JSON / wire codec | DB adapter |
|---------|-------------------|------------|
| `money` | `money_to_wire` / `money_from_wire`; `exchange_rate_to_wire` / `exchange_rate_from_wire` | `money_to_db_fields` / `money_from_db_fields`; `exchange_rate_to_db_fields` / `exchange_rate_from_db_fields` |
| `ratio` | `ratio_to_wire` / `ratio_from_wire` | `ratio_to_db_value` / `ratio_from_db_value` |
| `quantity` | `quantity_to_wire` / `quantity_from_wire` | `quantity_to_db_fields` / `quantity_from_db_fields` |
| `unit_price` | `unit_price_to_wire` / `unit_price_from_wire` | `unit_price_to_db_fields` / `unit_price_from_db_fields` |

Wire codecs serialize decimals as JSON strings, never JSON numbers. DB adapters
return exact `Decimal` storage fields plus their semantic key (`currency` or
`unit`) where applicable. Malformed boundary payloads raise typed base-package
errors (`Invalid*PayloadError` or `FloatNotAllowedError`), giving application
code one place to audit and translate failures.

The Decimal-scalar mechanics shared by every package's codec — the canonical
wire string form (`decimal_to_wire`), the construction-time coercion
(`coerce_decimal`), and the wire-parse / mapping / field triad (`WireCodec`) —
live once in a single `decimal_scalar` module per layer (`common/decimal_scalar.py`
and its `apps/backend/src` mirror), parameterized by each package's typed errors.
It is dependency-light substrate, not a fifth base package, so the family stays
bounded (§2). Routing every package through it is enforced by AC12.36, so the
per-package codec bodies cannot silently re-duplicate.

Runtime service code should keep the owning value type alive once a raw storage
field crosses into business logic. For example, backend services should turn a
quantity DB `Decimal` into `Quantity(value, unit).quantize()`, call methods such
as `quantity.is_zero()` during calculations, and only use `quantity.value` when
writing ORM fields or SQL predicates. Moving service-local `_quantity*` wrappers
into package-level Decimal-to-Decimal helpers is still drift: it hides the value
type instead of making it the narrow waist.

### Forbidden raw Decimal zones

Raw `Decimal` is forbidden as naked business semantics in migrated
service/domain calculations and frontend application code. In those zones:

- money math must construct `Money`, and cross-currency conversion must call
  `money.convert(Money, ExchangeRate)`;
- percentage/proportion math must construct `Ratio`;
- quantity comparisons and quantity arithmetic must construct `Quantity`;
- repeated DB-field quantization/zero checks must keep `Quantity` objects in
  business code and use `.value` only at DB/model/SQL boundaries;
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
7. **Serialization + storage adapters** — to/from the wire as **strings**
   (never JSON float) and to/from exact DB fields through package-owned helpers.
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

- `money`: [common/money/readme.md#money-type](https://github.com/wangzitian0/finance_report/blob/main/common/money/readme.md#money-type), `common/money/`, `apps/backend/src/money/`, `apps/frontend/src/lib/money/`
- `ratio`: [EPIC-012 AC12.9](../project/EPIC-012.foundation-libs.md), `common/ratio/`, `apps/backend/src/ratio/`, `apps/frontend/src/lib/ratio/`
- `quantity`: [EPIC-012 AC12.30](../project/EPIC-012.foundation-libs.md), `common/quantity/`, `apps/backend/src/quantity/`, `apps/frontend/src/lib/quantity/`
- `unit_price`: [EPIC-012 AC12.32](../project/EPIC-012.foundation-libs.md), `common/unit_price/`, `apps/backend/src/unit_price/` (frontend `apps/frontend/src/lib/unit_price/` is a P2 follow-up — no frontend call sites today; conformance vectors are already language-neutral so adoption is additive)
