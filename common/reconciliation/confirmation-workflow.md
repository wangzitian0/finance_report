# Confirmation Workflow — Match-Confirm (Stage 2)

> Match-confirm (Stage 2) half of `confirmation-workflow`. Parse-confirm (Stage 1), cross-cutting diagram, tolerances (`0.001 USD` Stage 1 / `85`/`60` Stage 2), and design constraints are canonical in [`common/extraction/confirmation-workflow.md`](../extraction/confirmation-workflow.md#state-machine). Threshold details: `common/reconciliation/readme.md#thresholds`.

## <a id="state-machine"></a>Cross-Cutting State Machine

See [`common/extraction/confirmation-workflow.md §3`](../extraction/confirmation-workflow.md#3-cross-cutting-state-machine) and [Stage 1 Transitions](../extraction/confirmation-workflow.md#stage-1-transitions).

### Stage 2 Transitions

| From | Event | To | Guard |
|---|---|---|---|
| `pending_review` | `accept_match()` / `POST /api/reconciliation/matches` | `accepted` | No unresolved consistency checks in active Stage 2 scope; referenced entries reconcile idempotently |
| `pending_review` | `reject_match()` | `rejected` | — |
| `auto_accepted` | system auto-accept | `accepted` | Score `>= 85` |
| `accepted` | journal reconciled | (terminal) | Linked posted journal entry transitions to `reconciled` |

`accept_match()` and `POST /api/reconciliation/matches` never invent missing journal entries, categories, or accounts; they transition `pending_review -> accepted` and reconcile pre-existing referenced journal entries idempotently (`ReconciliationMatchBatchResponse` returns `approved_count`, `rejected_count`, and `journal_entries_reconciled`). See [`§4`](../extraction/confirmation-workflow.md#4-design-constraints) and [`§5`](../extraction/confirmation-workflow.md#5-tolerance-reference).

## 6. API Contract — Stage 2 Endpoints (reconciliation + statements routers)

| Endpoint | Input | Side Effect |
|---|---|---|
| `POST /api/reconciliation/matches/{id}/accept` | `match_id`, bearer token | `status -> accepted`; reconciles linked journal entry |
| `POST /api/reconciliation/matches/{id}/reject` | `match_id`, bearer token | `status -> rejected` |
| `POST /api/reconciliation/matches` | `action`, `match_ids`, optional `run_id`/`min_score`, bearer token | Batch-accepts or rejects matches in scope, reconciles linked journal entries, returns `approved_count`, `rejected_count`, and `journal_entries_reconciled` |
| `GET /api/statements/stage2/queue` | optional `run_id`, bearer token | Returns pending matches and unresolved consistency checks in scope |
| `GET /api/reconciliation/pending` | bearer token | Returns `pending_review` matches |

Stage 1 endpoints: [`common/extraction/confirmation-workflow.md`](../extraction/confirmation-workflow.md#6-api-contract--stage-1-endpoints-in-routersstatementspy).

## 7. Verification (The Proof) — Stage 2

| Test | File | Verifies |
|---|---|---|
| `test_AC16_32_3_stage2_queue_returns_all_pending_checks` | `api/test_review_router.py` | Stage 2 queue returns complete unresolved blocker set |
| `test_AC19_11_1_stage2_run_queue_filters_by_run_id` | `api/test_review_router.py` | Run-scoped Stage 2 queue and approval stay isolated by `run_id` |
| `test_batch_approve_matches_reconciles_referenced_entry` | `api/test_review_router.py` | Batch approval transitions linked entries to `reconciled` without creating entries |
| `test_batch_approve_matches_accepts_match_without_creating_entry` | `api/test_review_router.py` | Match without linked entry accepts cleanly with `journal_entries_reconciled == 0` |
| `test_batch_approve_matches_blocked_by_unresolved_check` | `api/test_review_router.py` | Unresolved check blocks batch approval with 400 |

Stage 1 proof: [`common/extraction/confirmation-workflow.md`](../extraction/confirmation-workflow.md#7-verification-the-proof--stage-1).
