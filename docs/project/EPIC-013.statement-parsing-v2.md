# EPIC-013: Statement Parsing V2

> Status: 🟡 In Progress
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

Expected routing behavior remains threshold-based:
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

## Definition of Done

- All extraction tests pass
- Lint/type checks pass
- PR is ready for review with SSOT + project docs updated
