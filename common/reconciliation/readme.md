# `reconciliation` — transaction-to-journal matching (domain package)

> Conforming backend implementation: [`apps/backend/src/reconciliation`](../../apps/backend/src/reconciliation). See also: `common/ledger/readme.md#decimal-rule`, `common/ledger/readme.md#async-tx-boundary`.

## Why & Ubiquitous Language

`reconciliation` links extracted `AtomicTransaction` facts to posted `JournalEntry` rows, scores confidence, and routes ambiguous candidates into review instead of guessing.

- **`ReconciliationMatch`**: canonical disposition head for an `AtomicTransaction` (`journal_match | transfer_leg | reviewed_unmatched`), enforced to one active non-superseded head by partial unique index.
- **`ReconciliationTransferPair` / `ReconciliationTransferPairLeg`**: pairs one `OUT` and one `IN` transfer disposition per pair; decision state survives restarts.
- **`TransferLeg` & `pair_fx_legs` / `discover_fx_conversions`**: pairs cross-currency transfers within rate/date tolerances (`reconciliation/extension/fx_transfer.py`).
- **Consistency checks / anomaly detection**: diagnostic checks (`duplicate`, `transfer_pair`, `anomaly`) run over matched state without altering match scoring.

## Cross-package edges

`extraction` (`AtomicTransaction`), `ledger` (`JournalEntry` linked by ID only, no cross-domain FK), `portfolio`, `pricing` (FX rates), `audit`, `platform` (`WorkflowEvent`).

## Governance

Boundary and tier checks run via `tools/check_app_boundary.py`, `tools/check_base_purity.py`, and `tools/check_tier_imports.py`. Accuracy harness (`apps/backend/tests/reconciliation/test_reconciliation_audit.py`) gates `>= 95%` accuracy, `< 0.5%` FP, `< 2%` FN, `< 10s` runtime.

## Scoring, thresholds, and the state machine

### <a id="thresholds"></a>Thresholds

Defaults live in `apps/backend/src/reconciliation/base/config.py` (`DEFAULT_CONFIG`), loaded from `apps/backend/config/reconciliation.yaml` with env overrides (`RECONCILIATION_AUTO_ACCEPT_THRESHOLD`, `RECONCILIATION_REVIEW_THRESHOLD`, `ENABLE_AI_RECONCILIATION`) via `load_reconciliation_config()` in `apps/backend/src/reconciliation/extension/config.py`, and executed by `execute_matching` in `apps/backend/src/reconciliation/extension/matching.py`. Scoring weights: amount `0.40`, date `0.25`, description `0.20`, business `0.10`, history `0.05`; tolerances: `0.5%` / `$0.10` / `±7 days`. `extension/candidate_policy.py` owns candidate pruning, grouping, and rule scoring; `extension/entry_reads.py` owns the ledger candidate reads; `base/config.py` stays pure.

| Score Range | Action | Transition |
|---|---|---|
| `>= 85` | Auto-Accept | `pending -> auto_accepted` |
| `60-84` | Review Queue | `pending -> pending_review` |
| `< 60` | Unmatched | stays `pending` |

Amount matching compares `AtomicTransaction.currency` against the same-currency bank/cash asset side of candidate entries (`IN` -> debit asset lines, `OUT` -> credit asset lines); `score_description` owns the single normalized `SequenceMatcher` + token-overlap similarity formula (`normalize_text` includes CJK bigrams, and memos compare truncated via `fit_journal_memo`).

### <a id="state-machine"></a>State machine

- Lifecycle: `PENDING_REVIEW -> ACCEPTED / AUTO_ACCEPTED / REJECTED -> SUPERSEDED` (`superseded_by_id` + `version`).
- Rejected suggestions remain historical audit records (`claimed` only by active `PENDING_REVIEW`/`ACCEPTED`/`AUTO_ACCEPTED` rows); transactions reappear in `/reconciliation/unmatched` for manual `POST /reconciliation/unmatched/{txn_id}/reviewed-dispositions` adjudication (`ReviewedDispositionCommand`).
- Transfer legs (`post_named_transfer_legs`) post through `1199` Processing in effective `base_currency` only, storing the AI/user score (`100` when user-confirmed).

### Design constraints

- Always record `score_breakdown` on auto-matches; lock rows on manual review transitions; pre-fetch period candidates via `ReconciliationRepository` (`MatchingContext`) to avoid N+1 queries.
- `list_pending_transactions` excludes transactions already posted from their statement (`posted_statement_source_ids`), while `get_reconciliation_stats` and unscoped `/reconciliation/unmatched` pass `include_pending_stage1=False` (`#2826`, `#2884`).
- Statement reject/retire calls `release_transaction_dispositions` to mark released matches `SUPERSEDED` without deleting audit history or unpairing active pairs silently (`#2888`).

## Two-Stage Review & Balances

### Stage 1 — record-level review

- `/statements/{id}` validates intra-statement balances (`opening_delta <= 0.001` and `closing_delta <= 0.001`), surfaces cross-period `Prior Gap (3198)` diagnostics (`abs(delta) <= 0.10`), and transitions `PARSED / pending_review -> APPROVED` or `REJECTED`.

### <a id="per-currency-balance-reconciliation"></a>Per-currency balance reconciliation

Multi-currency statements store `currency_balances` (`[{currency, opening, closing}]`). `validate_balance_per_currency` checks each currency independently (`opening_ccy + IN_ccy - OUT_ccy == closing_ccy` within tolerance) and never sums across currencies.

### <a id="fx-cross-currency-transfer-pairing"></a>FX / cross-currency transfer pairing

Two `TransferLeg` candidates pair via `pair_fx_legs` / `discover_fx_conversions` iff: same `user_id`, opposite direction (`OUT` vs `IN`), within time window (default 2 days), and implied rate `amount_from / amount_to` within relative tolerance (default `0.5%`) of `pricing.get_exchange_rate`. Unambiguous 1:1 ledger discovery runs conservatively in memory and deduplicates against recorded `fx_conversions`.

### Stage 2 & Reviewed Disposition

- Workbench `/reconciliation` tabs (`?tab=matches|unmatched|review-queue`) default to `unmatched` when items exist (`#2646`).
- `accept_match()` and `POST /reconciliation/matches` share `accept_pending_matches()`: lock matches once, batch-load transactions/entries/anchor links (`~2` SQL per extra match), block if unresolved checks exist in scope (`run_id` when specified), reconcile existing linked journal entries (without fabricating entries/accounts/categories), and return `{approved_count, journal_entries_reconciled}`.
- `reconciliation_match_journal_entries` is the trusted audit link table alongside compatibility `journal_entry_ids`.
- `POST /reconciliation/unmatched/{txn_id}/reviewed-dispositions` requires explicit non-transfer intent, active counter-account, and rationale; it atomically appends `OBSERVATION` + `DECISION` `TraceRecord` rows and posts one entry under an `AtomicTransaction` lock.

## API Endpoints & Key Files

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/statements/{id}/review` | Stage 1 review payload with PDF URL |
| `POST` | `/statements/{id}/approvals` | Stage 1 approve with balance validation |
| `POST` | `/statements/{id}/rejections` | Stage 1 reject + extract rerun |
| `GET` | `/statements/{statement_id}/conflicts` | Duplicate and transfer-pair conflicts |
| `POST` | `/statements/{statement_id}/conflict-resolutions` | Confirm that the listed duplicate and transfer-pair candidates are different transactions; links no rows |
| `GET` | `/reconciliation/review-queue` | Stage 2 queue (`optional run_id`) |
| `POST` | `/reconciliation/consistency-checks/runs` | Run consistency checks |
| `POST` | `/reconciliation/consistency-checks/{id}/resolutions` | Resolve consistency check |
| `GET` | `/reconciliation/consistency-checks` | List/filter consistency checks |
| `GET` | `/reconciliation/transfers/summary` | In-transit processing transfer summary |
| `GET` | `/reconciliation/transfers/pending` | Pending unpaired processing transfer legs |
| `PATCH` | `/reconciliation/matches/{id}` | Accept or reject a single match (`action`) |
| `POST` | `/reconciliation/matches` | Batch accept or reject matches (`action`, optional `run_id`/`min_score`) |

Key files: `src/reconciliation/extension/{matching,candidate_policy,entry_reads,consistency_checks,processing_transfers,review_queue,reviewed_disposition}.py`, `src/routers/{reconciliation,statements}.py`, `apps/frontend/src/components/{review/Stage2ReviewQueue,reconciliation/Workbench}.tsx`.
