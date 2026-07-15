# EPIC-004: Reconciliation Engine & Matching

> **Status**: ✅ Complete (TDD Aligned)
> **Vision Anchor**: `decision-4-two-stage-review`
> **Phase**: 3
> **Duration**: 5 weeks
> **Dependencies**: EPIC-003

---

## 🎯 Objective

Automatically match bank transactions with journal entries, implementing intelligent reconciliation and review queue, achieving ≥95% automatic matching accuracy.

**Core Rules**:
```
≥ 85 points  → Auto-accept
60-84 points → Review queue
< 60 points  → Unmatched
```

---

## Macro Proof Ownership

- `source-ledger-report-traceability`

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🔗 **Reconciler** | Matching algorithm | Multi-dimensional weighted scoring, adjustable thresholds, supports one-to-many/many-to-one |
| 🏗️ **Architect** | System design | Independent matching engine service, supports batch processing and incremental matching |
| 📊 **Accountant** | Business logic | Account type combinations must follow accounting logic (e.g., salary = Bank + Income) |
| 💻 **Developer** | Performance requirements | 10,000 transactions matched in < 10s, supports parallel processing |
| 🧪 **Tester** | Accuracy verification | False positive rate < 0.5%, false negative rate < 2% |
| 📋 **PM** | User experience | Efficient and user-friendly review queue, batch operation support |

---

## ✅ Task Checklist

### Data Model (Backend)

- [x] `ReconciliationMatch` model
- [x] Alembic migration script
- [x] Status update trigger

### Matching Algorithm (Backend)

- [x] `reconciliation/extension/matching.py` - Reconciliation engine
  - [x] `calculate_match_score()` - Composite scoring
  - [x] `find_candidates()` - Find candidate journal entries
  - [x] `execute_matching()` - Batch matching execution
  - [x] `auto_accept()` - Auto-accept logic
- [x] Scoring dimension implementation
  - [x] `score_amount()` - Amount matching (40%)
  - [x] `score_date()` - Date proximity (25%)
  - [x] `score_description()` - Description similarity (20%)
  - [x] `score_business_logic()` - Business logic validation (10%)
  - [x] `score_pattern()` - Historical pattern (5%)
- [x] Special scenario handling
  - [x] One-to-many matching (1 bank txn → multiple journal entries)
  - [x] Many-to-one matching (multiple bank txns → 1 journal entry)
  - [x] Cross-period matching (month-end/month-start)
  - [x] Fee splitting

### Review Queue (Backend)

- [x] `reconciliation/extension/review_queue.py` - Review queue management (journal-entry creation itself lives in `extraction/extension/review_queue.py`, since `AtomicTransaction` is extraction's aggregate)
  - [x] `get_pending_items()` - Get pending items (pagination, sorting)
  - [x] `accept_match()` - Accept match
  - [x] `reject_match()` - Reject match
  - [x] `batch_accept()` - Batch accept

### Anomaly Detection (Backend)

- [x] `reconciliation/extension/anomaly.py` - Anomaly detection
  - [x] Amount anomaly (> 10x monthly average)
  - [x] Frequency anomaly (same merchant > 5 transactions/day)
  - [x] Time anomaly (large amounts during non-business hours)
  - [x] New merchant flagging

### API Endpoints (Backend)

- [x] `POST /reconciliation/runs` - Execute matching
- [x] `GET /reconciliation/matches` - Match results
- [x] `GET /reconciliation/pending` - Pending queue
- [x] `POST /reconciliation/matches/{id}/accept` - Accept
- [x] `POST /reconciliation/matches/{id}/reject` - Reject

### Frontend UI (Frontend)

- [x] `/reconciliation` - Reconciliation workbench
- [x] `/reconciliation/unmatched` - Unmatched handling
- [x] Visualization (progress bar, score distribution)

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/reconciliation/`

### AC4.1: Matching Core

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.matching-core.1` through `.4`.

### AC4.2: Group Matching (Many-to-One / One-to-Many)

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.group-matching.1` through `.3`.

### AC4.3: Review Queue & Status

> *(AC4.3's Auto-Accept Logic row removed — duplicate of the same test already homed as `AC-reconciliation.score.2`.)* The rest migrated to
> [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.review-queue.1` through `.14`.

### AC4.4: Performance & Edge Cases

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.performance.1` / `.2`.

### AC4.5: Anomaly Detection

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.anomaly-detection.1` / `.2`.

### AC4.6: Source Type Conflict & Transfer Detection

> **Fully migrated except one unverifiable row.** The extraction-owned row (was AC4.6's group-8 row) is homed in the `extraction` package roadmap as
> `AC-extraction.406.8`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py)).
> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.source-type-transfer.1` through `.7`.
>
> **Retained** — *(AC4.6's batch-approve row removed from active tracking, not migrated)*: its cited test (`test_batch_approve_blocked_by_duplicate` in a `reconciliation/test_review_workflow.py` that does not exist) could not be verified against any real test in the repo. Needs a maintainer decision: genuine coverage gap, or fully superseded by `AC16.35.2`'s `test_AC16_35_2_batch_approve_blocked_returns_409`.

### AC4.8: Archive Baseline Benchmark Ownership

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.8.1 | Archive baseline benchmark residual is explicitly owned by EPIC-004 until synthetic accuracy and performance proof exists | `test_AC4_8_1_reconciliation_benchmark_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P1 | <!-- epic-owned: horizontal -->

### AC4.9: Bank-Side Amount Matching

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.bank-side-amount.1` through `.5` (AC4.9's confidence-tier row had two test functions, each anchoring its own record, `.4` and `.5`).

### AC4.10: Reconciliation Accuracy Audit Harness

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.audit-harness.1` / `.2`.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.10.3 | CI treats reconciliation audit JSON/Markdown as a hard gate for the EPIC-004 accuracy, false-positive, false-negative, and 10,000-transaction runtime targets | `test_AC4_10_3_ci_gates_reconciliation_audit_thresholds` | `tests/tooling/test_reconciliation_audit.py` | P0 | <!-- epic-owned: horizontal -->

> **Retained**: `AC4.10.3`'s test asserts a literal substring of this EPIC file's own text (the "10,000-transaction runtime targets" phrase two lines above), so it is a doc-governance self-check, not `reconciliation` package behavior — it cannot move (same category as EPIC-012's `AC12.25.1`).

### AC4.11: Decimal-Safe Unmatched Review UI

Unmatched transaction triage may create ledger entries, so monetary values shown
in the queue and created-entry confirmation must use the same Decimal-safe
frontend formatting contract as other accounting surfaces.
See: common/ledger/readme.md#decimal-rule

| AC | Acceptance Criteria | Test(s) | File(s) | Priority |
|----|--------------------|---------|---------|----------|
(AC4.11.1 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-remainder-reconciliation.1`, #1821 Wave B)

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Auto-match accuracy ≥ 95%** | `test_performance.py` | 🔴 Critical |
| **False positive rate < 0.5%** | `test_reconciliation_scoring.py` | 🔴 Critical |
| **False negative rate < 2%** | `test_reconciliation_scoring.py` | 🔴 Critical |
| Configurable thresholds | `test_auto_accept_threshold` | Required |
| Many-to-one matching support | `test_many_to_one_grouping` | Required |
| Batch process 10,000 txns < 10s | `test_batch_1000_transactions_reasonable_time` (1,000 txns verified) | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Auto-match rate > 70% | (Real data) | ⏳ |
| Review queue avg processing < 30s/txn | (Real data) | ⏳ |
| Anomaly detection recall > 95% | `test_anomaly.py` (Planned) | ⏳ |

### 🚫 Not Acceptable Signals

- False positive rate > 2%
- Accuracy < 90%
- Performance timeout (batch > 60s)
- Severe review queue backlog

---

## 📚 SSOT References

- [schema.md](../../common/meta/schema.md) - ReconciliationMatch table
- [reconciliation.md](../../common/reconciliation/reconciliation.md) - Reconciliation rules

---

## 🔗 Deliverables

- [x] `apps/backend/src/reconciliation/orm/reconciliation.py` (moved from `src/models/` in #1675)
- [x] `apps/backend/src/reconciliation/extension/matching.py`
- [x] `apps/backend/src/reconciliation/extension/review_queue.py`
- [x] `apps/backend/src/reconciliation/extension/anomaly.py`
- [x] `apps/backend/src/routers/reconciliation.py`
- [x] `apps/frontend/app/reconciliation/page.tsx`
- [x] `apps/backend/tests/reconciliation/` - Test suite

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| **0.1 USD Threshold** | ✅ Done (AC4.6.1 removed — migrated to `AC-reconciliation.source-type-transfer.1`, #1663) | Boundary test is registered in `reconciliation/test_reconciliation_scoring.py` |
| ML-based weight auto-tuning | P2 | v2.0 |
| Multi-currency matching | P2 | After EPIC-005 |

---

## Issues & Gaps

- [x] Explicit 0.1 USD tolerance check is covered by
      `test_amount_tolerance_0_10_boundary` (was AC4.6's boundary row,
      migrated — `AC-reconciliation.source-type-transfer.1`).
- [x] Archive baseline benchmark residual is explicitly owned by EPIC-004 and
      now closed through AC4.10.3. The hard-gated audit runs
      `python tools/reconciliation_audit.py --stdout`, includes a
      100-transaction manual false-positive audit plus 10,000-transaction
      benchmark evidence, and fails CI when the `>=95%`, `<0.5%`, `<2%`, or
      `<10s` targets are missed. Current traceability review also uses
      `python tools/analyze_test_ac_coverage.py --stdout` and
      `python tools/check_ac_index.py`.

## 🗄️ Archive Integration Notes

The removed `EPIC-004.reconciliation-accuracy-report.md` archive snapshot is
folded into this EPIC as a historical baseline; the removed inventory is
retained in [#548](https://github.com/wangzitian0/finance_report/issues/548).
Scoring dimensions, threshold routing, review queue flow, and anomaly handling
were implemented, but the old archive had pending accuracy and performance
measurements. Current work should add AC or test evidence rather than
hand-maintained accuracy prose.

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../user-guide/reconciliation.md](../user-guide/reconciliation.md) — matching, review, and unmatched transaction workflow.
- [../reference/api.md](../reference/api.md) — generated reconciliation API reference.

---

## ❓ Q&A (Clarification Required)

### Q1: Are matching thresholds adjustable?
> **Decision**: Use fixed thresholds in v1.0 (Auto > 85, Review 60-84).

### Q2: Unmatched transaction handling workflow
> **Decision**: AI-driven journal entry recommendations + time-aware rules.

### Q3: Duplicate matching detection
> **Decision**: Dual-layer event model - Immutable raw layer + Mutable analysis layer.

### Q4: Batch operation safety restrictions
> **Decision**: Tiered batch operation strategy (High score batch, Low score manual).

### Q5: Historical pattern learning
> **Decision**: Embedding-driven intelligent matching (simple and efficient).

---

## 📅 Timeline

| Phase | Content | Status |
|------|------|----------|
| Week 1 | Data model + Basic matching algorithm | ✅ Done |
| Week 2 | Scoring dimensions + Special scenarios | ✅ Done |
| Week 3 | Review queue + Anomaly detection | ✅ Done |
| Week 4 | Frontend UI + Algorithm tuning + Testing | ✅ Done |
| Week 5 | Embedding integration + Time-aware rules | ✅ Done |

### AC4.7: Recovered Coverage

> **Fully migrated.** The extraction-owned row (was AC4.7's group-2 row) is homed in the `extraction` package roadmap as
> `AC-extraction.407.2`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py)).
> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.recovered-coverage.1` through `.3`.

### AC4.12: Reconciliation UUID-Typed Path Params ([#1008](https://github.com/wangzitian0/finance_report/issues/1008))

Tier 2 of #1000. The `match_id` and `txn_id` path params in
`apps/backend/src/routers/reconciliation.py` are typed as `UUID`, so a malformed
id is rejected with 422 at the boundary instead of reaching the query layer as an
arbitrary string.

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.uuid-path-params.1` / `.2`.

### AC4.13: Per-Currency Statement Balances & Reconciliation ([#1123](https://github.com/wangzitian0/finance_report/issues/1123))

First mergeable slice of the complex-money design track (root #1123). A
multi-currency statement (Wise / IBKR / Futu) cannot be represented by the scalar
`opening_balance` / `closing_balance` columns. This slice introduces an additive
per-currency balance representation (`balances: [{currency, opening, closing}]`,
persisted as the `currency_balances` JSONB column) and runs balance
reconciliation **per currency** — `open_ccy + ΣIN_ccy − ΣOUT_ccy ≈ close_ccy` for
each currency independently, never summing across currencies. The legacy scalar
check is the degenerate one-currency case. Scalar columns stay populated for
backward compatibility.

Covers **AC1** (per-currency balances + per-currency reconciliation) and **AC5**
(SSOT) of #1123. **AC2** (FX leg pairing), **AC3** (internal-transfer net-worth),
and **AC4** (FX P&L) are deferred to a follow-up EPIC — they require a linked-leg
event model and accounting-layer changes beyond this representation slice.
See: `common/reconciliation/readme.md#per-currency-balance-reconciliation`

> **Fully migrated.** The extraction-owned row (was AC4.13's group-6 row) is homed in the `extraction` package roadmap as
> `AC-extraction.413.6`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py)).
> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.per-currency-balance.1` through `.9` (AC4.13's bank-currency-balances row had two test functions, each anchoring its own record, `.8` and `.9`).

### AC4.14: FX / Cross-Currency Transfers as Linked Multi-Leg Events ([#1123](https://github.com/wangzitian0/finance_report/issues/1123), assurance [#1103](https://github.com/wangzitian0/finance_report/issues/1103))

Second mergeable slice of the complex-money design track (root #1123), building on
the per-currency representation from AC4.13. A cross-currency transfer (e.g. SGD
out of one account, USD into another, at a conversion rate) is **one economic
event spanning two legs**, not two independent income/expense transactions. This
slice adds:

- an additive `fx_conversions` linking table —
  `{user_id, from_account, amount_from, currency_from, to_account, amount_to,
  currency_to, rate, fee, fee_currency, conversion_date}` — recording a paired
  multi-leg FX event (**AC2**);
- a deterministic pairing function (`reconciliation/extension/fx_transfer.py::pair_fx_legs`) that
  matches an out-leg in currency A with an in-leg in currency B for the **same
  owner**, **opposite direction**, within a **time window**, where
  `amount_from ≈ amount_to × market_rate` within a Decimal tolerance (**AC2**);
- net-worth classification (`classify_internal_transfer`) so a matched internal
  transfer is net-zero — the transfer-in is not income and the transfer-out is not
  expense; net worth changes only by the fee (**AC3**);
- FX gain/loss attribution to revaluation over time via the existing
  `fx_revaluation` journal source type, so a same-day round-trip conversion nets
  ~zero realized P&L (minus fee/spread), the rate move being a holding-period
  revaluation rather than a conversion-event gain (**AC4**);
- live wiring of the classification into the reporting net-income / income-statement
  path (`services/reporting.py::_internal_transfer_adjustment`): a recorded
  `fx_conversions` row whose legs are anchored to journal entries excludes those
  legs from income/expense aggregation, so the net-worth/income report reflects the
  internal transfer as net-zero minus the fee, proven end to end (**AC3 E2E**);
- **ledger-based auto-discovery** (`reconciliation/extension/fx_transfer_discovery.py::discover_fx_conversions`,
  consumed by `_internal_transfer_adjustment`): candidate cross-currency transfer
  leg pairs are discovered directly from RAW asset-account journal lines — no
  pre-recorded `fx_conversions` row required — by reinterpreting each asset line as
  a directional `TransferLeg` (asset DEBIT = IN, asset CREDIT = OUT) and pairing via
  the deterministic `pair_fx_legs`. Discovery is **conservative**: only unambiguous
  1:1 matches are netted (a leg matching more than one counterpart is left alone), so
  net worth biases toward *under*-netting — reducing, not fully eliminating,
  false-positive netting without an explicit linkage signal. This is
  the **AC2 live-consumption** slice that makes a transfer recorded purely as raw
  ledger lines net-worth-correct end to end (**AC2 E2E + AC4 round-trip E2E**).

Generalized invariant: **net worth changes only via external in/out + market
moves + FX revaluation; internal transfers cancel (minus fees).**
See: `common/reconciliation/readme.md#fx-cross-currency-transfer-pairing`,
`common/reporting/readme.md#internal-transfer-net-worth-neutrality`,
common/meta/schema.md (`fx_conversions`).

> Migrated to [`common/reconciliation/contract.py`](../../common/reconciliation/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-reconciliation.fx-transfer.1` through `.14`.
