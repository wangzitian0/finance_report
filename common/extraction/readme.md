# `extraction` — statement parsing bounded context

> Owned spec for document upload, OCR/LLM parsing, reviewed envelopes, and statement-run orchestration. Conforming implementation: [`apps/backend/src/extraction/`](../../apps/backend/src/extraction/). Audit case registry: [`audit-failed-cases.yaml`](./audit-failed-cases.yaml). See also: `common/ledger/readme.md#decimal-rule`, `common/ledger/readme.md#async-tx-boundary`, `common/reconciliation/readme.md#thresholds`.

## Overview

- PDF/image extraction uses the multimodal role (`MULTIMODAL_MODEL`, defaulted by `infra2_sdk.runtime.llm.LlmSettings`); CSV/text structuring uses `SMALL_MODEL`. No model names are hardcoded here, and there is no fallback model chain.
- Z.AI vision renders PDFs in lazy 5-page batches (`PDF_VISION_MAX_PAGES`), running two-stage metadata+body extraction when page count exceeds 5 and reading native page text first when the text layer prints decimal amounts.

## Statement ingestion application boundary

- `StatementIngestionUseCase` owns load -> extract -> persist -> promote/review -> posting across API and Prefect workers.
- Upload atomically stores object bytes, creates `UploadedDocument` (ODS) keyed by `(user_id, file_hash)` via savepoint race recovery, binds `StatementSummary` (DWD), and enqueues an extract `StatementRun`.
- `DELETE /statements/{id}` retires (`RETIRED`) the statement and releases only transactions no longer owned by an active/approved statement (`release_transaction_dispositions` -> `VOID` entries under user advisory lock) while preserving stored artifacts and audit lineage.

## Extraction Result And Economic Disposition

- `parse_document` emits an immutable `StatementExtractionResult` (`source_type` bank|brokerage, `evidence_type` `transaction_ledger`|`position_snapshot`); re-parsing advances `StatementSummary.current_extraction_result_id` without overwriting history.
- `DispositionPolicy` consumes typed `IntentProposal`, reviewed counter-account, and active reconciliation transfers (`accepted` matches outrank proposals) to produce balanced ledger commands under `StatementDispositionPolicySnapshot`.
- `auto_accept_ai_suggestions` (default enabled under `AUTO_ACCEPT_AI_SUGGESTIONS`) applies score `>= 60` proposals or routes fallback rows to General Income/Expense (`UNCLASSIFIED`), holding ambiguous transfers/investments in suspense; with auto-accept off, rows in `60-84` remain drafts until one-click/manual approval.
- Background classification runs asynchronously as a `classify` `StatementRun` (180s phase deadline; at most 50 rows/batch, 4 parallel batches) with separate sessions per phase so no DB transaction or policy lock is held across LLM calls (`#3028`). A model call happens only inside a `classify` run: the approve and the one-click fill ask no model, and a row without an answer posts to the General account (`#2994`).

## Upload-First Product Contract

- Bank and brokerage statements are `supported`; CSV exports, ESOP/RSU, property, liability, and manual records are `manual_trusted`; settlement notes are `gap`.

## SourceCapability Registry

- Source support status and `@ac_proof` traceability map from [`source_capability.py`](../../apps/backend/src/extraction/base/source_capability.py).

## Data Models

- **Vocabulary** (`src/extraction/base/source_vocabulary.py`): `DocumentType`, `DocumentStatus`, `TransactionDirection`, `RuleType`, `ClassificationStatus`, `BankStatementStatus`, `Stage1Status`.
- **ODS (`UploadedDocument`) & DWD (`AtomicTransaction`, `AtomicPosition`, `StatementSummary`)**: immutable atomic facts keyed by custody scope (`AtomicTransactionIdentity`) and per-currency balance containers (`currency_balances` reconciled independently via [per-currency balance reconciliation](../reconciliation/readme.md#per-currency-balance-reconciliation)).
- **Reviewed envelope (`ReviewedStatementEnvelope`)**: append-only `POST /api/statements/{id}/review-envelopes` decision filling absent custody/currency/period/balance facts without mutating source extractions.
- **Package interface**: `resolve_statement_contribution()` and `list_statement_contributions()` publish `ResolvedStatementContribution` with `TraceDecisionRef` (`authoritative` vs `unproven`) for reporting.

## <a id="confidence-scoring"></a>Confidence Scoring

| Factor | Weight |
|---|---|
| Balance validation | 35% |
| Field completeness | 25% |
| Format consistency | 15% |
| Transaction count | 10% |
| Balance progression | 10% |
| Currency consistency | 5% |

- `>= 85`: eligible for auto-accept only after balance validation, custody mapping, and non-overlapping source period checks pass.
- `60-84` or failed balance validation (including CSVs missing source balances) or brokerage payloads: routed to `parsed` (`pending_review`).
- `< 60` with valid balance: `uploaded` for manual entry.
- Brokerage under-extraction (`< 2` txns) is capped at `UNDER_EXTRACTION_SCORE_CAP` (`60`).

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/statements` | Upload document and enqueue extract run (`202`) |
| `GET` | `/api/statements` | List statements with fixed SQL budget (empty nested transactions) |
| `GET` | `/api/statements/{id}` | Statement detail with transactions |
| `GET` | `/api/statements/pending-review` | Statements awaiting Stage 1 review |
| `GET` | `/api/statements/coverage` | Per-account confirmed source date and continuity issues |
| `GET` | `/api/statements/classification-suggestions` | Pending classification suggestions in 60-84 review band |
| `POST` | `/api/statements/classification-feedback` | Submit accept/reject/edit feedback on a classification suggestion |
| `POST` | `/api/statements/corrections` | Record user transaction category correction for feedback learning |
| `GET` | `/api/statements/correction-loop/replay` | Replay held-out correction corpus effect on confidence metric |
| `POST` | `/api/statements/{id}/review-envelopes` | Version-pinned reviewer envelope confirmation |
| `POST` | `/api/statements/{id}/approvals` | Stage 1 approve + balance-chain check + posting |
| `POST` | `/api/statements/{id}/rejections` | Stage 1 reject (optionally triggers extract rerun) |
| `POST`/`GET` | `/api/statements/{id}/runs` | Start or list `StatementRun` attempts (`extract` / `classify`) |
| `POST` | `/api/statements/{id}/brokerage-imports` | Manual statement-scoped brokerage position import |
| `GET` | `/api/llm/catalog` | Configured provider model catalog (supersedes retired `/api/ai/models`) |

## Brokerage Position Import

- Broker documents route to `BROKERAGE_POSITIONS_PROMPT` before the model call and import into `AtomicPosition` + `ManagedPosition` via `BrokeragePositionImportService`.
- Import failures persist non-destructively in `extraction_metadata["brokerage_import_failure"]` (`record_brokerage_import_failure` / `clear_brokerage_import_failure`). Missing snapshot dates or out-of-range/non-ISO-4217 values return HTTP 422 (`brokerage_snapshot_date_missing`, `brokerage_position_out_of_range`).

## Statement run

- `statement_runs` tracks every `extract` and `classify` attempt (`requested -> running -> succeeded | failed | cancelled`) with partial unique index `uq_statement_runs_one_active` guaranteeing at most one active run per statement (`409` with `active_run_id`).
- State transitions go exclusively through conditional updates in `extension/statement_runs.py`, emitting `TraceRecord` events under `statement:{statement_id}:run:{run_id}`.
- `start_user_extract_run` locks the statement `FOR NO KEY UPDATE` (`key_share=True`) before inserting a run; `reap_stale_runs` fails stale `requested` (`claim_timeout`) or `running` (`heartbeat_lost`) runs after 5 minutes.
- High-confidence statements (`auto_approve_candidate=True`) approve and finish their `classify` run atomically in one transaction (`approve_statement_workflow(..., ignore_run_id=run_id)`).
- `RunHints` accepts `<= 20` keywords (`<= 64` chars) and a `<= 500`-char note, hashed by `run_prompt_digest` into `prompt_digest` with `model` and the template version of the run kind (`PARSING_PROMPT_TEMPLATE_VERSION` or `CLASSIFICATION_PROMPT_TEMPLATE_VERSION`). Every run stores both columns at creation.
- **Classify again with hints (#2994, S4b-1).** `POST /statements/{id}/runs` takes `kind` `extract` or `classify`. A classify run needs a `PARSED` statement (else 400; 409 if the status changed under the lock). It takes no `model` (422). Hints are allowed for every file type, because the model classifies the rows of a CSV too: `hints_apply_to_file_type` is an extraction rule only. `start_user_classify_run` shares `_start_user_run` with `start_user_extract_run`: the statement lock first, then the run insert with the latest run as parent, no status change, no commit. The route commits, then `submit_classify_run` runs `execute_classify_run` as a tracked task of the API process. If the task cannot start, the run fails with `dispatch_failed` (503). If the process dies, the run stays `requested` and the reaper fails it with `claim_timeout` after 5 minutes: the user starts it again.
- **Prompts and hints.** The executor reads the hints of its own run row, after the claim committed. `ask_model` passes them to the proposer only when they are not empty. `prompts/hints.py` holds the header, the JSON encoding (keywords as an array, the note as a string) and the end line, shared by both prompts. Each prompt adds its own purpose line. Extraction keeps the line of S2, so its prompt with hints is byte-identical and `PARSING_PROMPT_TEMPLATE_VERSION` is `1`. Classification says that the hints may decide the category of the rows or descriptions that they name, and never change the catalog, the output schema, the signs or the amounts (`CLASSIFICATION_PROMPT_TEMPLATE_VERSION` is `2`). With empty hints the classification prompt is byte-identical to the prompt before S4b-1. One fingerprint of each prompt is pinned to its version. An answer outside the catalog still counts under `other` and writes no row.
- **Re-ask.** An automatic classify run, and a user run with no hints, ask only rows without an answer. A user classify run (trigger `rerun`) with hints asks again for each row with a model answer. It skips a keyword-rule row, a row that the user decided (`corrected_by_user`, `rejected_by_user`, `accepted_by_user`), a row that the ledger covers (`ledger_covered_txn_ids`: an anchored entry, a legacy entry, an accepted transfer match) and a row whose live answer came from a run of the same statement with the same `prompt_digest`, so a run that failed resumes. A re-ask appends: the batch write inserts the new answer and sets the old one to `SUPERSEDED` with `superseded_by_id`. The key `uq_txn_classification_version` is a partial unique index on `draft` and `applied` rows (migration 0076), so history rows are allowed. A query with no status or with a bound status cannot use a partial index, so `ix_txn_classification_txn_rule` keeps the lookups by row indexed. The batch write takes the policy-rule key, locks the answer rows `FOR UPDATE ORDER BY id`, and reads the decisions and the ledger coverage again. `apply_suggestion_feedback` takes the key before the row, as a correction does. The insert of an answer takes FOR KEY SHARE on the transaction row and on the account, so a poster locks both with FOR NO KEY UPDATE (`submit_reviewed_disposition`, the claim of the reconciliation repository). `settle_drafts_after_posting` locks the drafts and reads them again. The auto-fill of the approve takes the statement lock before it looks for an active run, so a run start waits for the approve or the approve refuses with the run id. A row for which the model returns no answer keeps its old answer; a low-confidence answer is written as the fallback row (AC 141). Rows of other policy versions are left to the sweep.
- **Run id.** Each answer that a run writes, a model answer or a keyword-rule answer, has `run_id` (the UUID of the run) in its tags. The run row holds the hints and the `prompt_digest`, so the id of an answer leads to the hints that produced it. A superseded answer keeps its run id.
- **Not covered.** The `accept` action of `AiFeedback` sets no `accepted_by_user` marker, because no reader needs it today. A feedback on a draft that a re-ask already superseded answers `recorded` and changes nothing. A shutdown of the API process cancels its classify task: the run stays `running` until the reaper fails it with `heartbeat_lost` after 5 minutes. The candidate auto-approve after the last batch has no heartbeat and no deadline of its own. The `timeout=60` of a batch call is a limit for each read of the stream, not a total (UNVERIFIED). The 180 s deadline covers the plan, the rule answers and every batch.
- **Run again panel and 422.** The panel of the statement page offers "Extract again" and "Classify again" for a parsed statement. The default is classify for a CSV and extract otherwise. A 409 with `active_run_id` says that a run is in progress. A 422 body keeps only `loc`, `msg` and `type` of each error: the `input` and `ctx` fields are dropped, and a `msg` can hold validator text.

## Planner Statistics Refresh After Approval

- After committing an approval, `approve_statement_workflow` schedules non-blocking background `ANALYZE` on ledger/extraction/reconciliation tables (`timeout` guarded, skipped in `testing` / non-Postgres).

## Account Coverage Contract

- `GET /api/statements/coverage` checks adjacent approved statements per account/currency against `BALANCE_TOLERANCE` (`0.001`) and `CROSS_PERIOD_GAP_PLUG_TOLERANCE` (`0.10`), surfacing `GAP`, `OVERLAP`, or `DUPLICATE` issues while exempting zero-change gaps (`|delta| <= 0.10`) and daily broker snapshots.
