# `platform` — domain EventBus via the transactional outbox (meta-layer capability #1)

> Package model: [`../meta/readme.md`](../meta/readme.md). Machine
> contract: [`contract.py`](./contract.py).
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

## Running the relay (wired at the app composition root, #1642)

`run_once(session)` drains one batch; `run_forever(session_factory)` is the shape
of a durable poll loop. The durable worker is wired at the **app composition
root** (`apps/backend/src/main.py`), which is also where subscription happens —
the pattern every consumer package copies:

1. the composition root builds one shared `SubscriberRegistry`;
2. each consumer package publishes a wiring helper the root calls with that
   registry + the app session factory (first precedent: pricing's
   `subscribe_price_ingest`, #1642) — registration lives at the root because
   platform (L1) must never import a domain package (L3);
3. an app-startup `asyncio` background task drains the outbox each poll
   interval via `run_once` on a fresh session; a failing pass is logged and
   retried next pass (at-least-once — handlers are idempotent, so retry is
   always safe). A handler may be sync or a coroutine function; the relay
   awaits async handlers before marking the row published.

A `LISTEN/NOTIFY` fast-path, Prefect adapter, and dead-letter state are
deliberately deferred until operational evidence justifies their complexity.
They are not scheduled work; adoption requires a GitHub issue and roadmap AC.

## Layers (files converge by layer — `base` / `extension`)

The package follows the building-block layering (see
[`../meta/migration-standard.md`](../meta/migration-standard.md)), mirroring
`counter`:

| layer | what lives here |
|------|-----------------|
| `base/` | the pure core: `DomainEvent` (`event.py`), workflow request/response vocabulary (`workflow.py`), the `EventBus` **port** + `SubscriberRegistry` (`bus.py`), and the `OutboxRepository` **port** (`outbox.py`) — no I/O and no delivery-schema dependency |
| `extension/` | the impure edges: `OutboxEventBus`/`RecordingEventBus` bus adapters (`bus.py`), the `OutboxRelay` (`relay.py`), and the private `OutboxRecord` ORM table + `SqlOutboxRepository` adapter (`sql.py`, the only role that touches the ORM/session) |

The **headline** is the port/adapter split (dependency inversion, mechanism B):
the `EventBus` and `OutboxRepository` ports live in `base` so the pure core and
consumer packages depend only on abstractions, while their concrete adapters live
in `extension`. Consumers reach them through the published interface — the base
ports via `from src.platform.base import EventBus, DomainEvent`, the adapters via
`from src.platform import OutboxEventBus`.

Dependency rule (DAG, down only): the package imports nothing registered — only
the unregistered `src.database` (Base/`AsyncSession`). That is why the central
layer map places it in **`infra`** (L1, a leaf): a consumer like `counter`
(`middleware`, L2) may import it as a
strictly downward edge. See [`contract.py`](./contract.py) for the full rationale.

## Public vs internal

**Public** (`__all__`, == `contract.interface`): `DomainEvent`, `EventBus`,
`OutboxEventBus`, `RecordingEventBus`, `SubscriberRegistry`, `OutboxRelay`,
the persistence-neutral `Outbox` event record, `OutboxRepository` (the port),
and the `Workflow*` request/response value objects. `src.schemas.workflow` only
re-exports that vocabulary for delivery compatibility.

**Internal**: the `OutboxRecord` SQLAlchemy row and `SqlOutboxRepository` adapter
(reached only through its port), the rehydration helper in `extension/relay.py`,
and module internals.

## Storage

`outbox(id bigserial pk, occurred_at timestamptz, event_type text, source_pkg
text, aggregate_id text null, payload jsonb, status text default 'pending',
published_at timestamptz null)` with an index on `(status, id)` backing the
relay's "oldest pending, in order" drain. `status` is plain text (not a
`sa.Enum`) so a future lifecycle state needs no enum migration. Migration:
`apps/backend/migrations/versions/0049_add_outbox.py`.

## Governance

The package's ACs (`AC-platform.1.1`–`AC-platform.1.5`) live in [`contract.py`](./contract.py)'s
`roadmap` (carrying `tier: CODE-ONLY`, EPIC-026's authority-tier model) and are sourced
directly from there into the AC registry; its invariants pin to the DB-backed
tests that prove atomicity and post-commit dispatch.
`tools/check_package_contract.py` validates the implementation against this
contract.
