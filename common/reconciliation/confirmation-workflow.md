# Confirmation Workflow — Match-Confirm (Stage 2)

> **SSOT Key**: `confirmation-workflow` (match-confirm half)
> **Authority**: This document defines the `pending_review` state machine used
> across both Stage 1 (statement import, owned by
> [`common/extraction/confirmation-workflow.md`](../extraction/confirmation-workflow.md#state-machine))
> and Stage 2 (reconciliation, owned here). The two halves split at #1822
> (SSOT dissolution); the extraction half is the canonical home for the
> shared cross-cutting framing (the full state-machine diagram, tolerance
> reference, confidence/promotion model, and design constraints) — this half
> holds Stage-2-specific transitions, endpoints, and tests.
> **Cross-references**: [reconciliation.md](./reconciliation.md) §7 (Stage 1 & Stage 2 state machines), [common/extraction/confirmation-workflow.md](../extraction/confirmation-workflow.md) (parse-confirm half, Stage 1)

---

## <a id="state-machine"></a>Cross-Cutting State Machine

The full upload-to-journal state-machine diagram (both Stage 1 and Stage 2) and
the Stage 1 Transitions table are canonical in the extraction half:
[common/extraction/confirmation-workflow.md §3](../extraction/confirmation-workflow.md#3-cross-cutting-state-machine).

### Stage 2 Transitions

| From | Event | To | Guard |
|------|-------|----|-------|
| `pending_review` | `accept_match()` | `accepted` | All consistency checks resolved in the active Stage 2 scope |
| `pending_review` | `reject_match()` | `rejected` | — |
| `auto_accepted` | system auto-accept | `accepted` | Score ≥ 85 |
| `accepted` | journal created | (terminal) | Accounting equation holds |

Stage 1 Transitions live in the extraction half:
[common/extraction/confirmation-workflow.md §Stage 1 Transitions](../extraction/confirmation-workflow.md#stage-1-transitions).

Design constraints (DO / DO NOT), the shared tolerance reference, the
confidence-tier rollup, the promotion gate, and the correction feedback loop
are also canonical in the extraction half —
[common/extraction/confirmation-workflow.md §4](../extraction/confirmation-workflow.md#4-design-constraints)
and
[§5](../extraction/confirmation-workflow.md#5-tolerance-reference).

---

## 6. API Contract — Stage 2 Endpoints (reconciliation + statements routers)

| Endpoint | Input | Side Effect |
|----------|-------|-------------|
| `POST /api/reconciliation/matches/{id}/accept` | `match_id`, bearer token | status → accepted; creates journal entry |
| `POST /api/reconciliation/matches/{id}/reject` | `match_id`, bearer token | status → rejected |
| `POST /api/reconciliation/batch-accept` | `[match_id]`, bearer token | Accepts all provided matches; blocked if any related consistency check is unresolved; creates journal entries |
| `GET /api/statements/stage2/queue` | optional `run_id`, bearer token | Returns pending matches and the full unresolved consistency-check set for the user or requested run scope |
| `POST /api/statements/batch-approve-matches` | `[match_id]`, optional `run_id`, bearer token | Stage 2 batch acceptance scoped to the requested run when provided; routes each pending match through `accept_match()`, creates missing journal entries or reconciles referenced entries, and returns accepted/created/reconciled counts |
| `GET /api/reconciliation/pending` | bearer token | Returns `[ReconciliationMatch]` with `status=pending_review` |

Stage 1 endpoints live in the extraction half:
[common/extraction/confirmation-workflow.md §API Contract](../extraction/confirmation-workflow.md#6-api-contract--stage-1-endpoints-in-routersstatementspy).

---

## 7. Verification (The Proof) — Stage 2

| Test | File | What It Verifies |
|------|------|-----------------|
| `test_AC16_32_3_stage2_queue_returns_all_pending_checks` | `api/test_statements_router.py` | Stage 2 queue returns the complete unresolved blocker set |
| `test_AC19_11_1_stage2_run_queue_filters_by_run_id` | `api/test_statements_router.py` | Run-scoped Stage 2 queue and approval cannot affect another run |
| `test_batch_approve_requires_checks_resolved` | `review/test_review_workflow.py` | Stage 2 batch blocked by open checks (⏳ Planned) |
| `test_journal_entry_created_on_accept` | `review/test_review_workflow.py` | Journal entry only on accepted transition (⏳ Planned) |
| `test_batch_approve_matches_reconciles_referenced_entry` | `api/test_statements_router.py` | Stage 2 batch approval reconciles referenced journal entries |
| `test_batch_approve_matches_creates_missing_entry_once` | `api/test_statements_router.py` | Stage 2 batch approval creates missing journal entries idempotently |

Stage 1 verification lives in the extraction half:
[common/extraction/confirmation-workflow.md §Verification](../extraction/confirmation-workflow.md#7-verification-the-proof--stage-1).

---

## 8. Related SSOT Documents

- [common/extraction/confirmation-workflow.md](../extraction/confirmation-workflow.md) — the parse-confirm (Stage 1) half, and the shared cross-cutting state machine/tolerance/confidence framing
- [reconciliation.md §7](./reconciliation.md) — Stage 1 and Stage 2 detailed state machines
- [common/ledger/readme.md](../ledger/readme.md) — journal entry creation on `accepted`
