# `reconciliation` — transaction-to-journal matching (domain package)

> Package model: [`../meta/readme.md`](../meta/readme.md). Machine contract:
> [`contract.py`](./contract.py).
>
> This `common/reconciliation/` directory is the **spec + review surface**; the
> conforming implementation lives at
> [`apps/backend/src/reconciliation`](../../apps/backend/src/reconciliation)
> (`contract.implementations["be"]`).

## Why

Extracted bank transactions and manually/portfolio-posted journal entries are
two independent records of the same real-world event; `reconciliation` decides
whether they refer to the same thing, at what confidence, and routes anything
below auto-accept confidence into a review queue instead of silently trusting
either side.

## Ubiquitous language

- **`ReconciliationMatch`** — the aggregate root linking an `AtomicTransaction`
  to one or more `JournalEntry` rows. At most one *active* match exists per
  transaction; a newer match supersedes the prior one rather than mutating it.
- **Status lifecycle** —
  `PENDING_REVIEW → ACCEPTED/AUTO_ACCEPTED/REJECTED → SUPERSEDED`; posted
  entries behind an active match are immutable.
- **Match score** — a weighted composite of amount/date/description/business-
  logic/pattern sub-scores in `[0, 100]` (`score_amount`/`score_date`/
  `score_description`/`score_business_logic`/`score_pattern` composed by
  `calculate_match_score`). Scores at or above the auto-accept threshold
  auto-accept; the review band routes to `PENDING_REVIEW`.
- **`TransferLeg`** — one side of an internal transfer between the user's own
  accounts; `pair_fx_legs`/`discover_fx_conversions` pair cross-currency
  transfer legs within a rate/time tolerance.
- **Many-to-one matching** — `build_many_to_one_groups` groups several bank
  lines against one journal entry (e.g. a combined card settlement) within
  `MAX_COMBINATION_CANDIDATES` and a configured tolerance.
- **Consistency checks / anomaly detection** — `run_all_consistency_checks` /
  `detect_anomalies` are diagnostic passes over already-matched state, not
  part of the matching decision itself.

## Cross-package edges

`extraction` (the `AtomicTransaction` side), `portfolio` (positions can also
be reconciled), `ledger` (the `JournalEntry` side — links by id only, no
cross-domain FK: `AC-reconciliation.txn.1`), `pricing` (FX rate lookups for
cross-currency transfer pairing), `audit` (base value types), `platform`
(publishes `WorkflowEvent.reconciliation_match_outcome`).

## Governance

The package's ACs (`AC-reconciliation.match.*`/`.score.*`/`.stats.*`/`.txn.*`)
live in [`contract.py`](./contract.py)'s `roadmap` and are sourced **directly**
from there into the AC registry (no EPIC mirror); the larger two-stage-review
UI surface (EPIC-016) is a separate frontend concern and has not moved into
this roadmap yet. `tools/check_package_contract.py` validates the
implementation against this contract (interface == `__all__`, every test
reference resolves, no upward import edge).
