# `reporting` — framework financial statements (core package · draft)

> A package = DDD bounded context. Model spec: [`../meta/readme.md`](../meta/readme.md).
> Machine contract: [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).
>
> **Status: `draft` scaffold** (EPIC-026 Lane B, #1387). This `common/reporting/`
> directory is the spec + review surface; the conforming implementation currently
> lives at `apps/backend/src/services/reporting` and is migrated into
> `apps/backend/src/reporting` in follow-up one-package PRs.

## Why

Reporting is the **`L1 → report`** band of the financial data flow:
`(extraction + portfolio) → reconciliation → ledger → reporting → advisor`. It
takes **trusted L1 facts** and aggregates them into the line items of the
Balance Sheet / Income Statement / Cash Flow under a chosen accounting
framework.

It does **no extraction and no inference** — given the L1 facts, every number is
a deterministic sum. That is why this band is **`CODE-ONLY`**: its correctness is
pure code, and its proof obligation is an **`exact`** test (a fixed L1 fixture
renders a byte-exact statement), *not* an LLM `eval`. The audit's recurring
finding was that this CODE band was ungoverned — report lines were free-form
strings with no exact-aggregation proof; this package makes the band a contract.

## Ubiquitous language (planned)

- **ReportLineId** — the package's self-owned SSOT term: an *enumerated,
  framework-tagged report line* (the US ∪ HK union), each carrying `statement`
  (balance_sheet / income_statement / cash_flow), `section`, `frameworks ⊆
  {us_gaap_like, hkfrs_like}`, and per-framework order. Replaces today's
  free-form `line_mappings` strings (the #1353 work). An unknown line becomes
  unrepresentable.
- **FrameworkPolicy** — the selected framework's mapping + ordering rule that
  drives statement assembly.
- **ReportPackage** — the assembled set of statements for a period.
- **Snapshot** — an immutable rendered package retained for audit.
- **Readiness** — the deterministic blocker/ready state for a package.

## Authority tier — `CODE-ONLY`

Decided per #1387 Lane B: the whole PC wave (`portfolio → … → reporting`) is
deterministic. Tier fixes the proof kind via the tier→proof matrix
(`common/authority/authority_matrix.py`): **CODE-ONLY ⇒ `exact` / `property`**.

## Invariants this package will guarantee

- **report-lines-reconcile** — every statement line equals the exact sum of its
  contributing L1 facts; section totals equal the sum of their lines (no
  double-count, no dropped line). *(The `exact` proof #1353/#1397 owe.)*
- **framework-1:1** — a line appears under a framework iff it is tagged for that
  framework; per-framework ordering is deterministic (HK-only lines never appear
  under US, and vice versa).

These are declared in `contract.py` `invariants` (with anchored tests) as the
implementation is migrated.

## Public vs internal

The published language will be the implementation's `__init__.__all__`, mirrored
by `contract.interface`. Everything else (aggregation helpers, FX plumbing) is
internal.
