# `platform` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] First runtime capability of the meta layer: a domain EventBus via the
      transactional outbox pattern (one shared Postgres table, no broker).
- [x] `DomainEvent` base value type; `OutboxEventBus` adapter (atomic write in
      the caller's session); `SubscriberRegistry`; `RecordingEventBus` fake.
- [x] `OutboxRelay` (`run_once` / `run_forever` shape) — post-commit, at-least-
      once dispatch; handlers documented as idempotent.
- [x] Shared `outbox` table + migration `0049_add_outbox`.
- [x] `counter` emits `counter.Incremented` through the outbox, atomic with the
      tally bump (`counter.api.record_increment`).
- [x] ACs `AC25.7.1`–`AC25.7.5` sourced directly from the contract `roadmap`.

## Next

- [ ] **UnitOfWork / Clock / Repository** seams: lift the session + `now()` +
      outbox-write into explicit collaborators so producers depend on ports, not
      on `AsyncSession`/`datetime.now` directly.
- [ ] **Durable relay worker**: wire `run_forever` as a real background task /
      periodic job (today only `run_once` is exercised; no always-on worker).
- [ ] **Prefect adapter** and a **`LISTEN/NOTIFY`** fast-path so the relay wakes
      on enqueue instead of polling.
- [ ] Dead-letter / retry-count handling for a handler that keeps failing.
- [ ] A typed subscriber surface (rehydrate to the producer's concrete event
      subclass) once a consumer needs more than the JSON payload.
