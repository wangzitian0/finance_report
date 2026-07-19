# `counter` — per-(user, key) tallies (middleware package)

> The **canonical worked example of the package model** (a package = DDD bounded
> context). Model spec: [`../meta/readme.md`](../meta/readme.md).
> Machine contract: [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).
>
> This `common/counter/` directory is the **spec + review surface**; the
> conforming implementation lives at
> [`apps/backend/src/counter`](../../apps/backend/src/counter)
> (`contract.implementations["be"]`).

## Why

## Bounded-context decision

`counter` owns the small tally model: namespaced keys, non-negative counts, and
the `counter.Incremented` fact emitted when its own tally changes. It consumes
the `platform` EventBus/outbox as a consumer port rather than owning generic
event delivery. It does not own reporting interpretation, business metrics,
workflow, routing, or cross-domain orchestration. The machine-readable context
boundary and relationship are declared in [`contract.py`](./contract.py).

Insight reports ask "**how many times did X happen** — overall, or for this
user?". `counter` is the small, reusable middleware capability that answers that:
it tallies named events per user and lets a report read either the per-user count
or the global count (sum across users).

**Status (2026-07-09, issue #1672):** this is real, in a real reusable shape —
but currently unwired. No router or report-generation path calls
`increment`/`get_count` today; `identity` and `pricing` reference its
*pattern* in comments ("like `counter`'s `CounterTally`") without importing
it. It already served its original purpose (the worked example the
package-model migration's Step 0 built to prove the base/extension/data +
repository-split shape — `platform` and others copied it). Decision: **keep
it** — the shape is sound and cheap to carry, and a real "how many times did
X happen" insight-report surface is plausible future scope, not invented
scope. If you're looking for where it's called from in production: it isn't
yet. Wire it to a real caller when that surface gets built, or open a fresh
issue to retire it if it's still unwired by 2027-07-09 (a year past this
note).

## Ubiquitous language

- **Key** — a *namespaced counter identity*: a lowercase dotted `domain.action`
  string such as `report.generated` or `statement.uploaded`. The shape is
  validated, so an invalid key is unrepresentable (`InvalidCounterKeyError`).
  `CounterKey` is this package's self-owned SSOT term.
- **Count** — a *non-negative tally*. A negative count is meaningless and cannot
  be constructed (`NegativeCountError`).
- counting is **per (user, key)**: each `increment` only ever bumps *that user's*
  tally for *that key*.
- a **query** returns either the **per-user** count (a concrete `user_id`) or the
  **global** count (`user_id=None`, summed across all users).
- **`Incremented`** — the domain event published on each increment. It is a
  `platform` **`DomainEvent`** (`event_type="counter.Incremented"`, with
  `user_id`/`key`/`count`/`at` in its `payload()`); other contexts (e.g. report
  generation) react to it without importing this package's internals.

## Usage

```python
from src.counter import CounterKey, increment, get_count
from src.platform import RecordingEventBus

key = CounterKey("report.generated")

# write (pure op): bump this user's tally; publish Incremented through any EventBus
bus = RecordingEventBus()
new_count = increment(repo, user_id=user_id, key=key, bus=bus)  # Count(1), Count(2), ...

# read: per-user vs global
mine    = get_count(repo, key=key, user_id=user_id)            # this user's count
overall = get_count(repo, key=key)                             # global (all users)
```

`repo` is any `CounterRepository` (the store port); `bus` is any platform
`EventBus`. Ops are pure and DB-free, so in tests an in-memory fake repo + a
`RecordingEventBus` satisfy the ports. In production the async boundary does the
**atomic** write — bump + outbox event in one transaction — and a thin read:

```python
from src.counter import record_increment, read_count

# write: bump the tally AND enqueue counter.Incremented into the platform outbox,
# both in `db`'s transaction; the caller's single commit makes them atomic.
new_count = await record_increment(db, user_id=user_id, key=key)
await db.commit()

# read: thin async read for reporting
overall = await read_count(db, key=CounterKey("report.generated"))   # Count
```

## Layers (base / extension)

The implementation converges into the package model's internal layers
(the then-role folders `types/ops/store/api` were re-layered in #1418):

| layer | what lives here |
|-------|-----------------|
| `base/types/` | `CounterKey`, `Count`, `Incremented` (a platform `DomainEvent`) + typed errors (pure; no I/O) |
| `base/ops/` | `increment` (publishes `Incremented` through an `EventBus`) and `get_count` (per-user/global), over the repository **port** |
| `base/repository.py` | `CounterRepository` (a `typing.Protocol` port — mechanism B's base half) |
| `extension/sql.py` | `SqlCounterRepository`/`CounterTally` (the SQLAlchemy adapter — the only module that touches the ORM) |
| `extension/facade/` | `read_count` (thin async read) and `record_increment` (atomic write: tally bump + outbox event in one transaction) |

Dependency rule (DAG, down only): `extension → base` and never back, and the
package depends downward on the `platform` package (the
`DomainEvent`/`EventBus`/outbox substrate) — declared in `contract.depends_on`.
The ORM/`AsyncSession` lives only in `extension` and never leaks into `base`.

## Public vs internal

**Public** (`__all__`, == `contract.interface`): `CounterKey`, `Count`,
`Incremented`, `increment`, `get_count`, `CounterRepository`, `read_count`,
`record_increment`, and the errors `CounterError`, `InvalidCounterKeyError`,
`NegativeCountError`.

**Internal** (not importable as public language): `SqlCounterRepository`,
`CounterTally` (the table model), and module internals. Persistence is an
implementation detail behind the `CounterRepository` port.

## Storage

`counter_tally(user_id, key, count)` with a composite primary key `(user_id, key)`
(which is also the unique constraint and the upsert conflict target) and a
`count >= 0` check. `bump` is a single atomic upsert-increment
(`INSERT ... ON CONFLICT (user_id, key) DO UPDATE SET count = count + 1`), so
concurrent increments cannot lose updates. Migration:
`apps/backend/migrations/versions/0048_counter_tally.py`.

## Governance

The package's ACs (`AC-counter.1.1`–`AC-counter.1.4`) live in [`contract.py`](./contract.py)'s
`roadmap` and are sourced **directly** from there into the AC registry (no EPIC
mirror); its invariants pin to the tests that prove them.
`tools/check_package_contract.py` validates the implementation against this
contract (interface == `__all__`, every test reference resolves, no upward import
edge).
