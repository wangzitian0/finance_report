# `counter` — per-(user, key) tallies (platform package)

> The **first worked example of the package model** (a package = DDD bounded
> context). Model spec: [`docs/ssot/package-model.md`](../../../../docs/ssot/package-model.md).
> Machine contract: [`contract.py`](./contract.py).

## Why

Insight reports ask "**how many times did X happen** — overall, or for this
user?". `counter` is the small, reusable platform capability that answers that:
it tallies named events per user and lets a report read either the per-user count
or the global count (sum across users).

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
- **`Incremented`** — the domain event published on each increment
  (`user_id`, `key`, `at`); other contexts (e.g. report generation) react to it
  without importing this package's internals.

## Usage

```python
from src.counter import CounterKey, increment, get_count

key = CounterKey("report.generated")

# write: bump this user's tally; returns the new per-user Count, emits Incremented
new_count = increment(repo, user_id=user_id, key=key)          # Count(1), Count(2), ...

# read: per-user vs global
mine   = get_count(repo, key=key, user_id=user_id)             # this user's count
overall = get_count(repo, key=key)                             # global (all users)
```

`repo` is any `CounterRepository` (the store port). Ops are pure and DB-free, so
in tests an in-memory fake satisfies the port. In production the SQL adapter is
awaited at the boundary:

```python
from src.counter.api import read_count   # thin async read for reporting
overall = await read_count(db, key=CounterKey("report.generated"))   # Count
```

## Roles (files converge by role)

| role | what lives here |
|------|-----------------|
| `types/` | `CounterKey`, `Count`, `Incremented` value objects + typed errors (pure; no I/O) |
| `ops/` | `increment` (emits `Incremented`) and `get_count` (per-user/global), over the store **port** |
| `store/` | `CounterRepository` (a `typing.Protocol` port) + `SqlCounterRepository`/`CounterTally` (the SQLAlchemy adapter — the only role that touches the ORM) |
| `api/` | `read_count` — the thin async boundary that bridges an `AsyncSession` to a `Count` for reporting |

Dependency rule (DAG, down only): `api → ops → {types, store}`. The
ORM/`AsyncSession` lives only in `store`/`api` and never leaks into `types`/`ops`.

## Public vs internal

**Public** (`__all__`, == `contract.interface`): `CounterKey`, `Count`,
`Incremented`, `increment`, `get_count`, `CounterRepository`, `read_count`, and
the errors `CounterError`, `InvalidCounterKeyError`, `NegativeCountError`.

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

The package's ACs (`AC25.6.1`–`AC25.6.4`) live in [`contract.py`](./contract.py)'s
`roadmap`; its invariants pin to the tests that prove them.
`tools/check_package_contract.py` validates this package against its contract
(interface == `__all__`, every test reference resolves, no upward import edge).
