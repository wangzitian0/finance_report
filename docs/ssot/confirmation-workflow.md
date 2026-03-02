# Confirmation Workflow SSOT

> **SSOT Key**: `confirmation-workflow`
> **Authority**: This document defines the `pending_review` state machine used across both Stage 1 (statement import) and Stage 2 (reconciliation) of the review pipeline.
> **Cross-references**: [reconciliation.md](./reconciliation.md) §7 (Stage 1 & Stage 2 state machines), [schema.md](./schema.md), [extraction.md](./extraction.md)

---

## 1. Source of Truth

| Concern | Location |
|---------|----------|
| `Stage1Status` enum | `apps/backend/src/models/statement.py` — `BankStatement.stage1_status` |
| `Stage2Status` on match | `apps/backend/src/models/reconciliation.py` — `ReconciliationMatch.status` |
| `pending_review` usage | `apps/backend/src/routers/statements.py`, `apps/backend/src/routers/reconciliation.py` |
| Balance-chain validation | `apps/backend/src/services/statement_validation.py` |
| Consistency checks | `apps/backend/src/services/consistency_checks.py` |

---

## 2. The `pending_review` Status

`pending_review` appears on **two distinct model fields**. They are NOT the same concept.

| Field | Model | Meaning |
|-------|-------|---------|
| `BankStatement.stage1_status = PENDING_REVIEW` | Stage 1 | Parsed statement awaiting user visual verification against the original PDF |
| `ReconciliationMatch.status = PENDING_REVIEW` | Stage 2 | Reconciliation match scoring 60–84 pts, requiring human decision before journal entry creation |

Both use the string value `"pending_review"` by convention, but the state machines they live in are independent.

---

## 3. Cross-Cutting State Machine

The following diagram shows how a bank statement travels from upload through to posted journal entries.

```
                 ┌─────────────────────────────────────────────────────┐
                 │                  STAGE 1 (Record-Level)              │
                 │                                                       │
  Upload         │  BankStatement.stage1_status                          │
  ──────►  parsed│                                                       │
                 │   pending_review ──► approved ──────────────────────►│──► Stage 2 queue
                 │         │                                             │
                 │         └──► rejected ──► re-parse (loop)            │
                 │              (edit → re-validate → approved)         │
                 └─────────────────────────────────────────────────────┘

                 ┌─────────────────────────────────────────────────────┐
                 │                  STAGE 2 (Run-Level)                 │
                 │                                                       │
  Stage 2 queue  │  ReconciliationMatch.status                          │
  ──────────────►│                                                       │
                 │  score ≥ 85    ──► auto_accepted ──► journal posted  │
                 │  60 ≤ score < 85 ──► pending_review ──► accepted/   │
                 │                                         rejected      │
                 │  score < 60    ──► unmatched                         │
                 │                                                       │
                 │  Consistency checks must ALL be resolved before      │
                 │  batch_approve is permitted.                          │
                 └─────────────────────────────────────────────────────┘
```

### Stage 1 Transitions

| From | Event | To | Guard |
|------|-------|----|-------|
| `pending_review` | `approve_statement()` | `approved` | Balance delta ≤ 0.001 USD |
| `pending_review` | `reject_statement()` | `rejected` | — |
| `pending_review` | `edit_and_approve()` | `approved` | Balance delta ≤ 0.001 USD after edits |
| `rejected` | re-parse triggered | `pending_review` | — |

### Stage 2 Transitions

| From | Event | To | Guard |
|------|-------|----|-------|
| `pending_review` | `accept_match()` | `accepted` | All consistency checks resolved |
| `pending_review` | `reject_match()` | `rejected` | — |
| `auto_accepted` | system auto-accept | `accepted` | Score ≥ 85 |
| `accepted` | journal created | (terminal) | Accounting equation holds |

---

## 4. Design Constraints

### DO
- ✅ Always pass `user_id` to service methods that mutate `pending_review` state (ownership check)
- ✅ Validate balance chain (0.001 USD tolerance) before advancing Stage 1
- ✅ Resolve all consistency checks before Stage 2 batch approval
- ✅ Create journal entry only on `accepted` transition (never on `pending_review`)
- ✅ Emit an audit log entry on every state transition

### DO NOT
- ❌ Combine Stage 1 status and Stage 2 status into a single field — they are independent
- ❌ Create journal entries from `pending_review` matches
- ❌ Auto-accept Stage 1 statements without balance chain validation
- ❌ Allow `pending_review → approved` bypass when duplicate/transfer checks are unresolved
- ❌ Hardcode tolerance as `0.10` in Stage 1 — Stage 1 requires `0.001 USD`

---

## 5. Tolerance Reference

| Context | Tolerance | Source |
|---------|-----------|--------|
| Stage 1 balance chain validation | 0.001 USD | EPIC-016 Q1 user decision |
| Stage 2 reconciliation match (amount score) | 0.10 USD | AGENTS.md, reconciliation.md |
| Reconciliation statistics comparison | 1% | AGENTS.md |

---

## 6. API Contract

### Stage 1 Endpoints (in `routers/statements.py`)

| Endpoint | Input | Side Effect |
|----------|-------|-------------|
| `POST /api/statements/{id}/approve` | `statement_id`, bearer token | stage1_status → approved; queues to Stage 2 |
| `POST /api/statements/{id}/reject` | `statement_id`, `reason`, bearer token | stage1_status → rejected; triggers re-parse |
| `POST /api/statements/{id}/edit` | `statement_id`, edits, bearer token | Updates transactions, re-validates, approves if valid |
| `GET /api/statements/pending-review` | bearer token | Returns `[BankStatement]` with `stage1_status=pending_review` |

### Stage 2 Endpoints (in `routers/reconciliation.py`)

| Endpoint | Input | Side Effect |
|----------|-------|-------------|
| `POST /api/reconciliation/matches/{id}/accept` | `match_id`, bearer token | status → accepted; creates journal entry |
| `POST /api/reconciliation/matches/{id}/reject` | `match_id`, bearer token | status → rejected |
| `POST /api/reconciliation/review-queue/batch-approve` | `[match_id]`, bearer token | Accepts all; blocked if any check unresolved |
| `GET /api/reconciliation/pending` | bearer token | Returns `[ReconciliationMatch]` with `status=pending_review` |

---

## 7. Verification (The Proof)

| Test | File | What It Verifies |
|------|------|-----------------|
| `test_validate_balance_chain_within_tolerance` | `review/test_statement_validation.py` | 0.001 USD tolerance passes |
| `test_validate_balance_chain_exceeds_tolerance` | `review/test_statement_validation.py` | 0.0011 USD delta fails |
| `test_approve_statement_invalid_balance_fails` | `review/test_statement_validation.py` | Approve blocked if balance bad |
| `test_batch_approve_requires_checks_resolved` | `review/test_review_workflow.py` | Stage 2 batch blocked by open checks |
| `test_journal_entry_created_on_accept` | `review/test_review_workflow.py` | Journal entry only on accepted transition |
| `test_stage1_approve_promotes_source_type` | `extraction/test_source_type_promotion.py` | Stage 1 approve raises source_type to user_confirmed |

---

## 8. Related SSOT Documents

- [reconciliation.md §7](./reconciliation.md) — Stage 1 and Stage 2 detailed state machines with DB column definitions
- [schema.md](./schema.md) — `BankStatement`, `ReconciliationMatch`, `ConsistencyCheck` table definitions
- [extraction.md](./extraction.md) — How parsed statements enter `pending_review` (Stage 1 entry point)
- [source-type-priority.md](./source-type-priority.md) — How `source_type` is promoted through the confirmation lifecycle
