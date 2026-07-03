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

Expected routing behavior remains threshold-based (See: `docs/ssot/reconciliation.md#thresholds`):
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
>
> Migrated ids (each resolves in the contract roadmap):
>
> `AC-extraction.101.1`
> `AC-extraction.101.2`
> `AC-extraction.101.3`
> `AC-extraction.102.1`
> `AC-extraction.102.2`
> `AC-extraction.102.3`
> `AC-extraction.103.1`
> `AC-extraction.103.2`
> `AC-extraction.103.3`
> `AC-extraction.103.4`
> `AC-extraction.103.5`
> `AC-extraction.104.1`
> `AC-extraction.104.2`
> `AC-extraction.104.3`
> `AC-extraction.104.4`
> `AC-extraction.104.5`
> `AC-extraction.104.6`
> `AC-extraction.104.7`
> `AC-extraction.105.1`
> `AC-extraction.105.2`
> `AC-extraction.105.3`
> `AC-extraction.105.4`
> `AC-extraction.106.1`
> `AC-extraction.106.2`
> `AC-extraction.106.3`
> `AC-extraction.107.5`
> `AC-extraction.107.6`
> `AC-extraction.107.7`
> `AC-extraction.107.8`
> `AC-extraction.107.9`
> `AC-extraction.107.10`
> `AC-extraction.107.11`
> `AC-extraction.107.12`
> `AC-extraction.108.1`
> `AC-extraction.108.2`
> `AC-extraction.108.3`
> `AC-extraction.108.4`
> `AC-extraction.108.5`
> `AC-extraction.108.6`
> `AC-extraction.108.7`
> `AC-extraction.108.8`
> `AC-extraction.108.9`
> `AC-extraction.108.10`
> `AC-extraction.108.11`
> `AC-extraction.108.12`
> `AC-extraction.108.13`
> `AC-extraction.109.1`
> `AC-extraction.109.2`
> `AC-extraction.115.1`
> `AC-extraction.115.2`
> `AC-extraction.115.3`
> `AC-extraction.115.4`
> `AC-extraction.115.5`
> `AC-extraction.118.1`
> `AC-extraction.118.2`
> `AC-extraction.119.1`
> `AC-extraction.119.2`
> `AC-extraction.119.3`
> `AC-extraction.119.4`
> `AC-extraction.114.1`
> `AC-extraction.114.2`
> `AC-extraction.114.3`
> `AC-extraction.114.4`
> `AC-extraction.114.5`
> `AC-extraction.114.6`
> `AC-extraction.114.7`
> `AC-extraction.114.8`
> `AC-extraction.114.9`
> `AC-extraction.110.1`
> `AC-extraction.110.2`
> `AC-extraction.110.3`
> `AC-extraction.110.4`
> `AC-extraction.110.5`
> `AC-extraction.110.6`
> `AC-extraction.112.1`
> `AC-extraction.112.2`
> `AC-extraction.112.3`
> `AC-extraction.111.1`
> `AC-extraction.111.2`
> `AC-extraction.113.1`
> `AC-extraction.113.2`
> `AC-extraction.113.3`
> `AC-extraction.121.1`
> `AC-extraction.121.2`
> `AC-extraction.121.3`
> `AC-extraction.121.4`
> `AC-extraction.121.5`
> `AC-extraction.121.6`
> `AC-extraction.122.1`
> `AC-extraction.122.2`
> `AC-extraction.116.1`
> `AC-extraction.116.2`
> `AC-extraction.116.3`
> `AC-extraction.116.4`
> `AC-extraction.116.5`
> `AC-extraction.117.1`
> `AC-extraction.117.2`
> `AC-extraction.117.3`
> `AC-extraction.117.4`
> `AC-extraction.117.5`
> `AC-extraction.117.6`
> `AC-extraction.117.7`
> `AC-extraction.117.8`
> `AC-extraction.117.9`
> `AC-extraction.117.10`
> `AC-extraction.117.11`
> `AC-extraction.117.12`
> `AC-extraction.120.1`
> `AC-extraction.120.2`
> `AC-extraction.120.3`
> `AC-extraction.120.4`
> `AC-extraction.120.5`
> `AC-extraction.120.6`
> `AC-extraction.120.7`
> `AC-extraction.120.8`
> `AC-extraction.123.1`
> `AC-extraction.123.2`
> `AC-extraction.123.3`



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

- All extraction tests pass
- Lint/type checks pass
- PR is ready for review with SSOT + project docs updated

### AC-extraction.111: Recovered Coverage

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.111.1 | Dual-write handles duplicate document hash / IntegrityError without failing. | `test_dual_write_layer2_integrity_error_is_non_fatal` | `extraction/test_extraction_error_paths.py` | P1 |
| AC-extraction.111.2 | Dedup upsert sanitizes malformed source_documents payloads (transaction). | `test_upsert_atomic_transaction_handles_non_list_source_documents` | `extraction/test_deduplication.py` | P1 |

### AC-extraction.113: Extraction Determinism (#989)

The AI vision model is not bit-reproducible and cannot be pinned in CI, but
everything *downstream* of the model response must be. Given identical extracted
model output, `confidence_score`, `status` (routing), `validation_error`, and the
resulting transaction set must be identical on every parse. These ACs pin that
seam so a regression that re-introduces non-determinism (dict/set iteration order,
unstable tie-breaking, unseeded randomness) in the scoring/routing pipeline fails
CI. Model-level reproducibility (the same PDF re-sent to the provider) is a
separate concern owned by the extraction-retry / temperature configuration, not
this gate.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.113.1 | Pure scoring + routing functions return identical results across N runs on the same input. | `test_scoring_and_routing_are_deterministic` | `extraction/test_extraction_determinism.py` | P0 |
| AC-extraction.113.2 | Re-parsing identical model output yields identical confidence/status/validation_error across N parses. | `test_repeated_parse_yields_identical_confidence_status_validation` | `extraction/test_extraction_determinism.py` | P0 |
| AC-extraction.113.3 | Each payload class (bank-valid, bank-balance-invalid, brokerage) routes consistently across N parses. | `test_routing_is_consistent_per_payload_class` | `extraction/test_extraction_determinism.py` | P0 |

### AC-extraction.121: Balance-Mismatch Statement Lifecycle (#1141, folds #1085 + #1087)

A bank statement that parses cleanly but whose running balance does not reconcile
must **not** be parked in `uploaded` (a dead-end that the retry endpoint rejects
and the report-readiness query ignores). It must enter the same reviewable resting
state as a brokerage statement: `PARSED` with `stage1_status=PENDING_REVIEW` and a
`validation_error` describing the mismatch. This makes balance-invalid bank
statements retriable (AC-extraction.121.3), visible to readiness (AC-extraction.121.4), and
deterministic (AC-extraction.121.5). CSV intake with a missing institution must fail
synchronously at upload with HTTP 400 instead of accepting (202) and then
rejecting asynchronously (AC-extraction.121.6).

> **Superseded (EPIC-020 AC20.9.2, #1352).** The #1141 "balance-invalid bank
> statement rests in `PARSED`/review" resting state is **no longer the parse-path
> outcome**: the LLM-LED (event→L2) layer now treats a non-reconciling balance chain as a
> BLOCKING invariant and quarantines the extraction to `REJECTED` with a typed reason
> code (an internally-inconsistent extraction must not persist as trusted financial
> truth). The pure `route_by_threshold` routing function (AC-extraction.121.1) and the
> readiness `PARSED`-counts filter (AC-extraction.121.4) are unchanged — the gate sits above
> them in `parse_document`. AC-extraction.121.2 / AC-extraction.121.5 are updated above to the blocking
> outcome.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.121.1 | `route_by_threshold` routes a balance-invalid bank statement to `PARSED` (review), never `uploaded`, regardless of score. | `test_AC13_21_1_balance_invalid_routes_to_parsed_review` | `accounting/test_validation.py` | P0 |
| AC-extraction.121.2 | _Superseded by AC20.9.2 (#1352)._ A parsed bank statement that fails balance reconciliation is now BLOCKING: it is quarantined to `REJECTED` (not `PARSED`/review) with `stage1_status=REJECTED` and a typed `validation_error` reason code. | `test_AC20_9_2_balance_invalid_parse_is_quarantined` | `extraction/test_extraction_determinism.py` | P0 |
| AC-extraction.121.3 | The retry endpoint accepts a balance-invalid statement at its `PARSED` resting state. | `test_AC13_21_3_retry_accepts_parsed_resting_state` | `api/test_statements_router.py` | P0 |
| AC-extraction.121.4 | Report readiness counts the balance-invalid `PARSED` statement as an available input. | `test_AC13_21_4_readiness_counts_parsed_balance_invalid` | `accounting/test_validation.py` | P1 |
| AC-extraction.121.5 | _Superseded by AC20.9.2 (#1352)._ The same balance-mismatch payload routes deterministically across N parses to the same status — now `REJECTED` (the LLM-LED blocking gate), not `PARSED`. | `test_routing_is_consistent_per_payload_class` | `extraction/test_extraction_determinism.py` | P0 |
| AC-extraction.121.6 | CSV upload with a missing institution fails synchronously with HTTP 400 and an actionable message. | `test_AC13_21_6_csv_missing_institution_rejected_sync` | `api/test_statements_router.py` | P0 |

### AC-extraction.122: Same-Amount Deposit Survives a Page-Boundary Balance Repeat (#1254)

A single bank statement can contain two **genuinely distinct** same-date,
same-amount incoming deposits whose extracted running `balance_after` is
**identical** — this happens when a carried-forward balance row precedes the
first deposit and a brought-forward balance row across a page boundary precedes
the second, so the statement prints the same running balance against both rows.

The confidence-tiered dedup disambiguator (AC11.16) used `balance_after` alone
as the high-confidence key, applying the per-document `occurrence_index` only
when `balance_after` was `null`. When the running balance repeated, the two real
deposits hashed identically and the second collapsed into the first at upsert
time, so only one deposit persisted and the deterministic running-balance chain
diverged by exactly the missing amount (`balance_validated=false`).

The fix folds the per-document `occurrence_index` into the disambiguator **even
when `balance_after` is present**, so two distinct rows at distinct positions in
one parse stay distinct. Recall of genuine cross-document duplicate suppression
is preserved: a re-uploaded statement reproduces the same ordered rows, so each
row keeps the same `(balance_after, occurrence_index)` pair and still collapses.
The fix invents no rows — it only uses the visible per-row balance and position
evidence already extracted.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.122.1 | Two distinct same-date/same-amount/same-direction rows sharing one running `balance_after` hash differently within one document (via `occurrence_index`), while a re-uploaded identical row still collapses across documents. | `test_AC13_22_1_same_balance_distinct_rows_do_not_collapse` | `extraction/test_deduplication.py` | P0 |
| AC-extraction.122.2 | A parsed statement with two same-date/same-amount deposits separated by a carried-forward/brought-forward balance repeat persists both deposits and the running-balance chain reconciles. | `test_AC13_22_2_page_boundary_duplicate_deposit_survives` | `extraction/test_dual_write_layer2.py` | P0 |

### AC-extraction.116: Deterministic Decoding — Request Seed (issue #989)

Complements AC-extraction.113 (downstream determinism). AC-extraction.113 pins everything *after* the
model response; this AC pins the *request* so the model itself decodes
reproducibly: temperature 0 / `do_sample` false, plus an optional fixed `seed`
(`AI_JSON_SEED`) forwarded to the provider. The seed is **off by default**
because Z.AI/GLM validates params strictly and some models (e.g. the default
`glm-4.6v`) reject `seed` with HTTP 400; it is opt-in for seed-supporting models.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.116.1 | A provided seed is forwarded in the streaming request payload | `test_stream_ai_json_forwards_zai_knobs_and_seed()` | `ai/test_ai_streaming.py` | P1 |
| AC-extraction.116.2 | Extraction forwards the configured `ai_json_seed` to the model call | `test_extraction_forwards_configured_seed()` | `extraction/test_seed_determinism.py` | P1 |
| AC-extraction.116.3 | Extraction pins `temperature=0` / `do_sample=False` alongside the seed | `test_extraction_decoding_is_deterministic_by_default()` | `extraction/test_seed_determinism.py` | P1 |
| AC-extraction.116.4 | Empty `AI_JSON_SEED` parses as None (omitted) instead of raising | `test_empty_seed_env_is_treated_as_none()` | `extraction/test_seed_determinism.py` | P1 |
| AC-extraction.116.5 | The seed is off (None) by default so it is never sent to providers that reject it (e.g. glm-4.6v) | `test_seed_is_off_by_default()` | `extraction/test_seed_determinism.py` | P1 |

### AC-extraction.117: Balance-Aware Self-Consistency Re-extract (issue #989 Step B)

Step A (AC-extraction.116) makes a single decode reproducible; this AC adds the
**self-consistency** half. When a bank statement's running-balance chain fails to
reconcile, `_extract_with_balance_retry` re-extracts up to
`AI_EXTRACT_MAX_ATTEMPTS` times — each attempt with a *varied* seed (configured
seed, then +1, +2 …) so retries are different-but-reproducible samples — and keeps
the first parse that reconciles before the statement would route to `uploaded`.
Brokerage payloads are never retried (they reconcile via Layer-2 positions, not a
running-balance chain); if no attempt reconciles, the smallest-difference result is
kept so routing is unchanged. Only failing parses retry, so average cost is bounded.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.117.1 | A reconciling first parse is returned without retry | `test_reconciles_first_attempt_single_call()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.2 | A failing parse is retried and the reconciling result wins | `test_retries_until_reconciles()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.3 | When no attempt reconciles, the smallest-difference result is kept | `test_keeps_best_when_none_reconcile()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.4 | Brokerage payloads are not retried | `test_brokerage_is_not_retried()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.5 | Attempt 0 uses the configured seed; retries vary it (seed+1, seed+2 …) | `test_seed_varies_per_attempt()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.6 | `AI_EXTRACT_MAX_ATTEMPTS=1` keeps single-shot behavior | `test_max_attempts_one_disables_retry()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.7 | A structurally-invalid parse (balance uncomputable, difference 0) does not win "best" over a numerically-close parse | `test_structurally_invalid_parse_does_not_win_as_best()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.8 | If every attempt is structurally invalid, the last parse is returned so `parse_document` reports the failure | `test_all_invalid_returns_last_parse()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.9 | A transient extraction error on a retry attempt keeps the earlier usable parse (no upload regression) | `test_transient_retry_error_keeps_earlier_usable_parse()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.10 | If every attempt raises, the error propagates so the upload fails as in the single-call path | `test_all_attempts_error_reraises()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.11 | A transient error on the first attempt does not abort; a later reconciling attempt is returned | `test_first_attempt_error_then_success_recovers()` | `extraction/test_self_consistency.py` | P1 |
| AC-extraction.117.12 | An error after an earlier usable parse keeps trying remaining attempts; a later reconciling parse still wins | `test_error_mid_run_does_not_skip_remaining_attempts()` | `extraction/test_self_consistency.py` | P1 |

### AC-extraction.120: Running-Balance Chain-Break Detector + Repair-Pass Hook (root [#1140](https://github.com/wangzitian0/finance_report/issues/1140))

Bank-statement **under-extraction**: the per-currency self-check correctly flags
`opening + ΣIN − ΣOUT ≠ closing` when rows are dropped, but recall is the
underlying problem and recall is probabilistic (LLM) — it cannot be turned into a
hard CI gate. This AC delivers the **deterministic, testable** slice around that
soft metric:

- **AC-C1 (detector)** — a pure, `Decimal`-based function walks the ordered
  transactions' running `balance_after` chain and returns the exact index/region
  where `balance_after[i-1] + signed_amount[i] != balance_after[i]` (within
  `BALANCE_TOLERANCE`), pinpointing where a row was missed/misparsed. No floats,
  no model call, fully reproducible.
- **AC-C2 (repair-pass hook)** — orchestration + decision logic keyed off the
  self-check delta: when the balance self-check fails *and* the detector finds a
  break, a region-targeted re-extract is attempted exactly once before
  finalizing. The actual re-extraction is behind an injectable interface so CI
  exercises the trigger logic without a live model; it is a safe no-op when there
  is no detector signal or no repair backend is wired.
- **AC-C3 (regression fixture / corpus)** — a synthetic clean bank-statement shape
  with a deliberately-dropped row, asserting the detector finds the correct break
  index and the repair hook is invoked. A corpus fixture
  (`clean_bank_dropped_row_corpus.json`) also drives the detector + repair hook
  **end-to-end** through `ExtractionService._extract_with_balance_retry` with an
  injected `RegionReExtractor`, proving the live wiring fires (not just the bare
  functions). Actual extraction **recall** stays a tracked **soft** metric — no
  hard CI gate.

Extraction **recall** stays a **soft metric** (tracked, no hard CI gate); the
self-check balance guard and these deterministic seams stay hard-tested.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.120.1 | AC-C1: detector pinpoints the exact break index on a crafted chain with a dropped row | `test_AC13_20_1_detector_finds_break_index_on_dropped_row()` | `extraction/test_chain_break_repair.py` | P1 |
| AC-extraction.120.2 | AC-C1: a clean running-balance chain reports no break | `test_AC13_20_2_clean_chain_reports_no_break()` | `extraction/test_chain_break_repair.py` | P1 |
| AC-extraction.120.3 | AC-C1: detection is Decimal-based and tolerant within `BALANCE_TOLERANCE` (no float drift) | `test_AC13_20_3_detector_is_decimal_tolerant()` | `extraction/test_chain_break_repair.py` | P1 |
| AC-extraction.120.4 | AC-C2: on balance mismatch with a detected break, the repair hook is invoked exactly once | `test_AC13_20_4_repair_hook_invoked_once_on_mismatch()` | `extraction/test_chain_break_repair.py` | P1 |
| AC-extraction.120.5 | AC-C2: a clean/reconciling chain never invokes the repair hook | `test_AC13_20_5_repair_hook_not_invoked_on_clean_chain()` | `extraction/test_chain_break_repair.py` | P1 |
| AC-extraction.120.6 | AC-C2: when no repair backend is injected, the hook is a safe no-op returning the original payload | `test_AC13_20_6_repair_is_safe_noop_without_backend()` | `extraction/test_chain_break_repair.py` | P1 |
| AC-extraction.120.7 | AC-C3: the synthetic dropped-row fixture drives the detector to the correct index and triggers the repair hook | `test_AC13_20_7_regression_fixture_detects_and_repairs()` | `extraction/test_chain_break_repair.py` | P1 |
| AC-extraction.120.8 | AC-C3: the clean-bank dropped-row regression-corpus fixture triggers the chain-break detector + `repair_under_extraction` end-to-end through `ExtractionService._extract_with_balance_retry` with an injected `RegionReExtractor` (recall stays a soft metric) | `test_AC13_20_8_corpus_fixture_triggers_repair_end_to_end()` | `extraction/test_chain_break_repair.py` | P1 |

### AC-extraction.123: User Deletion During In-Flight Parse — Lifecycle Coordination ([#1256](https://github.com/wangzitian0/finance_report/issues/1256))

Deleting a user (`DELETE /users/{id}`) while an async statement parse is still
running caused two distinct, compounding defects:

1. **No lifecycle coordination.** The delete cascaded (`UserOwnedMixin` FK with
   `ON DELETE CASCADE`) with no check for in-flight parses. The background parse
   then wrote uploaded-document lineage for the now-deleted `user_id`, which
   PostgreSQL rejected with an `uploaded_documents.user_id → users.id` FK
   `IntegrityError`.
2. **Original error masked.** The failure handler read `statement.id` off the
   expired ORM row *before* `db.rollback()`; on an already-failed session that
   raises `PendingRollbackError`, masking the real FK error so it never gets
   logged.

**Chosen coordination strategy: 409 when a parse is in flight.** Statement
in-flight state is already queryable (`StatementSummary.status == PARSING`), so
`delete_user()` returns a clear, actionable HTTP 409 if the user has any
statement still parsing — the least-invasive option (no cancellation plumbing,
no waiting on a fire-and-forget/remote task, no terminal-marking race). Defence
in depth: the parse finalization path re-checks user/statement existence before
writing lineage, and the failure handler rolls back before touching ORM
attributes using a plain cached `statement_id`, so a parse that races past the
guard fails gracefully without masking the original error.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC-extraction.123.1 | User deletion is refused with HTTP 409 (actionable message) while the user has a statement in the `PARSING` (in-flight) state; with no in-flight parse the delete still succeeds (204) | `test_AC13_23_1_delete_user_with_in_flight_parse_returns_409()`, `test_AC13_23_1_delete_user_without_in_flight_parse_succeeds()` | `api/test_users_router.py` | P0 |
| AC-extraction.123.2 | Parse-failure lineage write re-checks user existence and skips the FK-violating insert (no `IntegrityError`) when the owning user is gone | `test_AC13_23_2_failed_lineage_skips_when_user_deleted()` | `extraction/test_parse_user_deletion_lifecycle.py` | P0 |
| AC-extraction.123.3 | The failure handler rolls back before reading ORM attributes (cached `statement_id`); the original error is preserved/logged and never masked by `PendingRollbackError` | `test_AC13_23_3_failure_handler_rolls_back_before_reading_orm()`, `test_AC13_23_3_original_error_not_masked()` | `extraction/test_parse_user_deletion_lifecycle.py` | P0 |

## Acceptance Criteria

> **Migrated (2026-07-03, #1421 Stage-2 cutover):** all 118 ACs moved to
> the `extraction` package roadmap in
> [`common/extraction/contract.py`](../../common/extraction/contract.py) as
> `AC-extraction.<group>.<seq>` — this EPIC's rows occupy the reserved
> groups 101–123 (group + 100), per Decision A (standard-preserving move — every AC kept its
> statement, anchored test, and priority; the package tier is LLM-LED with
> per-AC `proof_kind`). This table intentionally holds no rows; the contract
> roadmap is the single source.
>
> Migrated ids (each resolves in the contract roadmap):
>
> `AC-extraction.101.1`
> `AC-extraction.101.2`
> `AC-extraction.101.3`
> `AC-extraction.102.1`
> `AC-extraction.102.2`
> `AC-extraction.102.3`
> `AC-extraction.103.1`
> `AC-extraction.103.2`
> `AC-extraction.103.3`
> `AC-extraction.103.4`
> `AC-extraction.103.5`
> `AC-extraction.104.1`
> `AC-extraction.104.2`
> `AC-extraction.104.3`
> `AC-extraction.104.4`
> `AC-extraction.104.5`
> `AC-extraction.104.6`
> `AC-extraction.104.7`
> `AC-extraction.105.1`
> `AC-extraction.105.2`
> `AC-extraction.105.3`
> `AC-extraction.105.4`
> `AC-extraction.106.1`
> `AC-extraction.106.2`
> `AC-extraction.106.3`
> `AC-extraction.107.5`
> `AC-extraction.107.6`
> `AC-extraction.107.7`
> `AC-extraction.107.8`
> `AC-extraction.107.9`
> `AC-extraction.107.10`
> `AC-extraction.107.11`
> `AC-extraction.107.12`
> `AC-extraction.108.1`
> `AC-extraction.108.2`
> `AC-extraction.108.3`
> `AC-extraction.108.4`
> `AC-extraction.108.5`
> `AC-extraction.108.6`
> `AC-extraction.108.7`
> `AC-extraction.108.8`
> `AC-extraction.108.9`
> `AC-extraction.108.10`
> `AC-extraction.108.11`
> `AC-extraction.108.12`
> `AC-extraction.108.13`
> `AC-extraction.109.1`
> `AC-extraction.109.2`
> `AC-extraction.115.1`
> `AC-extraction.115.2`
> `AC-extraction.115.3`
> `AC-extraction.115.4`
> `AC-extraction.115.5`
> `AC-extraction.118.1`
> `AC-extraction.118.2`
> `AC-extraction.119.1`
> `AC-extraction.119.2`
> `AC-extraction.119.3`
> `AC-extraction.119.4`
> `AC-extraction.114.1`
> `AC-extraction.114.2`
> `AC-extraction.114.3`
> `AC-extraction.114.4`
> `AC-extraction.114.5`
> `AC-extraction.114.6`
> `AC-extraction.114.7`
> `AC-extraction.114.8`
> `AC-extraction.114.9`
> `AC-extraction.110.1`
> `AC-extraction.110.2`
> `AC-extraction.110.3`
> `AC-extraction.110.4`
> `AC-extraction.110.5`
> `AC-extraction.110.6`
> `AC-extraction.112.1`
> `AC-extraction.112.2`
> `AC-extraction.112.3`
> `AC-extraction.111.1`
> `AC-extraction.111.2`
> `AC-extraction.113.1`
> `AC-extraction.113.2`
> `AC-extraction.113.3`
> `AC-extraction.121.1`
> `AC-extraction.121.2`
> `AC-extraction.121.3`
> `AC-extraction.121.4`
> `AC-extraction.121.5`
> `AC-extraction.121.6`
> `AC-extraction.122.1`
> `AC-extraction.122.2`
> `AC-extraction.116.1`
> `AC-extraction.116.2`
> `AC-extraction.116.3`
> `AC-extraction.116.4`
> `AC-extraction.116.5`
> `AC-extraction.117.1`
> `AC-extraction.117.2`
> `AC-extraction.117.3`
> `AC-extraction.117.4`
> `AC-extraction.117.5`
> `AC-extraction.117.6`
> `AC-extraction.117.7`
> `AC-extraction.117.8`
> `AC-extraction.117.9`
> `AC-extraction.117.10`
> `AC-extraction.117.11`
> `AC-extraction.117.12`
> `AC-extraction.120.1`
> `AC-extraction.120.2`
> `AC-extraction.120.3`
> `AC-extraction.120.4`
> `AC-extraction.120.5`
> `AC-extraction.120.6`
> `AC-extraction.120.7`
> `AC-extraction.120.8`
> `AC-extraction.123.1`
> `AC-extraction.123.2`
> `AC-extraction.123.3`
