# EPIC-013: Statement Parsing V2

> Status: ✅ Complete
> Vision Anchor: `decision-2-event-middle-layer`
> Owner: Backend + Frontend
> Scope: Statement extraction quality and review workflow visibility

## Goal

Upgrade statement parsing from V1 to V2 with richer transaction-level data and improved confidence scoring so review routing is more accurate and auditable.

## Objectives

1. Per-transaction currency support
2. Running balance (`balance_after`) per transaction
3. Institution auto-detection for PDF/image uploads when `institution` is omitted
4. Confidence scoring V2 with additional quality factors
5. Human review workflow visibility improvements in statement detail UI

## Deliverables

### 1) Per-Transaction Currency
- Add nullable `currency` on `BankStatementTransaction` model
- Add DB migration for `bank_statement_transactions.currency`
- Populate from AI extraction payload when present
- Expose through API schemas and frontend types
- Display in transactions table

### 2) Running Balance Per Transaction
- Add nullable `balance_after` on `BankStatementTransaction` model
- Add DB migration for `bank_statement_transactions.balance_after`
- Parse and persist from extraction payload
- Expose through API schemas and frontend types
- Display in transactions table

### 3) Institution Auto-Detection
- Make upload request `institution` optional for PDF/image flows
- Keep CSV path requiring institution
- Prompt requires model to infer institution from document header/logo

### 4) Confidence Scoring V2

Weights:
- Balance validation: 35%
- Field completeness: 25%
- Format consistency: 15%
- Transaction count: 10%
- Balance progression: 10%
- Currency consistency: 5%

New scoring helpers:
- `_score_balance_progression(transactions)`
- `_score_currency_consistency(transactions, header_currency)`

Expected routing behavior remains threshold-based (See: `common/reconciliation/readme.md#thresholds`):
- >= 85: auto-accept candidate
- 60-84: review queue
- < 60: manual handling path

### 5) Human Review Workflow Visibility
- Add `Currency` and `Balance` columns in statement detail transaction table
- Keep confidence and status columns visible for reviewer triage context

## Test Plan

- Update extraction unit tests for `_safe_decimal(None)` nullable behavior
- Add explicit required-mode test for `_safe_decimal(None, required=True)`
- Add confidence scoring V2 coverage tests:
  - balance progression scoring
  - currency consistency scoring
  - full-score with all factors
  - cap behavior without new factors

## Risks and Mitigations

- Risk: AI responses omit `currency`/`balance_after`
  - Mitigation: fields are nullable and scoring functions degrade gracefully
- Risk: scoring drift against SSOT
  - Mitigation: SSOT updates and dedicated V2 tests

## Progress Checklist

- [x] Model changes for transaction currency and running balance
- [x] Alembic migration for new columns
- [x] Extraction schema updates
- [x] Prompt updates for V2 output expectations
- [x] Extraction service updates (`_safe_decimal`, transaction mapping)
- [x] Confidence scoring V2 implementation
- [x] Frontend type and table updates
- [x] Test updates and V2 scoring coverage
- [x] SSOT documentation sync (`extraction.md`, `schema.md`)

## 🧪 Test Cases / Acceptance Criteria

> **Migrated (2026-07-03, #1421 Stage-2 cutover):** all 118 ACs moved to
> the `extraction` package roadmap in
> [`common/extraction/contract.py`](../../common/extraction/contract.py) as
> `AC-extraction.<group>.<seq>` — this EPIC's rows occupy the reserved
> groups 101–123 (group + 100), per Decision A (standard-preserving move — every AC kept its
> statement, anchored test, and priority; the package tier is LLM-LED with
> per-AC `proof_kind`). This section intentionally holds no rows; the contract
> roadmap is the single source.



> Machine-owned SSOT anchor (governance report requirement): source coverage
> tracking stays registered in
> [`source_coverage_matrix`](../ssot/source-coverage-matrix.yaml).

## 📌 Future Work (from Vision Recovery Audit)

The following item was identified during the vision.md recovery audit as a feature designed in vision but not yet tracked in this EPIC:

- **source_type Priority Logic** — Implemented for journal entries in #395. Remaining future source types such as CSV import should map into the same hierarchy instead of adding a parallel priority system.

## 🗄️ Archive Integration Notes

The useful EPIC-013 items from the removed `EPIC-ENCODING-SUMMARY.md` archive
snapshot are consolidated as current proof gaps. The removed inventory is
retained in [#548](https://github.com/wangzitian0/finance_report/issues/548):

- Institution auto-detection accepts omitted `institution` for PDF/image flows,
  but still needs provider-backed integration evidence that real document
  headers/logos produce the expected institution.
- Currency and running-balance display are delivered as V2 objectives, but UI
  tests should continue to prove the transaction table keeps those columns
  visible.
- V1 and V2 confidence scoring tests coexist; production paths should keep
  proving that V2 factors, including balance progression and currency
  consistency, are the active scoring path.

## 📏 Acceptance Criteria

> Migrated (2026-07-03, #1421): every group table that lived here duplicates
> the `extraction` package roadmap (`common/extraction/contract.py`, reserved
> groups 101–123). The contract is the single source; this section holds no
> rows.
