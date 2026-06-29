# `ledger` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done

- [x] SSOT internalized: the double-entry + processing-account prose lives in
      [`readme.md`](./readme.md) (slice 2 of #1420).
- [x] **Code body cutover (slice 3a of #1420)**: the implementation
      (`apps/backend/src/ledger`) adopts the building-block layering —
      `base/` (the `Entry`/`Leg` balance invariant + typed errors + the pure
      posting validators + the `JournalRepository` port), `extension/`
      (`post_entry` + the `AsyncSession` adapter), `data/` (the account-balance
      projection). `contract.py` declares the `units` (kind→layer, repository
      split, data sink) and the structural `invariants`. The double-entry tests
      moved to `apps/backend/tests/ledger/`; `_ledger_helpers` is published as the
      ledger test factory; the god-file balance-query surface in
      `services/accounting.py` was deleted (zero residue, no re-export shim).

## Next

- [ ] **slice 3b — `processing_account`**: fold the `ProcessingAccount` aggregate
      (`src/services/processing_account.py` + its tests, EPIC-015) into the package
      as a `base` aggregate referenced cross-domain by id (Decision B).
- [ ] **slice 3c — AC migration**: move the EPIC-002 / EPIC-012 (AC12.34) /
      EPIC-015 double-entry ACs into the contract `roadmap` as
      `AC-ledger.<entity>.<seq>`, removed from the EPIC tables (atomic), and delete
      the EPIC rows when all their ACs are distributed.
- [ ] Publish a typed read API for balances consumed by reporting, and consider an
      `EntryPosted` domain event (mechanism C) so reconciliation/reporting react by
      event with no compile edge.
