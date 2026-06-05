# Confirmation Workflow SSOT

> **SSOT Key**: `confirmation-workflow`
> **Authority**: This document defines the `pending_review` state machine used across both Stage 1 (statement import) and Stage 2 (reconciliation) of the review pipeline.
> **Cross-references**: [reconciliation.md](./reconciliation.md) §7 (Stage 1 & Stage 2 state machines), [schema.md](./schema.md), [extraction.md](./extraction.md)

---

## 1. Source of Truth

| Concern | Location |
|---------|----------|
| `Stage1Status` enum | `apps/backend/src/models/statement.py` — `BankStatement.stage1_status` (nullable; `None` at upload, set during review workflow) |
| `Stage2Status` on match | `apps/backend/src/models/reconciliation.py` — `ReconciliationMatch.status` |
| `pending_review` usage | `apps/backend/src/routers/statements.py`, `apps/backend/src/routers/reconciliation.py` |
| Balance-chain validation | `apps/backend/src/services/statement_validation.py` |
| Consistency checks | `apps/backend/src/services/consistency_checks.py` |

---

## 2. The `pending_review` Status

`pending_review` appears on **two distinct model fields**. They are NOT the same concept.

| Field | Model | Meaning |
|-------|-------|---------|
| `BankStatement.stage1_status = PENDING_REVIEW` | Stage 1 | Parsed statement awaiting user visual verification against the original PDF (**nullable** — `None` after upload; set to `PENDING_REVIEW` when review is triggered) |
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
                 │   score ≥ 85 + guards ──► approved ─────────────────►│──► Stage 2 queue
                 │         │                                             │
                 │   pending_review ──► approved ──────────────────────►│
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
| `parsed` | system auto-accept | `approved` | Score ≥ 85, balance delta ≤ 0.001 USD, confirmed active asset account in statement currency, non-overlapping source period |
| `approved` | auto-post guard failure | `pending_review` | Guard failure during high-confidence auto-post; preserve parsed statement and transactions |
| `pending_review` | `approve_statement()` | `approved` | Opening and closing balance-chain checks both pass within 0.001 USD; duplicate and transfer-pair candidates are resolved |
| `pending_review` | `reject_statement()` | `rejected` | — |
| `pending_review` | `edit_and_approve()` | `approved` | Opening and closing balance-chain checks both pass within 0.001 USD after edits; duplicate and transfer-pair candidates are resolved |
| `rejected` | re-parse triggered | `pending_review` | — |

### Stage 2 Transitions

| From | Event | To | Guard |
|------|-------|----|-------|
| `pending_review` | `accept_match()` | `accepted` | All consistency checks resolved in the active Stage 2 scope |
| `pending_review` | `reject_match()` | `rejected` | — |
| `auto_accepted` | system auto-accept | `accepted` | Score ≥ 85 |
| `accepted` | journal created | (terminal) | Accounting equation holds |

---

## 4. Design Constraints

### DO
- ✅ Always pass `user_id` to service methods that mutate `pending_review` state (ownership check)
- ✅ Validate both opening and closing balance-chain checks (0.001 USD tolerance) before advancing Stage 1
- ✅ Label and confirm Stage 1 edit actions as approve-and-post operations because `/review/edit` persists edits, approves the statement, and posts journal entries when valid
- ✅ Block Stage 1 approve and edit-approve when unresolved duplicate or transfer-pair candidates remain on the statement
- ✅ Require confirmed account mapping and source-period uniqueness before Stage 1 auto-posting
- ✅ Resolve all consistency checks in the active Stage 2 scope before batch approval
- ✅ Create journal entry only on `accepted` transition (never on `pending_review`)
- ✅ Emit an audit log entry on every state transition

### DO NOT
- ❌ Combine Stage 1 status and Stage 2 status into a single field — they are independent
- ❌ Create journal entries from `pending_review` matches
- ❌ Auto-accept Stage 1 statements without opening and closing balance-chain validation
- ❌ Present `/review/edit` as a save-only action; it is an approval operation with posting side effects
- ❌ Allow `pending_review → approved` bypass when duplicate/transfer checks are unresolved
- ❌ Hardcode tolerance as `0.10` in Stage 1 — Stage 1 requires `0.001 USD`

---

## 5. Tolerance Reference

| Context | Tolerance | Source |
|---------|-----------|--------|
| Stage 1 balance chain validation | 0.001 USD | EPIC-016 Q1 user decision |
| Stage 2 reconciliation match (amount score) | 0.10 USD | AGENTS.md, reconciliation.md |
| Reconciliation statistics comparison | 1% | AGENTS.md |

These tolerances are intentionally separate policies. Stage 1 document approval
uses the strict 0.001 USD balance-chain threshold for both the opening continuity
check and the closing transaction-sum check; extraction confidence and Stage 2
matching may use wider scoring tolerances, but they cannot approve a Stage 1
statement with either balance-chain check outside the 0.001 USD tolerance.

---

## 6. API Contract

### Stage 1 Endpoints (in `routers/statements.py`)

| Endpoint | Input | Side Effect |
|----------|-------|-------------|
| `POST /api/statements/{id}/review/approve` | `statement_id`, bearer token | stage1_status → approved; opening and closing balance-chain validation enforced (≤ 0.001 USD); unresolved duplicate/transfer-pair candidates rejected; queues to Stage 2 |
| `POST /api/statements/{id}/review/reject` | `statement_id`, `reason`, bearer token | stage1_status → rejected; triggers re-parse |
| `POST /api/statements/{id}/review/edit` | `statement_id`, edits, bearer token | Updates transactions, re-validates opening and closing balance-chain checks, rejects unresolved duplicate/transfer-pair candidates, approves if valid, and posts journal entries |
| `GET /api/statements/pending-review` | bearer token | Returns `[BankStatement]` where `status=PARSED` and either `stage1_status=PENDING_REVIEW` or `stage1_status` is null for legacy parsed rows |
### Stage 2 Endpoints (reconciliation + statements routers)

| Endpoint | Input | Side Effect |
|----------|-------|-------------|
| `POST /api/reconciliation/matches/{id}/accept` | `match_id`, bearer token | status → accepted; creates journal entry |
| `POST /api/reconciliation/matches/{id}/reject` | `match_id`, bearer token | status → rejected |
| `POST /api/reconciliation/batch-accept` | `[match_id]`, bearer token | Accepts all provided matches; blocked if any related consistency check is unresolved; creates journal entries |
| `GET /api/statements/stage2/queue` | optional `run_id`, bearer token | Returns pending matches and the full unresolved consistency-check set for the user or requested run scope |
| `POST /api/statements/batch-approve-matches` | `[match_id]`, optional `run_id`, bearer token | Stage 2 batch acceptance scoped to the requested run when provided; routes each pending match through `accept_match()`, creates missing journal entries or reconciles referenced entries, and returns accepted/created/reconciled counts |
| `GET /api/reconciliation/pending` | bearer token | Returns `[ReconciliationMatch]` with `status=pending_review` |

---

## 7. Verification (The Proof)

| Test | File | What It Verifies |
|------|------|-----------------|
| `test_validate_balance_chain_within_tolerance` | `review/test_statement_validation.py` | 0.001 USD tolerance passes |
| `test_validate_balance_chain_exceeds_tolerance` | `review/test_statement_validation.py` | 0.0011 USD delta fails |
| `test_ac16_22_7_tolerance_policy_constants_are_intentional` | `review/test_tolerance_policy.py` | Stage 1 and extraction/reconciliation tolerances remain intentionally separate |
| `test_approve_statement_invalid_balance_fails` | `review/test_statement_validation.py` | Approve blocked if balance bad |
| `test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts` | `api/test_statements_router.py` | Stage 1 approve blocked if duplicate/transfer candidates remain |
| `test_AC16_32_3_stage2_queue_returns_all_pending_checks` | `api/test_statements_router.py` | Stage 2 queue returns the complete unresolved blocker set |
| `test_AC19_11_1_stage2_run_queue_filters_by_run_id` | `api/test_statements_router.py` | Run-scoped Stage 2 queue and approval cannot affect another run |
| `test_batch_approve_requires_checks_resolved` | `review/test_review_workflow.py` | Stage 2 batch blocked by open checks (⏳ Planned) |
| `test_journal_entry_created_on_accept` | `review/test_review_workflow.py` | Journal entry only on accepted transition (⏳ Planned) |
| `test_batch_approve_matches_reconciles_referenced_entry` | `api/test_statements_router.py` | Stage 2 batch approval reconciles referenced journal entries |
| `test_batch_approve_matches_creates_missing_entry_once` | `api/test_statements_router.py` | Stage 2 batch approval creates missing journal entries idempotently |
| `test_stage1_approve_promotes_source_type` | `extraction/test_source_type_promotion.py` | Stage 1 approve raises source_type to user_confirmed (✅ Implemented) |

---

## 8. Related SSOT Documents

- [reconciliation.md §7](./reconciliation.md) — Stage 1 and Stage 2 detailed state machines with DB column definitions
- [schema.md](./schema.md) — `BankStatement`, `ReconciliationMatch`, `ConsistencyCheck` table definitions
- [extraction.md](./extraction.md) — How parsed statements enter `pending_review` (Stage 1 entry point)
- [source-type-priority.md](./source-type-priority.md) — How `source_type` is promoted through the confirmation lifecycle
