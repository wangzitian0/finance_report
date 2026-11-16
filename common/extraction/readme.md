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
- Background classification runs asynchronously as a `classify` `StatementRun` (180s phase deadline; at most 50 rows/batch, 4 parallel batches) with separate sessions per phase so no DB transaction or policy lock is held across LLM calls (`#3028`).

## Upload-First Product Contract

- Bank and brokerage statements are `supported`; CSV exports, ESOP/RSU, property, liability, and manual records are `manual_trusted`; settlement notes are `gap`.

## SourceCapability Registry

- Source support status and `@ac_proof` traceability map from [`source_capability.py`](../../apps/backend/src/extraction/base/source_capability.py).

## Data Models

- **Vocabulary** (`src/extraction/base/source_vocabulary.py`): `DocumentType`, `DocumentStatus`, `TransactionDirection`, `RuleType`, `ClassificationStatus`, `BankStatementStatus`, `Stage1Status`.
- **ODS (`UploadedDocument`) & DWD (`AtomicTransaction`, `AtomicPosition`, `StatementSummary`)**: immutable atomic facts keyed by custody scope (`AtomicTransactionIdentity`) and per-currency balance containers (`currency_balances` reconciled independently via [per-currency balance reconciliation](../reconciliation/readme.md#per-currency-balance-reconciliation)).
- **Reviewed envelope (`ReviewedStatementEnvelope`)**: append-only `POST /api/statements/{id}/review/envelope` decision filling absent custody/currency/period/balance facts without mutating source extractions.
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
| `POST` | `/api/statements/upload` | Upload document and enqueue extract run (`202`) |
| `GET` | `/api/statements` | List statements with fixed SQL budget (empty nested transactions) |
| `GET` | `/api/statements/{id}` | Statement detail with transactions |
| `GET` | `/api/statements/pending-review` | Statements awaiting Stage 1 review |
| `GET` | `/api/accounts/coverage` | Per-account confirmed source date and continuity issues |
| `POST` | `/api/statements/{id}/review/envelope` | Version-pinned reviewer envelope confirmation |
| `POST` | `/api/statements/{id}/review/approve` | Stage 1 approve + balance-chain check + posting |
| `POST` | `/api/statements/{id}/review/reject` | Stage 1 reject (optionally triggers extract rerun) |
| `POST`/`GET` | `/api/statements/{id}/runs` | Start or list `StatementRun` attempts (`extract` / `classify`) |
| `POST` | `/api/statements/{id}/brokerage/import` | Manual statement-scoped brokerage position import |
| `GET` | `/api/llm/catalog` | Configured provider model catalog (supersedes retired `/api/ai/models`) |

## Brokerage Position Import

- Broker documents route to `BROKERAGE_POSITIONS_PROMPT` before the model call and import into `AtomicPosition` + `ManagedPosition` via `BrokeragePositionImportService`.
- Import failures persist non-destructively in `extraction_metadata["brokerage_import_failure"]` (`record_brokerage_import_failure` / `clear_brokerage_import_failure`). Missing snapshot dates or out-of-range/non-ISO-4217 values return HTTP 422 (`brokerage_snapshot_date_missing`, `brokerage_position_out_of_range`).

## Statement run

- `statement_runs` tracks every `extract` and `classify` attempt (`requested -> running -> succeeded | failed | cancelled`) with partial unique index `uq_statement_runs_one_active` guaranteeing at most one active run per statement (`409` with `active_run_id`).
- State transitions go exclusively through conditional updates in `extension/statement_runs.py`, emitting `TraceRecord` events under `statement:{statement_id}:run:{run_id}`.
- `start_user_extract_run` locks the statement `FOR NO KEY UPDATE` (`key_share=True`) before inserting a run; `reap_stale_runs` fails stale `requested` (`claim_timeout`) or `running` (`heartbeat_lost`) runs after 5 minutes.
- High-confidence statements (`auto_approve_candidate=True`) approve and finish their `classify` run atomically in one transaction (`approve_statement_workflow(..., ignore_run_id=run_id)`).
- `RunHints` accepts `<= 20` keywords (`<= 64` chars) and a `<= 500`-char note, hashed into `prompt_digest` alongside `model` and `PARSING_PROMPT_TEMPLATE_VERSION`.

## Planner Statistics Refresh After Approval

- After committing an approval, `approve_statement_workflow` schedules non-blocking background `ANALYZE` on ledger/extraction/reconciliation tables (`timeout` guarded, skipped in `testing` / non-Postgres).

## Account Coverage Contract

- `GET /api/accounts/coverage` checks adjacent approved statements per account/currency against `BALANCE_TOLERANCE` (`0.001`) and `CROSS_PERIOD_GAP_PLUG_TOLERANCE` (`0.10`), surfacing `GAP`, `OVERLAP`, or `DUPLICATE` issues while exempting zero-change gaps (`|delta| <= 0.10`) and daily broker snapshots.
