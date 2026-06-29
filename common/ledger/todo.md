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
- [x] **`processing_account` cutover (slice 3b of #1420)**: the in-transit Processing
      account folded into the package — the pure `ProcessingAccount` identity +
      `TransferPair` + `detect_transfer_pattern` scoring policy in `base/processing.py`,
      the impure verbs (`get_or_create_processing_account` / `find_transfer_pairs` /
      `create_transfer_*` / `get_processing_balance` / `get_unpaired_transfers` /
      `list_processing_transfer_legs`) in `extension/processing.py`. Consumers
      (`routers/accounts`, `services/reconciliation`, `services/reconciliation_audit`)
      repointed to the published `src.ledger` interface; reconciliation references
      Processing cross-domain by id (Decision B). `src/services/processing_account.py`
      deleted (zero residue, no shim); tests moved to `apps/backend/tests/ledger/`.

- [x] **slice 3c-i — EPIC-015 AC migration**: the 23 processing-account backend ACs
      (was `AC15.1.1`…`AC15.6.7`) homed in the contract `roadmap` as
      `AC-ledger.71.*`…`AC-ledger.76.*`; the EPIC-015 backend tables deleted and
      replaced with a disclaimer listing the new ids; the `AC15.<1-6>.*` test
      docstrings repointed to the new ids. The id form is the numeric
      `AC-ledger.<n>.<n>` grammar the live traceability regex
      (`common/ssot/ac_traceability_refs.py`) accepts — **not** the aspirational
      `AC-ledger.<entity>.<seq>` form some docs advertise (that form fails the regex
      and is invisible to `check_registry_to_tests`). Group blocks are reserved
      ledger-locally: **1–70 = EPIC-002/012 double-entry** (slices 3c-ii/iii),
      **71–76 = EPIC-015 processing**. The EPIC-015 frontend ACs (`AC15.7.*`) stay
      in EPIC-015 (ledger is backend-only).

## Next
- [ ] **slice 3c-ii/iii — EPIC-002 / EPIC-012 (AC12.34) AC migration**: move the
      double-entry ACs into the contract `roadmap` under the reserved **groups 1–70**
      (`AC-ledger.<n>.<n>`, the numeric grammar — not `AC-ledger.<entity>.<seq>`),
      removed from the EPIC tables (atomic), deleting the EPIC rows when all their
      ACs are distributed.
- [ ] Publish a typed read API for balances consumed by reporting, and consider an
      `EntryPosted` domain event (mechanism C) so reconciliation/reporting react by
      event with no compile edge.
