# `audit` — the number governor

> The **number** governor, the parallel peer to [`meta`](../meta/readme.md) the
> **form** governor. `meta.base` is the package model everyone's *structure*
> conforms to; `audit.base` is the **value language** everyone's *numbers* are
> expressed in. Both are foundational *and* governing — one for form, one for
> number (the "meta / audit symmetry" in
> [`../meta/migration-standard.md`](../meta/migration-standard.md)).

## What audit governs

- **`audit.base`** — the value language: the cross-runtime Shared-Kernel value
  types (`Money` / `Currency` / `ExchangeRate` /
  `CurrencyBalances` / `Ratio` / `Quantity` / `Unit` / `UnitPrice`), plus audit's
  own base value objects (financial invariants, confidence / provenance, and the
  `TraceRecord` assurance boundary).
- **`audit.extension`** — reaches the financial flow (`ledger` / `extraction` /
  `portfolio` / `reporting`) to assert global numeric correctness and end-to-end
  traceability. The four cross-package invariants are formalized (closeout
  #1429) as `AC-audit.global-invariant.1`-`.4` in `contract.py`'s `roadmap`,
  each pinned to an already-green cross-package test in `ledger`/`reporting`/
  the e2e suite — a physical `audit.extension` module is not required for
  this, since the invariants are proven by tests that already span packages.
- **`audit.data`** — fixed-cohort confidence projections over current
  `TraceRecord` supersession heads.

Everyone's `base` ultimately depends on `audit.base` (the value types), so
`audit.extension` reaching the whole flow is what lets audit govern the numbers —
the symmetric mirror of `meta.extension` reaching every package to govern
structure.

## TraceRecord assurance boundary

`TraceRecord` is the single append-only language for executable assurance. An
`OBSERVATION` records an actual measurement; a `DECISION` is a fail-closed fold
over exact parent records. Static contracts, workflow conclusions, mutable
labels, and file existence cannot construct authority by themselves.

Cross-package bulk reads use audit's public
`current_authoritative_trace_decision_projection(scope)` rather than importing
the trace ORM. It returns only financial decisions whose own and parent records
remain current; consumers join it to their immutable local reference and never
reconstruct trace validity.

A consumer that knows its decision ids calls
`current_authoritative_trace_decisions(db, scope, decision_ids)`. One statement
reads only these ids. A caller that runs many such reads for one result opens
`shared_current_authority(db, scope)`: in the block, each read of the same
session and scope uses one read of the projection. A TraceRecord write on the
session in the block ends that reuse, so the block never reports a superseded
decision as current. The package evaluation opens one block per evaluation
(#2602).

Cross-package contributions carry a `TraceDecisionRef`, the lightweight exact
coordinates `(decision_id, target, assertion)` of the decision they resolved.
The consuming package must compare all three coordinates with its scope-bound
current projection; an opaque decision id alone cannot authorize a different
fact or policy.

Every record pins a typed tenant/repository/environment scope, target and
assertion versions, target class, the existing CODE/LLM tier and proof-kind
profile, provenance, execution stage/id, causality mode, evidence
manifest digest, result, producer version, parent ids, and optional supersession.
Scores use `Ratio`; raw financial values, documents, prompts, identities, and
secrets are not valid record fields. Package composition adapters must use only
opaque technical ids, never user or document text, for scope, target, assertion,
execution, version, provenance, and reason fields. The canonical JSON codec is
shared by JSONL and JUnit observation adapters. It rejects decision restore;
the SQL repository reconstructs decisions from typed columns only while replaying
their registered policy over the complete parent graph.

Record ids are UUID5 values derived from the canonical semantic digest. Rewriting
the same observation therefore stays idempotent, while changing any assurance
input creates a new id. Correction appends a record whose `supersedes_id` points
to the prior head; the prior row is never mutated. A head is a record not named
by another record's `supersedes_id`. Stable target kind/id plus assertion kind/id
form a `TraceLineage`; their versions remain exact pins and may advance through
supersession. Observations may coexist across executions. Only authoritative
decision heads are singleton, serialized under a transaction-scoped advisory
lock so authority cannot fork.

The repository keeps two deliberately different reads. `current_decision()` is
the fail-closed authority view and returns a record only while its complete
ancestry is current. `decision_head()` returns a `TraceDecisionHead` containing
the physical singleton head plus `ancestry_current`; this prevents a writer from
collapsing "no decision has ever existed" and "a decision exists but its evidence
was superseded" into the same `None` state. Cross-package consumers use this
typed port rather than reading audit tables or recovering the physical head from
timestamps.

The production repository stores common fields in typed columns and parents in
scope-bound link rows. ORM guards and PostgreSQL triggers reject update/delete,
and a sealed parent count prevents a later link insert from rewriting a decision.
The persisted graph is acyclic. Repository validation rejects missing,
cross-scope, stale, skipped, or unproven decision parents. DIRECT rejects
cross-target/cross-execution parents;
MANIFEST accepts them only through a versioned policy's complete parent set. An
LLM-produced financial observation requires a same-target CODE-ONLY
invariant/promotion decision parent before an authoritative decision can exist.

`TraceEmitter.emit_many()` hands an ordered causal set to `append_many()` when
the repository has it. `append_many()` applies the checks of `append()` and
persists the same rows. It sends a fixed number of statements, whatever the size
of the set: one lock statement, one existence read, one head read, and two
inserts. A set with a supersession keeps the per-record path, because a
supersession changes the heads that the later records of the set read. After an
append, the repository knows the new record, its head state, its current
ancestry and the decision head of its lineage. Later reads in the same unit of
work use that memo without a statement (#2612). The memo ends at a commit, and at
a rollback of the unit of work or of a savepoint.

Each package injects `TraceEmitter` at its composition boundary and flushes the
complete causal set into the same caller-owned transaction as the authoritative
side effect; the emitter never commits or rolls back independently. Any append
failure propagates so the package UoW must roll back both. There is no
process-global emitter, mutable authority registry, or promotion shadow adapter.
See the language-neutral contract at
[`trace/contract/trace_record.contract.md`](trace/contract/trace_record.contract.md).

## Terminal audit

`TerminalAuditVerifier` consumes one selected frozen package decision, its exact
manifest decision coordinates, and the canonical testing `TraceRecord` emitted
after pytest's real call-phase PASS. Repository reads replay the owning policies;
the verifier only checks exact scope, type, result, coordinates, and direct
decision-parent membership. It neither reconstructs package policy nor requires
frozen history to remain the current lineage head.

Success emits one ordinary `TraceRecord` observation through the existing codec.
There is no certificate schema, verdict model, persisted projection, runtime
source-tree scanner, or second assurance entity. Failure is a non-zero,
redaction-safe first-boundary diagnostic; owner packages retain their own
producer, reader, and deletion gates.

<a id="deletion-ownership"></a>
## Deletion ownership

`ondelete="CASCADE"` is a hidden cross-aggregate write. Audit owns the exact
declaration-level inventory in `data/fk-cascade-ownership.json`; its extension
discovers production foreign-key declarations, resolves their source and target
owners, expands mixin declarations to mapped consumers, and fails closed on an
opaque policy, unresolved ownership, an empty scan, duplicate, or unclassified
site. `aggregate_internal` is the sole approved class. `purge_owned`,
`cross_domain`, and `retention_sensitive` sites are explicit #1848 debt, pinned
by `data/fk-cascade-debt-baseline.json` so that the set can only shrink.

## The Shared Kernel now lives inside audit

The four value domains (`money` / `ratio` / `quantity` / `unit_price`) are a
cross-runtime **Shared Kernel**: a language-neutral standard
(`common/audit/<domain>/contract/*.contract.md` + `conformance/vectors.json`)
with the one editable Python source in `apps/backend/src/audit/<domain>`, a locked
Python mirror in `common/audit/<domain>` (see the next section) and a TypeScript
mirror in `apps/frontend/src/lib/audit/<domain>` (where a frontend mirror exists),
kept in lockstep by the conformance vectors —
content unchanged by the fold, only relocated. Each domain stays an internal
**submodule** of `audit` rather than flattening into one namespace: several
symbol names collide across domains (`FloatNotAllowedError` is defined
independently in every domain), so a consumer reaches domain-specific
errors via `from src.audit.money import FloatNotAllowedError`. Only the 10
non-colliding value-object classes are re-exported flat at `audit`'s root
(`from src.audit import Money`) — exactly the `units` this contract declares.
Backward compatibility of the language-neutral contracts and conformance vectors
is sacred; only the physical location and Python/TS import path changed.

### Two Python trees, one editable source

`apps/backend/src/audit` is the one editable source of the Python kernel. Edit the
backend file first, then apply the same change to the file of the same name in
`common/audit`. The mirror stays because two consumers cannot import the backend
tree. The backend image copies only `src`, so `src` cannot import `common`. The
bare-Python CI jobs (the `lint` gates that run through `uv run --with pyyaml`,
`ac-traceability`, `ac-behavioral-ratchet`, `evidence-bundle`, the staging AI/OCR
gate and the E2E virtualenv) install neither the backend nor SQLAlchemy, and
`src/audit/__init__.py` imports SQLAlchemy at import time, so `common.testing`
cannot import `src.audit`. `common/audit` therefore stays standard-library only.

`tests/tooling/test_audit_mirror_lock.py` (AC-audit.43.1) locks the two trees. It
compares the AST of every Python module pair, without docstrings and import order
(ruff line length is 120 in the backend and 88 here). A module that exists in one
tree only, a backend-only definition inside a twin, and a name that one package
surface publishes alone appear in an explicit list with the reason. A module in
neither list fails the test, so a second copy cannot return silently. The test
rewrites the module names of import statements only, so a string constant that names
the other tree counts as a difference. The four TraceRecord files (`base/trace.py`,
`base/trace_repository.py`, `extension/trace_codec.py`, `extension/trace_adapters.py`)
also keep docstrings and import order. A second test fails when a file under
`common/` or `tools/` imports a backend-only module.

### Two digest definitions (AC-audit.44.1, AC-audit.44.2)

`apps/backend/src/audit/digest.py` holds the two SHA-256 definitions of the backend:
`canonical_json_digest(value)` hashes sorted, compact JSON (`default=str`), and
`text_digest(text)` hashes one UTF-8 string. The canonical digest of a string has quotes,
so it differs from the text digest of the same string. Trace records, command digests, result ids
and policy versions store these values: keep the bytes. The module is backend-only and has no mirror.
`tests/tooling/test_digest_single_definition.py` fails when a function in `apps/backend/src`
combines `hashlib.sha256` with `json.dumps(sort_keys=True)`, or hashes `<str>.encode()`, outside
that module and outside its list of other byte forms and file hashes. The bare-Python
`common/testing/executed_proof.py` keeps its own canonical digest because tooling cannot import `src.audit`.

The membership rule for what earns a Shared-Kernel value package, the canonical
structure every one must follow, and the raw-`Decimal` boundary policy are
internalized below in [§Base packages (value-type narrow waists)](#base-packages)
— `audit` is the number-governor that declares this value family, so the family
doc lives here per the package-migration standard
([`../meta/migration-standard.md`](../meta/migration-standard.md), step 3 "SSOT
internalized").

Monetary values are `Decimal`-backed and never use `float`; money rounds with
banker's `HALF_EVEN`. audit's `no-float-in-money-narrow-waist` invariant pins this
to the existing narrow-waist guard test. See: common/ledger/readme.md#decimal-rule

## Migration state (issue #1419, Stage 1 of umbrella #1416)

Three-step sequence, each a separate merge-gated PR:

- **Step 1 (done)** — the four value domains are physically folded into
  `audit`: `common/{money,ratio,quantity,unit_price}` →
  `common/audit/<domain>`, `apps/backend/src/{money,ratio,quantity,unit_price}` →
  `apps/backend/src/audit/<domain>`, `apps/frontend/src/lib/{money,ratio,quantity}`
  → `apps/frontend/src/lib/audit/<domain>` (frontend `unit_price` mirror doesn't
  exist yet — unrelated P2 follow-up). All ~85 consumer files (routers, services,
  models, schemas, the frontend app tree) repointed to the new paths. The
  package's layer changed with the move (at the time, a `klass` flip
  `platform` → `kernel`; today placement is `infra`, resolved from the central
  `PACKAGE_LAYER` map — contracts no longer self-declare a `klass`);
  `implementations`/`interface` populated
  (10 value-object classes, flat re-export). Old locations deleted entirely — no
  re-export shim, no residue.
- **Step 2 (done here)** — transferred AC *ownership* of the value-language
  ACs (`AC2.19`/`AC2.20` in EPIC-002, `AC12.9`/`AC12.30`/`AC12.32`/`AC12.33`/
  `AC12.36` in EPIC-012) into audit's `roadmap` as `AC-audit.<n>.<n>` (20
  roadmap ACs total, including the pre-existing `AC-money.22.3`/`AC-money.23.1`
  leftovers). Every `@ac_proof(ac_ids=[...])` edge, BE/FE traceability
  docstring/comment, and the tier baseline
  (`common/meta/data/ac-tier-baseline.json`, shrunk via
  `check_ac_tier_baseline.py --update`) were renamed atomically; the migrated
  EPIC table rows were deleted and replaced with disclaimer paragraphs. No AC
  lives in both an EPIC table and a package roadmap (`check_epic_package_dual`
  enforces it).
- **Step 3 (next, separate PR)** — close out any remaining residual references
  (docs/SSOT cross-links, historical mentions) issue #1419 surfaces.
- **Also deferred, unrelated to #1419's 3-step sequence** — remaining audit
  confidence/provenance folds. TraceRecord landed under #1906. The `extension`
  reach into the financial flow is no longer fully deferred: its four
  cross-package numeric-governance invariants are formalized as
  `AC-audit.global-invariant.1`-`.4` (closeout #1429, see [What audit
  governs](#what-audit-governs) above); only a *physical* `audit.extension`
  module (as opposed to roadmap ACs pointing at tests that already live in
  the governed packages) remains a later fold.

## Source-type trust hierarchy (provenance)

*(Internalized from the former `docs/ssot/source-type-priority.md`, migration closeout
wave 3, #1664; the pointer stub itself was retired in #1822 (SSOT
dissolution) — this is the single owner and always has been; do not re-add
a separate SSOT copy. Lives in `audit` because it's a `confidence`/`provenance`
concern — see [What audit governs](#what-audit-governs) above — and its
implementation is `apps/backend/src/audit/source_type_priority.py`.)*

`JournalEntrySourceType` (`apps/backend/src/ledger/orm/journal.py`) is the
trust hierarchy for journal-entry provenance — which source wins when two
sources disagree about the same transaction. Four user-data values, highest
to lowest trust: `manual` (TRUSTED — user typed the entry directly),
`user_confirmed` (HIGH — auto-extracted, but the user explicitly confirmed
it), `auto_matched` (MEDIUM — reconciliation matched at score ≥ 85 before
the entry became immutable; see:
[common/reconciliation/readme.md#thresholds](../reconciliation/readme.md#thresholds)
for the full ≥85 / 60-84 / <60 routing table), `auto_parsed` (LOW —
AI-extracted from a document, unconfirmed). Internal/system types (`system`,
`fx_revaluation`) sit outside this user-trust ladder. `bank_statement` was
a legacy value retired from the enum in migration 0040 (#896); its
historical rows moved to `auto_parsed` in migration 0018, no write path
emits it anymore, and `normalize_source_type` still folds any stray raw
string defensively so legacy inputs and the immutability trigger's text
guard stay harmless.

**Conflict resolution**: when two sources disagree on the same
transaction (amount, date, classification), the higher-priority source
always wins — `manual > user_confirmed > auto_matched > auto_parsed`. If
`auto_parsed` says $100.00 and `manual` says $102.50, the manual entry
prevails and the auto-parsed record is flagged superseded.

**State transitions** — `auto_parsed` is the only entry point (AI
extraction); from there: `auto_parsed → user_confirmed` (Stage-1 review
confirm), `auto_parsed → manual` (user edits and saves),
`auto_parsed → auto_matched` (reconciliation score ≥ 85 before posting),
`auto_matched → user_confirmed` (review-queue confirm),
`user_confirmed → manual` (user re-edits). `manual` is terminal — highest
trust, no further promotion.

Design constraints: always stamp `source_type` at entry creation, never
leave it null (it's optional on `POST /api/journal-entries`, defaulting
to `manual` when omitted). Reconciliation auto-accept may set
`source_type=auto_matched` only before the journal entry becomes
posted/reconciled — an immutable posted entry keeps its original
`source_type`; auto-match provenance for an already-posted entry is
represented by `ReconciliationMatch` and its normalized anchor links
instead. Log both the winning and losing `source_type` in the audit trail
(`ReconciliationMatch.score_breakdown`) when resolving a conflict. Never
downgrade `source_type` (e.g. `manual` back to `auto_parsed`); never
silently overwrite a `manual` entry with `auto_matched` data — require
explicit user action; never omit `source_type` when creating journal
entries via the API. The field is immutable after creation except through
explicit promotion endpoints (Stage-1 approve, review-queue confirm).

<a id="base-packages"></a>

## Base packages (value-type narrow waists)

> Internalized from the retired `docs/ssot/base-packages.md` (the value-package
> family doc) per the package-migration standard
> ([`../meta/migration-standard.md`](../meta/migration-standard.md), step 3 "SSOT
> internalized"). `audit` is the number-governor that declares this value family,
> so the membership rule and the canonical per-package structure live here.
>
> **Core definition**: the family of shared value-type "narrow waist" packages,
> the rule for what qualifies, and the canonical structure every one must follow.

A *base package* is a small, dependency-light value type that makes a class of
bad states unrepresentable and is shared, by a **language-neutral standard**,
across every end (backend Python + frontend TypeScript). `money` (#1167) is the
reference instance; this generalises it so the family stays uniform and bounded.

In the package model this value family **is** the project's **Shared Kernel** —
the canonical ubiquitous language (`money`/`ratio`/`quantity`/`unit_price`) that
every package reuses, whose strategic role is "shared by everyone" and whose
implementation therefore lives in `common/`. The family's structure, layering,
and how each package migrates onto the model are owned by the package migration
standard: [`../meta/migration-standard.md`](../meta/migration-standard.md)
(see "Where files go" and "Completion state"). This section owns the *membership
rule* (what earns a Shared-Kernel value package) and the per-package value
contract.

### 1. What qualifies (all five must hold)

A domain earns a base package only if it is **all** of:

1. **A shared algorithm** — real computation, not just a DTO.
2. **Cross-language** — computed/rendered on both backend and frontend, so the two
   can drift.
3. **Correctness-critical** — a wrong value is a real bug.
4. **Currently ad-hoc / duplicated** — no single standard today.
5. **A primitive, not business logic** — domain-specific weights/policies
   (reconciliation scoring, attention ranking, source-type rules) do **not**
   qualify; they consume primitives, they are not primitives.

### 2. The family (bounded on purpose)

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
zero-denominator fallback `fraction_or_zero`. These let business code stay typed instead of re-deriving
`sum(..., Decimal("0"))`, `amount <= Decimal("0")`, or `abs(a-b) < Decimal("0.01")`
(EPIC-012 AC12.33, #1253).

### 3. Raw Decimal boundary policy

`Decimal` is the storage/interchange substrate for exact numeric values; it is
not, by itself, a business value type. Once a value crosses into service/domain
logic, code should use the MECE base element that owns the semantics:

- `Money` for currency amounts and same-currency arithmetic;
- `ExchangeRate` inside `money` for directed cross-currency conversion;
- `Ratio` for dimensionless proportions, percentages, and shares of a whole;
- `Quantity` for shares, units, lots, contracts, and quantity comparisons.

#### Allowed raw Decimal boundaries

Raw `Decimal` is allowed only as a physical substrate where the surrounding
layer is explicitly a boundary or test fixture. Hand-written semantic conversion
at those boundaries must construct the owning base-package value type, not use
local `Decimal(str(...))` helpers.

1. **Base packages** — `common/audit/money`, `common/audit/ratio`, `common/audit/quantity` and the
   backend/frontend runtime copies may use `Decimal`/`decimal.js` internally.
2. **DB models and migrations** — SQLAlchemy `Numeric` columns, Alembic
   migrations, and repository/query predicates store exact numeric values; code
   that turns storage fields into business values must construct the owning value
   type, such as `Money(amount, currency)`, `Ratio(value)`, or `Quantity(value, unit)`.
3. **Schemas and API contracts** — Pydantic/TypeScript API shapes may expose
   exact decimals as string-backed fields while preserving existing wire shapes.
   Python has no wire codec; the TypeScript twin keeps its own.
4. **Parser and provider adapters** — OCR, CSV/PDF parsers, market-data
   providers, and import adapters may parse external numbers into raw
   `Decimal` before handing them to domain services, then immediately cross the
   boundary through the typed package.
5. **Tests, fixtures, and generated code** — tests may build exact inputs and
   assert exact outputs; generated API types may mirror the wire contract.

#### No Python boundary codec

The Python kernel has no wire or DB codec for the value types. No production code
called one, so #2698 deleted the 20 functions and their four `wire.py` modules from
both Python trees. Python code constructs the value type from a storage `Decimal`
and reads `.amount`, `.value` or `.rate` back when it writes an ORM field. The
TypeScript twin (`apps/frontend/src/lib/audit`) keeps JSON codecs that serialize
decimals as strings, never JSON numbers. #2752 deleted the Python
`Invalid*PayloadError` classes: no code raised them after the codecs went.

The construction-time coercion (`coerce_decimal`) that every value type shares
lives once in a single `decimal_scalar` module per layer (`common/audit/decimal_scalar.py`
and its `apps/backend/src` mirror), parameterized by each package's
`FloatNotAllowedError`. It is dependency-light substrate, not a fifth base package,
so the family stays bounded (§2). Routing every package through it is enforced by
AC12.36, so the per-package coercion bodies cannot silently re-duplicate.

Runtime service code should keep the owning value type alive once a raw storage
field crosses into business logic. For example, backend services should turn a
quantity DB `Decimal` into `Quantity(value, unit).quantize()`, call methods such
as `quantity.is_zero()` during calculations, and only use `quantity.value` when
writing ORM fields or SQL predicates. Moving service-local `_quantity*` wrappers
into package-level Decimal-to-Decimal helpers is still drift: it hides the value
type instead of making it the narrow waist.

#### Forbidden raw Decimal zones

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

### 4. The canonical structure (every base package has these)

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
7. **Serialization** — the TypeScript twin writes the wire as **strings** (never
   JSON float). Python has no wire or DB adapter (#2698).
8. **Typed error hierarchy** — base `XError` → `FloatNotAllowed` / `Invalid…` /
   `…Mismatch`.
9. **The language-neutral standard** — `contract/<x>.contract.md` (interface) +
   `conformance/vectors.json` (golden cases) + `shared_api` (identifier set).
10. **Per-end implementations** — backend runtime (`apps/backend/src/audit/<x>`, the
    editable source), its locked Python mirror (`common/audit/<x>`), frontend (`apps/frontend/src/lib/<x>`) — each
    conformance-tested against the **same** vectors.
11. **Three guards** — no-`float` (the money narrow-waist guard), one conformance
    suite per stack, and identifier-parity (`test_<x>_api_parity.py`).

### 5. Why per-end copies (not one shared runtime)

The frontend is TypeScript and cannot import the Python package; the deployed
images do not ship `common/`. So the **standard** (contract + conformance
vectors) is shared at *test time*, and each end keeps its own idiomatic
implementation verified against it. `common/<x>` is the reference + the home of
the standard; it is dev/test-time only, never shipped into a runtime image.

### Used by

- `money`: [common/audit/money/readme.md#money-type](https://github.com/wangzitian0/finance_report/blob/main/common/audit/money/readme.md#money-type), `common/audit/money/`, `apps/backend/src/audit/money/`, `apps/frontend/src/lib/audit/money/`
- `ratio`: [EPIC-012 AC12.9](../../docs/project/EPIC-012.foundation-libs.md), `common/audit/ratio/`, `apps/backend/src/audit/ratio/`, `apps/frontend/src/lib/audit/ratio/`
- `quantity`: [EPIC-012 AC12.30](../../docs/project/EPIC-012.foundation-libs.md), `common/audit/quantity/`, `apps/backend/src/audit/quantity/`, `apps/frontend/src/lib/audit/quantity/`
- `unit_price`: [EPIC-012 AC12.32](../../docs/project/EPIC-012.foundation-libs.md), `common/audit/unit_price/`, `apps/backend/src/audit/unit_price/` (frontend `apps/frontend/src/lib/audit/unit_price/` is a P2 follow-up — no frontend call sites today; conformance vectors are already language-neutral so adoption is additive)

## See also

- [`../meta/readme.md`](../meta/readme.md) — the form governor and the package
  model audit conforms to.
- [`../meta/migration-standard.md`](../meta/migration-standard.md) — the target
  architecture and the value→audit fold (meta / audit symmetry).
- `contract.py` — audit's machine-checkable `PackageContract`.
- [`../../vision.md`](../../vision.md) — the north star (Good Taste: backward
  compatibility of the value contracts is sacred).
