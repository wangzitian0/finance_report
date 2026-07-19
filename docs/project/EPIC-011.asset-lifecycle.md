# EPIC-011: Asset Lifecycle Management

<!-- epic-file: design-doc -->
<!-- 0 AC rows by design (2026-07-14): the last resident row's version-ordering
     half migrated to the `extraction` package roadmap as
     `AC-extraction.classification-priority.1`; this file stays the delivered
     asset-lifecycle design record. -->

**Status**: 🟡 In Progress (P0 Complete)  
**Vision Anchor**: `decision-3-record-layer`  
**Phase**: 5  
**Duration**: 18 weeks (6 weeks asset features + 12 weeks 4-layer migration)  
**Priority**: P2 (Medium Priority)  
**Dependencies**: EPIC-002 (Double-Entry Core), EPIC-005 (Reporting)

> **Usable milestone**: ⏸️ deferred (post-Usable). P0 asset tracking is done; depreciation / ESOP / valuation-history depth is owned here but **not** required for the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1) (upload a year of real data on prod).

> **Status ownership**: This EPIC owns scope and AC definitions. Current proof
> status comes from generated registries, traceability checks, tests, and CI
> artifacts.

> **Note**: This EPIC includes both asset lifecycle features (6 weeks) and foundational 4-layer architecture migration (12 weeks). The 4-layer migration affects EPIC-003, EPIC-004, EPIC-005 and should be prioritized first.

---

## 📋 Executive Summary

**Goal**: Implement comprehensive **non-cash asset tracking** with automated valuation updates, depreciation schedules, and balance sheet integration.

**Scope**:
- **Securities** (Moomoo, Ping An Securities, ESOP) → Market value tracking
- **Real Estate** (Property - Mortgage) → Appraisal-based valuation
- **Depreciable Assets** (Electronics, Equipment) → Straight-line/accelerated depreciation
- **Intangible Assets** (ESOP vesting schedule)

**Out of Scope**:
- Trading execution (buy/sell orders)
- Portfolio optimization or robo-advisory
- Crypto wallet integration
- Collectibles (art, wine, etc.)

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `annualized-income-long-term`

---

## 🎯 Business Value

### Current Pain Points
1. **Securities hidden in bank balances** → No visibility into stock/bond holdings
2. **Property value stale** → Manual updates, no integration with appraisals
3. **Depreciation ignored** → Balance sheet overstates asset value
4. **ESOP vesting unclear** → No tracking of unvested options

### Success Metrics
- **Accuracy**: ≤ 1% variance between reported and real asset values
- **Automation**: ≥ 90% of securities valuations auto-updated
- **Coverage**: All asset classes represented in balance sheet
- **Timeliness**: Real estate valuations updated quarterly, securities daily

---

## Source Of Truth And Scope Management

This EPIC owns the asset-lifecycle scope and AC definitions. Durable design
facts are managed by the SSOT/code surfaces below instead of being copied here:

| Fact | Owner |
|---|---|
| Four-layer raw/atomic/logic/report architecture | [assets.md](../../common/portfolio/assets.md), [schema.md](../../common/meta/schema.md), models, migrations |
| Upload, extraction, and atomic record flow | [common/extraction/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md), `apps/backend/src/extraction/` |
| Reconciliation and reporting integration | [reconciliation.md](../../common/reconciliation/reconciliation.md), [reporting.md](../../common/reporting/reporting.md) |
| Market data sync, freshness, and provider fallback | [market_data.md](../../common/pricing/market_data.md), `apps/backend/src/services/market_data/` (pre-migration; consolidates into the `pricing` package, #1610) |
| AC-to-test proof and current counts | `python tools/analyze_test_ac_coverage.py --no-write --stdout`, CI traceability artifact |

Historical migration options, copied table schemas, and implementation-phase
plans were removed from this EPIC because they duplicated SSOT/model ownership.
The retained information is recoverable from the linked SSOT files, executable
code, tests, issues, and git history.

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using AC11.x.y numbering.
> **Coverage**: See `apps/backend/tests/assets/`

### AC11.1: Asset Service - Reconciliation Logic

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.reconcile.1-12` (`AC11.1.<s>` becomes
> `AC-portfolio.reconcile.<s>`; migration closeout continuation, #1663 /
> #1717).

### AC11.2: Asset Router - List Operations

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.router.1-3` (migration closeout continuation, #1663 /
> #1717).

### AC11.3: Asset Router - Single Position Operations

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.router.4-6` (migration closeout continuation, #1663 /
> #1717).

### AC11.4: Asset Router - Reconciliation Endpoint

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.router.7-8` (migration closeout continuation, #1663 /
> #1717).

### AC11.5: Asset Router - Authentication

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.router.9-11` (migration closeout continuation, #1663 /
> #1717).

### AC11.6: Asset Router - Depreciation Endpoint

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.depreciation.1-4` (migration closeout continuation, #1663 /
> #1717).

### AC11.7: Security - User Isolation

> This group's row removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.router.12` (migration closeout continuation, #1663 /
> #1717).

### AC11.10: Daily Market Data Sync

> This group's rows removed — migrated to the `pricing` package roadmap as
> `AC-pricing.marketdata.1-11` (migration closeout continuation, #1663 /
> #1710).

### AC11.13: 4-Layer Migration — Stage 1 Dual-Write Activation — migrated to the `extraction` package

Stage 1 of the 4-layer cutover turns dual-write ON by default: every parsed
statement populates Layer 1/2 (`UploadedDocument` + `AtomicTransaction`)
alongside legacy Layer 0, with an env opt-out preserved for rollback.

> **The ACs of this group are no longer defined here.** The rows (were
> AC11.13.* rows .1–.1) migrated into the `extraction` package and are owned
> by, and sourced directly from,
> [`common/extraction/contract.py`](../../common/extraction/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-extraction.<group>.<seq>` id scheme
> (`AC11.13.<s>` becomes
> `AC-extraction.213.<s>`). `common/meta/extension/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-extraction.213.<s>` ids (homed in the package roadmap):
> `AC-extraction.213.1`

### AC11.14: 4-Layer Migration — Stage 2a Layer 0→2 Backfill (RETIRED in Stage 3)

> **Retired.** The Stage-2a backfill (`tools/backfill_layer2.py`) and its tests
> were transitional scaffolding to populate Layer 1/2 from legacy Layer-0
> statements before the read cutover. Stage 3 removes the `bank_statements`
> tables entirely and the ingestion pipeline writes Layer 1/2 + the
> `StatementSummary` conform directly, so there is no Layer-0 source to backfill
> from. The backfill acceptance criteria are obsolete and have been removed.

### AC11.15: 4-Layer Migration — StatementSummary Conform (custody account) — migrated to the `extraction` package

The durable `StatementSummary` conform binds an uploaded statement document to its
custody account (DIM) and carries the confirmed statement envelope (period,
balances, review state). It is the DWD-native home for the account context
reconciliation transfer detection needs. As of Stage 3 the ingestion pipeline
writes the conform directly (the legacy `BankStatement`→`StatementSummary` sync
was removed with the `bank_statements` table).

> **The ACs of this group are no longer defined here.** The rows (were
> AC11.15.* rows .3–.9) migrated into the `extraction` package and are owned
> by, and sourced directly from,
> [`common/extraction/contract.py`](../../common/extraction/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-extraction.<group>.<seq>` id scheme
> (`AC11.15.<s>` becomes
> `AC-extraction.215.<s>`). `common/meta/extension/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-extraction.215.<s>` ids (homed in the package roadmap):
> `AC-extraction.215.3` · `AC-extraction.215.4` · `AC-extraction.215.5` · `AC-extraction.215.6` · `AC-extraction.215.7` · `AC-extraction.215.8` · `AC-extraction.215.9`

### AC11.16: 4-Layer Migration — Balance-aware Layer 2 dedup

The Layer 2 `dedup_hash` includes the statement running balance (`balance_after`)
so two real, otherwise-identical transactions (same date/amount/direction/
description, no reference) stay distinct — their running balances differ — while
genuine duplicate extractions (same running balance) still collapse. This keeps
many-to-one reconciliation correct on the Layer-2 read path.

> **Fully migrated.** The extraction-owned rows (were AC11.16.* row .1) are
> homed in the `extraction` package roadmap as `AC-extraction.216.1`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py)).
> The remaining row (was .2) removed — migrated to the `reconciliation`
> package roadmap as `AC-reconciliation.layer2-dedup.1` (migration closeout
> continuation, #1663 / #1711).

### AC11.17: 4-Layer Migration — PR-B DWD read cutover

PR-B activates `ENABLE_4_LAYER_READ` by default: reconciliation reads Layer 2
(`atomic_transactions`) and transfer detection resolves the custody account from
the `StatementSummary` conform (DWD) instead of `bank_statements.account_id`
(ODS). The legacy Layer-0 read path remains available via the flag until Stage 3.

> This group's rows removed — migrated to the `reconciliation` package
> roadmap as `AC-reconciliation.dwd-cutover.1-2` (migration closeout
> continuation, #1663 / #1711).

### AC11.18: 4-Layer Migration — Financial Fact Schema Invariants

> This group's rows removed — migrated to the `audit` package roadmap as
> `AC-audit.42.1-6` (migration closeout continuation, #1663 / #1709).

### AC11.19: Append-Only Manual Valuation Facts (Axiom A)

Manual valuation snapshots are user-supplied source facts. Per vision Axiom A a
recorded fact is never edited in place: correcting a valuation for an existing
`(component_type, source, as_of_date)` appends a new version and supersedes the
prior one, so the correction history stays retrievable and one version maps to
exactly one value. Uniqueness applies to the current head only (a partial unique
index over `superseded_by_id IS NULL`); read paths and net-worth aggregation use
the current head so a correction never double-counts. (In-place value editing via
the PATCH endpoint is the documented next slice; see #918.)

> This group's rows removed — migrated to the `pricing` package roadmap as
> `AC-pricing.manualvaluation.1-2` (migration closeout continuation, #1663 /
> #1710).

### AC11.20: Retirement and Benefit Assets

Retirement accounts, personal social-security balances, CPF-style balances,
long-term benefit accounts, and insurance cash value are assets. They are not
insurance coverage or future benefits; only the attributable/account value is
recorded. By default they are restricted assets, included in full net-worth
views and grouped separately from liquid cash, public equity, property, and
restricted compensation.

> *(AC11.20.1 removed and AC11.20.2 removed — migrated to the `reporting`
> package roadmap as `AC-reporting.net-worth-components.1-2`; the frontend
> row below stays here. Migration closeout continuation, #1663 / #1716.)*

(AC11.20.3 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-assets2.1`, #1821 Wave B)

### AC11.21-11.24: Valuation Taxonomy Stack (RETIRED — reinvented existing accounting primitives)

> **Retired.** Issues #1221-1224 built a parallel valuation-classification stack
> (a `valuation_taxonomy` catalog, `atomic_valuation_facts` /
> `valuation_classifications` storage, a legacy adapter, and an LLM output
> contract). It reinvented primitives the system already has: the chart of
> accounts (`AccountType` / `Account`), the double-entry ledger
> (`JournalEntry` / `JournalLine` / `Direction`), transaction classification
> (`ClassificationRule` / `TransactionClassification`, with confidence +
> append-only versioning), and the audit-evidence graph (`EvidenceNode` /
> `EvidenceEdge`). The stack was an orphaned island — nothing ever produced or
> consumed its tables. The code, tests, storage tables, and SSOT vocabulary have
> been removed; the corrected direction folds manual / non-bank valuations into
> the existing Account + Journal + Classification + Evidence pipeline, with an
> LLM classifier mapping a raw record onto chart-of-accounts postings. The
> acceptance criteria above are obsolete and have been removed; replacement ACs
> will land with the ledger-pipeline extension. See issues #1221, #1222, #1223,
> #1224, #1225, #1226, #1279.


## Implementation Pattern Ownership

Do not copy reusable code patterns, router examples, migration guardrails, or
test inventories into this EPIC. Those facts are owned by the implementation and
its guardrails:

| Pattern | Owner |
|---|---|
| Service/router/session conventions | Existing backend modules and `apps/backend/README.md` |
| Monetary precision and enum naming | [red-lines.md](../agents/red-lines.md), schema guardrail tests |
| Frontend API access and component conventions | [frontend-patterns.md](../../apps/frontend/frontend-patterns.md), `apps/frontend/src/lib/api.ts` |
| Test ownership and execution stage | [test-execution-matrix.yaml](../../common/testing/data/test-execution-matrix.yaml), AC traceability artifact |

End-to-end user workflows are represented as ACs plus executable tests. Keep new
workflow detail in tests, critical proof matrix rows, or SSOT rationale instead
of adding another hand-maintained checklist here.

## ✅ Acceptance Criteria

This section retains only EPIC-owned acceptance criteria that are not already
represented in the detailed AC tables above or below. Current proof status is
generated from the registry and tests, not from checkboxes in this file.

*(AC11.9.1 removed and AC11.9.2 removed and AC11.9.3 removed and AC11.9.5
removed, canonical: migrated to the `pricing` package roadmap as
`AC-pricing.manualvaluation.5-8`, #1821 Wave A)*
(AC11.9.4 removed and AC11.9.6 removed and AC11.9.7 removed and AC11.9.8 removed and AC11.9.9 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-assets2.2` through `.6`, #1821 Wave B)
*(AC11.9.10 removed, canonical: migrated to the `pricing` package roadmap as
`AC-pricing.manualvaluation.9`, #1821 Wave A)*

Broader future scope such as depreciation schedules, ESOP grant management,
automated journal posting, charting, and tax-lot functionality remains product
scope only until it receives explicit ACs and executable proof. Technical risks,
provider choices, and accounting decisions are documented in the SSOT files
listed below.

## 📚 Related Documentation

- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) — Double-entry rules
- [schema.md](../../common/meta/schema.md) — Database models
- [reporting.md](../../common/reporting/reporting.md) — Financial reports
- [market_data.md](../../common/pricing/market_data.md) — Market data sources
- [assets.md](../../common/portfolio/assets.md) — Asset lifecycle rationale and proof references

---

## Archive And Future-Work Ownership

Removed archive snapshots are retained through [issue #548](https://github.com/wangzitian0/finance_report/issues/548)
and git history. Current remaining scope is not tracked by prose-only future-work
lists; it must be represented by one of these owners:

| Scope | Owner |
|---|---|
| Asset lifecycle rationale and data-model links | [assets.md](../../common/portfolio/assets.md), [schema.md](../../common/meta/schema.md) |
| Annualized income / restricted holdings UI gap | AC11.8 below |
| Personal report package annualized-income schedule | AC11.11 below and EPIC-005 package contract |
| Layer 3 classification service | AC11.12 below and extraction service tests |

## 🆕 UI Gap Audit (April 2026) — Annualized Income & ESOP Surfacing

**Origin**: UI gap audit against [Project Vision](../target.md) (annualized salary, ESOP/RSU vesting, restricted-asset visibility). Backend asset lifecycle is complete but the dashboard does not surface annualized income or ESOP/restricted holdings; user has no view of "earnings power vs. liquid wealth".

### Acceptance Criteria

*(AC11.8.1 removed and AC11.8.7 removed, canonical: migrated to the
`reporting` package roadmap as `AC-reporting.annualized-dashboard.1` and
`.3`, #1821 Wave A)*
(AC11.8.2 removed and AC11.8.4 removed and AC11.8.5 removed and AC11.8.6 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-assets2.7` through `.10`, #1821 Wave B)
*(AC11.8.3 removed, canonical: migrated to the `reporting` package roadmap
as `AC-reporting.annualized-dashboard.2`, #1821 Wave A)*

**Priority**: P1 (high) — closes the largest "vision parity" gap after net worth time series.
**Estimated effort**: 4-6 days backend (income aggregation + restricted-flag schema check) + 3-4 days frontend.

### Personal Report Package Dependency

[#566](https://github.com/wangzitian0/finance_report/issues/566) owns the
annualized income and long-term compensation proof path needed by the personal
financial-report package tracked in
[#563](https://github.com/wangzitian0/finance_report/issues/563). This EPIC
must supply report-ready schedules for salary, dividends, ESOP/RSU, restricted
holdings, vesting/unlock dates, valuation basis, and liquid-versus-restricted
net worth treatment.

For #521 closure, this EPIC sequence is:

1. Consume the package section contract from `#570`.
2. Finalize annualized income and long-term compensation schedule data
   (`#566`, now embedded in the one `PersonalReportPackageDocument`).
3. Prove the annualized income and long-term compensation schedule in the
   implemented `#565` post-merge package proof.
4. Land supporting explanation assets for the broader package:
   - report notes (`#571`)
   - traceability appendix (`#572`)
5. Provide deterministic fixture inputs for the remaining package completeness
   proof (`#573`).

`#570`, `#571`, and `#572` are shared package prerequisites with EPIC-005;
`#566` supplies the report-ready schedule contract and the `#565` package E2E
now proves `annualized-income-long-term` in
the derived critical-proof matrix (source `common/testing/data/critical-proof-outcomes.yaml`). `#573` remains responsible for the
representative fixture expansion needed before the overall
`personal-financial-report-package` macro can move from `partial` to `covered`.

### Acceptance Criteria — Report Package Annualized Income Schedule

> (AC11.11.1 removed and AC11.11.2 removed and AC11.11.4 removed and AC11.11.3 removed and AC5.11.3 removed, canonical: AC11.11.1/.2/.4 migrated to the `reporting` package roadmap as `AC-reporting.package-annualized.3`, `.4`, `.5` (#1821 Wave A); AC11.11.3 and AC5.11.3 removed with no new roadmap entry — duplicates of the already-migrated `AC-reporting.package-annualized.2`, which cites the identical test and whose docstring already names both ids.)

### Acceptance Criteria — Layer 3 Classification Service

> **Fully migrated (2026-07-14).** The idempotency row (was AC11.12.* row .1)
> is homed in the `extraction` package roadmap as `AC-extraction.212.1`. Row
> .2 ("Classification priority is deterministic across rule type and
> descending rule version") had two halves proven by two different tests: the
> keyword>regex half was already proven by the already-migrated
> `AC-extraction.1801.2` (identical test, docstring already names both ids);
> the newest-rule-version half had no package home and is now
> `AC-extraction.classification-priority.1`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py)),
> `proof_kind="property"` — valid under the package's LLM-LED tier, so the
> earlier "downgrades proof authority" concern did not apply once re-checked.
