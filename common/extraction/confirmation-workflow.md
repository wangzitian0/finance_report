# Confirmation Workflow — Parse-Confirm (Stage 1)

> **SSOT Key**: `confirmation-workflow` (parse-confirm half)
> **Authority**: This document defines the `pending_review` state machine used
> across both Stage 1 (statement import, owned here by `extraction`) and
> Stage 2 (reconciliation, owned by
> [`common/reconciliation/confirmation-workflow.md`](../reconciliation/confirmation-workflow.md#state-machine))
> of the review pipeline. The two halves split at #1822 (SSOT dissolution);
> this half is the canonical home for the shared cross-cutting framing (the
> full state-machine diagram, tolerance reference, and confidence/promotion
> model) plus everything Stage-1-specific. See the reconciliation half for
> Stage 2 transitions, endpoints, and tests.
> **Cross-references**: [reconciliation.md](../reconciliation/reconciliation.md) §7 (Stage 1 & Stage 2 state machines), [schema.md](../meta/schema.md), [common/extraction/readme.md](./readme.md)

---

## 1. Source of Truth

| Concern | Location |
|---------|----------|
| `Stage1Status` enum | `apps/backend/src/extraction/orm/statement_enums.py` (enum); `apps/backend/src/extraction/orm/statement_summary.py` — `StatementSummary.stage1_status` (nullable; `None` at upload, set during review workflow) |
| `Stage2Status` on match | `apps/backend/src/reconciliation/orm/reconciliation.py` — `ReconciliationMatch.status` (see the reconciliation half) |
| `pending_review` usage | `apps/backend/src/routers/statements.py`, `apps/backend/src/routers/reconciliation.py` |
| Balance-chain validation | `apps/backend/src/extraction/extension/statement_validation.py` |
| Consistency checks | `apps/backend/src/reconciliation/extension/consistency_checks.py` (see the reconciliation half) |

---

## 2. The `pending_review` Status

`pending_review` appears on **two distinct model fields**. They are NOT the same concept.

| Field | Model | Meaning |
|-------|-------|---------|
| `StatementSummary.stage1_status = PENDING_REVIEW` | Stage 1 | Parsed statement awaiting user visual verification against the original PDF (**nullable** — `None` after upload; set to `PENDING_REVIEW` when review is triggered) |
| `ReconciliationMatch.status = PENDING_REVIEW` | Stage 2 | Reconciliation match scoring 60–84 pts, requiring human decision before journal entry creation (see the reconciliation half) |

Both use the string value `"pending_review"` by convention, but the state machines they live in are independent.

---

## 3. <a id="state-machine"></a>Cross-Cutting State Machine

The following diagram shows how a bank statement travels from upload through to posted journal entries. This diagram is canonical here (Stage 1 is the entry point of the flow); the reconciliation half's Stage 2 Transitions table is the detailed continuation.

```
                 ┌─────────────────────────────────────────────────────┐
                 │                  STAGE 1 (Record-Level)              │
                 │                                                       │
  Upload         │  StatementSummary.stage1_status                       │
  ──────►  parsed│                                                       │
                 │   score ≥ 85 + guards ──► approved ─────────────────►│──► Stage 2 queue
                 │         │                                             │
                 │   pending_review ──► approved ──────────────────────►│
                 │         │                                             │
                 │         └──► rejected ──► re-parse (loop)            │
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
| `rejected` | re-parse triggered | `pending_review` | — |

Stage 2 Transitions live in the reconciliation half:
[common/reconciliation/confirmation-workflow.md §Stage 2 Transitions](../reconciliation/confirmation-workflow.md#stage-2-transitions).

---

## 4. Design Constraints

### DO
- ✅ Always pass `user_id` to service methods that mutate `pending_review` state (ownership check)
- ✅ Validate both opening and closing balance-chain checks (0.001 USD tolerance) before advancing Stage 1
- ✅ Treat `/review/edit` as unsupported: it returns HTTP 400. To change extracted data, reject and re-parse instead of editing in place
- ✅ Block Stage 1 approve when unresolved duplicate or transfer-pair candidates remain on the statement
- ✅ Require confirmed account mapping and source-period uniqueness before Stage 1 auto-posting
- ✅ Resolve all consistency checks in the active Stage 2 scope before batch approval
- ✅ Create journal entry only on `accepted` transition (never on `pending_review`)
- ✅ Emit an audit log entry on every state transition

### DO NOT
- ❌ Combine Stage 1 status and Stage 2 status into a single field — they are independent
- ❌ Create journal entries from `pending_review` matches
- ❌ Auto-accept Stage 1 statements without opening and closing balance-chain validation
- ❌ Re-introduce in-place edit-and-approve for `/review/edit`; it is unsupported and returns HTTP 400 (reject + re-parse instead)
- ❌ Allow `pending_review → approved` bypass when duplicate/transfer checks are unresolved
- ❌ Hardcode tolerance as `0.10` in Stage 1 — Stage 1 requires `0.001 USD`

---

## 5. Tolerance Reference

| Context | Tolerance | Source |
|---------|-----------|--------|
| Stage 1 balance chain validation | 0.001 USD | `src.audit.promotion.STATEMENT_BALANCE_TOLERANCE` (#930) |
| Stage 2 reconciliation auto-accept / review | 85 / 60 | `src.audit.promotion.RECONCILIATION_AUTO_ACCEPT_SCORE` / `src.audit.promotion.RECONCILIATION_REVIEW_SCORE` (#930) |
| Stage 2 reconciliation match (amount score) | 0.10 USD | AGENTS.md, [reconciliation.md](../reconciliation/reconciliation.md) |
| Reconciliation statistics comparison | 1% | AGENTS.md |

These tolerances are intentionally separate policies. Stage 1 document approval
uses the strict 0.001 USD balance-chain threshold for both the opening continuity
check and the closing transaction-sum check; extraction confidence and Stage 2
matching may use wider scoring tolerances, but they cannot approve a Stage 1
statement with either balance-chain check outside the 0.001 USD tolerance.

### <a id="confidence-tier-rollup"></a>Confidence Tier Rollup (resolves OD4)

Confidence tiers rank by trust: `TRUSTED > HIGH > MEDIUM > LOW`. A line or
aggregate takes the **worst-input tier** — it is only as trustworthy as its
least-trusted contributing fact. This is a defined rollup (a `min`), never an
invented blended score.

- A report line's tier is the worst tier among the journal entries contributing
  to it (tier derived from `source_type` via `confidence_tier`).
- An aggregate (e.g. Net Worth) takes the worst tier across its rated lines.
  Lines with no derivable tier (e.g. market-derived adjustments) are excluded
  from the rollup rather than counted as trusted; the aggregate is `null` when
  nothing is rated.
- Manual valuations are user-supplied, explicitly trusted data and surface as
  `TRUSTED`.

Owned first by the balance sheet (EPIC-005 AC5.18, issue #913). A `% trusted`
proportion is a separate, additive signal (the North-Star metric, EPIC-018
AC18.12), not the per-node badge.

### Promotion Gate (makes confidence load-bearing)

The single deterministic contract that decides whether a versioned fact (see
[schema.md → Append-Only Fact Versioning](../meta/schema.md)) may become authoritative.
Owned by `src.audit.promotion` (EPIC-018 AC18.13, issue #930; relocated from
`services/promotion_gate.py` by #1667):

> **authoritative ⇔ invariants_pass ∧ confidence ≥ τ**

- **Invariants first.** A single failed deterministic invariant (e.g. the
  balance-chain check outside `STATEMENT_BALANCE_TOLERANCE`) → `rejected`,
  regardless of confidence. Strong code is never overridden by a high score.
- **Then confidence.** All invariants pass but confidence below the named
  threshold → `review` (a non-authoritative candidate, escalated for a human).
- **Both pass** → `authoritative`.
- The verdict records the failing invariant and its `delta` vs `tolerance`, so the
  escalation reason is queryable — not a bare status string.

The thresholds in the table above are named constants owned here, not magic
numbers buried in services. AI / Derived versions may only *propose*; the gate
disposes. Wiring each decision site to call the gate (vs. consuming the shared
constants) is incremental; the runtime that *generates* Derived versions or
dispatches escalations is a separate EPIC.

### Correction Feedback Loop (drives the proportion down)

The North-Star metric (EPIC-018 AC18.12) measures the low-confidence proportion;
this is the mechanism that *moves* it. Owned by `extraction/extension/correction_loop.py`
(EPIC-018 AC18.14, issue #931):

- Every human correction that overrode an AI proposal is labeled signal, recorded
  append-only in `CorrectionLog`.
- The **corpus** is a projection of that store keyed by the transaction pattern —
  not a sidecar decision table that would drift from the provenance graph.
- A deterministic **held-out replay** builds priors from a train split and grounds
  recurring held-out patterns, so the low-confidence proportion strictly drops
  exactly when corrections recur (and never invents a gain when they do not).

Live grounding of generation, threshold calibration of the promotion gate from the
corpus, and the dispatch runtime are follow-ups.

---

## 6. API Contract — Stage 1 Endpoints (in `routers/statements.py`)

| Endpoint | Input | Side Effect |
|----------|-------|-------------|
| `POST /api/statements/{id}/review/approve` | `statement_id`, bearer token | stage1_status → approved; opening and closing balance-chain validation enforced (≤ 0.001 USD); unresolved duplicate/transfer-pair candidates rejected; queues to Stage 2 |
| `POST /api/statements/{id}/review/reject` | `statement_id`, `reason`, bearer token | stage1_status → rejected; triggers re-parse |
| `POST /api/statements/{id}/review/edit` | `statement_id`, edits, bearer token | Unsupported — returns HTTP 400. In-place edit-and-approve is removed; reject and re-parse to change extracted data |
| `GET /api/statements/pending-review` | bearer token | Returns `[StatementSummary]` where `status=PARSED` and either `stage1_status=PENDING_REVIEW` or `stage1_status` is null for legacy parsed rows |

Stage 2 endpoints live in the reconciliation half:
[common/reconciliation/confirmation-workflow.md §API Contract](../reconciliation/confirmation-workflow.md#6-api-contract--stage-2-endpoints-reconciliation--statements-routers).

---

## 7. Verification (The Proof) — Stage 1

| Test | File | What It Verifies |
|------|------|-----------------|
| `test_validate_balance_chain_within_tolerance` | `review/test_statement_validation.py` | 0.001 USD tolerance passes |
| `test_validate_balance_chain_exceeds_tolerance` | `review/test_statement_validation.py` | 0.0011 USD delta fails |
| `test_ac16_22_7_tolerance_policy_constants_are_intentional` | `review/test_tolerance_policy.py` | Stage 1 and extraction/reconciliation tolerances remain intentionally separate |
| `test_approve_statement_invalid_balance_fails` | `review/test_statement_validation.py` | Approve blocked if balance bad |
| `test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts` | `api/test_statements_router.py` | Stage 1 approve blocked if duplicate/transfer candidates remain |
| `test_stage1_approve_promotes_source_type` | `extraction/test_source_type_promotion.py` | Stage 1 approve raises source_type to user_confirmed (✅ Implemented) |

Stage 2 verification lives in the reconciliation half:
[common/reconciliation/confirmation-workflow.md §Verification](../reconciliation/confirmation-workflow.md#7-verification-the-proof--stage-2).

---

## 8. Related SSOT Documents

- [common/reconciliation/confirmation-workflow.md](../reconciliation/confirmation-workflow.md) — the match-confirm (Stage 2) half
- [reconciliation.md §7](../reconciliation/reconciliation.md) — Stage 1 and Stage 2 detailed state machines
- [schema.md](../meta/schema.md) — data-layer and migration guardrails
- [Generated DB Schema Reference](../../docs/reference/db-schema.md) — current `StatementSummary`, `ReconciliationMatch`, and `ConsistencyCheck` table inventory
- [common/extraction/readme.md](./readme.md) — How parsed statements enter `pending_review` (Stage 1 entry point)
- [common/audit/readme.md](../audit/readme.md#source-type-trust-hierarchy-provenance) — How `source_type` is promoted through the confirmation lifecycle
