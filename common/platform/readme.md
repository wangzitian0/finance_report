# `platform` — domain EventBus via the transactional outbox (meta-layer capability #1)

> Package model: [`../governance/readme.md`](../governance/readme.md). Machine
> contract: [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).
>
> This `common/platform/` directory is the **spec + review surface**; the
> conforming implementation lives at
> [`apps/backend/src/platform`](../../apps/backend/src/platform)
> (`contract.implementations["be"]`).

## Why

This is the **first runtime capability of the meta layer**: a single, reusable
way for any bounded context to *publish a domain event as a fact* and for others
to *react* to it — without the producer knowing its consumers, and without losing
the event if the process dies. It does this with **no new infrastructure**: one
Postgres table, no message broker, no Prefect, no `LISTEN/NOTIFY`.

## The transactional outbox in one paragraph

A producer `publish`es a **DomainEvent** through an **OutboxEventBus** built from
the *same* `AsyncSession` that is making the domain state change. The bus INSERTs
the event into the shared **outbox** table **in that transaction**, so the event
and the state change **commit together or roll back together** — they are atomic
by construction (there is no window where one persists without the other). A
separate **OutboxRelay** later reads committed `pending` rows in id order,
dispatches each to the subscribed handlers, and marks them `published`. Because
the relay only ever reads already-committed rows, **dispatch is inherently
post-commit**.

```
producer ──publish(event)──▶ OutboxEventBus ──INSERT──▶ outbox(status=pending)
                                                          │  (same txn as the
                                                          │   domain write)
                              caller commit() ────────────┘
                                                          ▼
OutboxRelay.run_once() ──read pending, in order──▶ handler(event) ──▶ mark published
```

## Ubiquitous language

- **DomainEvent** — an immutable fact that already happened. Carries a namespaced
  `event_type` (`"<pkg>.<Name>"`, the routing key) and `occurred_at` (UTC);
  subclasses add fields and override `payload()` to expose them as the JSON body
  persisted to the outbox.
- **outbox** — the one shared table (owned by this package) every producer
  enqueues into. A row is `pending` until the relay has delivered it, then
  `published`.
- **relay** — the post-commit dispatcher. Reads committed `pending` rows in order
  and invokes subscribed handlers.
- **at-least-once + idempotent** — if a pass crashes after a handler runs but
  before the row is marked `published`, the row is redelivered on the next pass.
  So **handlers MUST be idempotent**: processing the same event twice must have
  the same effect as once (key side effects by the event's aggregate / a dedupe
  key).

## Usage

```python
from src.platform import OutboxEventBus, OutboxRelay, SubscriberRegistry

# write side — atomic with the domain change (same session, one commit)
bus = OutboxEventBus(db, source_pkg="counter")
bus.publish(event)            # enqueues a pending outbox row in db's transaction
await db.commit()             # event + state change commit together

# read side — post-commit dispatch (run as a periodic background task; see below)
registry = SubscriberRegistry()
registry.subscribe("counter.Incremented", my_idempotent_handler)
relay = OutboxRelay(registry)
await relay.run_once(relay_session)   # drains one batch of pending rows
```

`RecordingEventBus` is an in-memory fake for unit tests that assert *what was
published* without a database.

## Running the relay (deferred — not wired here)

`run_once(session)` drains one batch; `run_forever(session_factory)` is the shape
of a durable poll loop. **No always-on worker is wired in this slice** — by
design. In production the relay would run as a periodic background task (e.g. an
app-startup `asyncio` task, a cron/`schedule`d job, or — later — a Prefect flow).
That durable worker, plus a `LISTEN/NOTIFY` fast-path, is explicitly future work
([`todo.md`](./todo.md)).

## Roles (files converge by role)

| role | what lives here |
|------|-----------------|
| `events/` | `DomainEvent` (event base), `EventBus` port + `OutboxEventBus`/`RecordingEventBus`, `SubscriberRegistry`, `OutboxRelay` |
| `store/` | the shared `Outbox` ORM table + `OutboxRepository` (the only role that touches the ORM/session) |

Dependency rule (DAG, down only): the package imports nothing registered — only
the unregistered `src.database` (Base/`AsyncSession`). That is why its `klass` is
**`kernel`** (a leaf): a `platform` consumer like `counter` may import it as a
strictly downward edge. See [`contract.py`](./contract.py) for the full rationale.

## Public vs internal

**Public** (`__all__`, == `contract.interface`): `DomainEvent`, `EventBus`,
`OutboxEventBus`, `RecordingEventBus`, `SubscriberRegistry`, `OutboxRelay`,
`Outbox`, `OutboxRepository`.

**Internal**: the rehydration helper in `relay.py` and module internals.

## Storage

`outbox(id bigserial pk, occurred_at timestamptz, event_type text, source_pkg
text, aggregate_id text null, payload jsonb, status text default 'pending',
published_at timestamptz null)` with an index on `(status, id)` backing the
relay's "oldest pending, in order" drain. `status` is plain text (not a
`sa.Enum`) so a future lifecycle state needs no enum migration. Migration:
`apps/backend/migrations/versions/0049_add_outbox.py`.

## Governance

The package's ACs (`AC-platform.1.1`–`AC-platform.1.5`) live in [`contract.py`](./contract.py)'s
`roadmap` (carrying `tier: PC`, EPIC-026's authority-tier model) and are sourced
directly from there into the AC registry; its invariants pin to the DB-backed
tests that prove atomicity and post-commit dispatch.
`tools/check_package_contract.py` validates the implementation against this
contract.
