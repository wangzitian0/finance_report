# Document Extraction SSOT

This document defines the Single Source of Truth for the document extraction feature.

## Overview

The extraction pipeline parses financial statements (PDFs, images, CSVs) with the configured AI provider. PDF/image uploads use `OCR_MODEL` (default `glm-4.6v`) as the OCR-capable model. When `OCR_MODEL` is a separate model from `VISION_MODEL`, the service uses the provider layout parser first, then structures Markdown with `PRIMARY_MODEL` (default `glm-5.1`). When `OCR_MODEL` equals `VISION_MODEL`, the service skips layout parsing and uses the shared vision OCR path directly. Z.AI PDF vision extraction renders the uploaded PDF bytes into a bounded set of in-memory PNG `image_url` payloads; short-lived external URLs are used only when no bytes are available. Inline base64 PDF payloads are reserved for dedicated layout parsing and non-Z.AI compatibility. JSON extraction disables GLM thinking by default and caps output tokens to keep provider latency bounded. Uploads immediately create a `parsing` record, and a background worker updates the statement once parsing completes.

## Upload-First Product Contract

The user-facing input model is upload-first: users provide supported source
documents and exports, and the system converts them into reviewed records before
ledger/report use. Supported upload classes include bank statements, brokerage
statements or settlement notes, CSV exports, ESOP/RSU grant or vesting
documents, property appraisals, insurance or liability statements, and other
future document types registered through the schema and AC workflow.

Extraction owns parsing, source metadata, validation results, and lineage back
to the original file. Downstream automation such as market-data refresh,
portfolio valuation, ESOP schedule presentation, recurring accrual treatment,
and report preparation is delegated to the owning SSOT documents and must not
weaken extraction confidence or balance-validation rules.

## Source Coverage Matrix

Supported source classes, proof levels, review requirements, and traceability
targets are owned by
[`source_coverage_matrix`](./source-coverage-matrix.yaml). This document
explains extraction behavior; source-class changes must land through the matrix
and its EPIC -> AC -> test anchors.

## Data Flow

```mermaid
flowchart TB
    A[Upload PDF/Image/CSV] --> S[Store to Object Storage]
    S --> P[Create PARSING Statement]
    P --> B{File Type}
    B -->|PDF/Image| C["OCR_MODEL OCR path"]
    C --> C2["PRIMARY_MODEL JSON structuring"]
    B -->|CSV| D[Structured Parser]
    C2 --> E[Extract JSON]
    D --> E
    E --> F{Confidence Score}
    F -->|≥85| G[Auto-Accept]
    F -->|60-84| H[Review Queue]
    F -->|<60| I[Manual Entry]
    G --> J[(PostgreSQL)]
    H --> J

    %% EPIC-011 Direct Writes
    F --> K[ODS: UploadedDocument]
    F --> L[DWD: AtomicTransaction]
    F --> N[DWD: StatementSummary]
    K --> M[(PostgreSQL: ODS/DWD)]
    L --> M
    N --> M
```

## Data Models

### Ingestion Writes (EPIC-011)

Ingestion writes the ODS/DWD tables directly. A successful parse persists one
`UploadedDocument` (ODS), the deduplicated `AtomicTransaction` rows (DWD), and a
`StatementSummary` envelope (DWD). `parse_document` returns
`(StatementSummary, list[AtomicTransaction])`. There is no legacy `BankStatement`
write path and no dual-write flag.

**ODS: Raw Documents (`UploadedDocument`)**
- Stores immutable metadata for every uploaded file
- Maps to `DocumentType`: `bank_statement`, `brokerage_statement`, `esop_grant`, `property_appraisal`
- Status tracking: `uploaded` → `processing` → `completed`

**DWD: Atomic Data (`AtomicTransaction`, `AtomicPosition`)**
- Deduplicated via SHA256 hash of core fields
  (`SHA256(user_id|date|amount|direction|description|reference|disambiguator)`).
  The disambiguator is the persisted statement running balance (`balance_after`)
  when the model supplies it, else a per-occurrence `#occurrence_index` fallback
  (`DeduplicationService.calculate_transaction_hash`). Either way two real but
  otherwise-identical transactions stay distinct, while a genuine duplicate
  extraction of the same row collapses onto the existing record. `balance_after`
  is persisted on the row so the hash is reproducible on re-import.
- Per-transaction fields (`txn_date`, `amount`, `direction`, `description`,
  `reference`, `currency`, `balance_after`) live on `AtomicTransaction`. Atomic
  rows are source-pure: they carry no per-transaction status, confidence, or
  raw OCR text.
- `source_documents` (JSONB) tracks lineage (which files contributed this record)
- Immutable once written (except for appending sources)

**DWD: Statement Envelope (`StatementSummary`)**
- One envelope per parsed statement, carrying period, opening/closing balances,
  institution metadata, `file_hash`, and the resolved custody `account_id`.
- Carries review/workflow state: `status`, `stage1_status`,
  `balance_validation_result`, `stage1_reviewed_at`, and `manual_opening_balance`.
- Enums `BankStatementStatus` and `Stage1Status` live in
  `src/models/statement_enums.py`.

When a parsed statement fails balance validation, `balance_validation_result`
must preserve the mismatch note from the Decimal balance check. The statement
must remain reviewable instead of silently hiding the reason it cannot be
trusted for auto-accept.

CSV transaction exports that do not contain source statement opening and closing
balances may use inferred balances for import continuity, but those inferred
balances are not source balance proof. Such parses must remain reviewable and
must not be auto-approved solely because `0 + transactions = inferred closing`.
Their confidence score must not include the balance-validation component because
no source statement balances were provided.

## Confidence Scoring

| Factor | Weight |
|--------|--------|
| Balance validation | 35% |
| Field completeness | 25% |
| Format consistency | 15% |
| Transaction count | 10% |
| Balance progression | 10% |
| Currency consistency | 5% |

**Thresholds**:
- ≥85: Auto-accept only after balance validation, account mapping, and source-period uniqueness pass
- 60-84: Review queue
- <60: Manual entry required

**The ~90 ceiling.** The Balance Progression component (10%) is only awarded
when transactions carry a per-line running `balance_after` chain. Statements
that omit per-line balances (most bank/brokerage PDFs) therefore top out near 90
even when every other factor is perfect. This is an inherent ceiling of the
weighting, not a scoring defect — a higher score requires source data that
exposes the running balance per row.

**Under-extraction guard.** A brokerage statement that yields fewer than
`BROKERAGE_MIN_PLAUSIBLE_TXNS` (2) transactions is a strong under-capture signal
— comparable brokerage statements extract ~10 rows. `compute_confidence_score`
caps such parses at `UNDER_EXTRACTION_SCORE_CAP` (60) so under-capture never
presents as high confidence.

If a high-confidence statement fails any Stage 1 posting guard, the parser must
preserve the extracted statement and transactions, set the statement to parsed
pending review, and expose the guard reason for human correction.

**CSV without source balances never auto-approves.** A CSV export that carries
no source statement opening/closing balances is parsed with
`balance_source = inferred_from_csv_transactions`; the parser forces the
statement to `parsed` (review) with `balance_validated = false`, and the
confidence score excludes the balance-validation component
(`balance_proof_available = false`). Inferred `0 + transactions = closing` is
not balance proof and must not satisfy the auto-approve precondition.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/statements/upload` | Upload document and enqueue parsing (202 Accepted) |
| GET | `/api/statements` | Statement list |
| GET | `/api/statements/{id}` | Get statement with transactions |
| GET | `/api/statements/{id}/transactions` | Transaction list |
| GET | `/api/statements/pending-review` | List parsed items needing review, including legacy parsed rows with no `stage1_status` |
| GET | `/api/accounts/coverage` | Account-level latest confirmed source date, stale status, and statement period continuity issues |
| POST | `/api/statements/{id}/review/approve` | Stage 1 approve with balance-chain validation (canonical) |
| POST | `/api/statements/{id}/review/reject` | Stage 1 reject (canonical) |
| POST | `/api/statements/{id}/approve` | Deprecated compatibility endpoint (proxies to Stage 1 approve) |
| POST | `/api/statements/{id}/reject` | Deprecated compatibility endpoint (proxies to Stage 1 reject) |
| GET | `/api/ai/models` | Configured AI provider model catalog for UI selection |

## Supported Institutions

| Institution | Format | Tier | Notes |
|-------------|--------|------|-------|
| DBS/POSB | PDF | v1 | Singapore bank, GIRO/PayNow |
| CMB (China Merchants Bank) | PDF | v1 | Chinese statements |
| Maybank | PDF | v1 | Malaysia bank |
| Wise | PDF/CSV | v1 | Fintech wallet |
| Brokerage (generic) | PDF/CSV | v1 | Covers Moomoo/IBKR style |
| Insurance (generic) | PDF | v1 | Policy statements |
| OCBC | PDF | Extended | Singapore bank |
| MariBank | PDF | Extended | Digital bank |
| GXS | PDF | Extended | Digital bank |
| Futu (Futu Holdings) | PDF | Extended | HK brokerage |

## Brokerage Position Import

Brokerage extraction feeds Layer 2 `AtomicPosition` through `apps/backend/src/services/brokerage_positions.py`.

### Post-parse routing (intentional difference vs bank statements)

Routing after parsing depends on the document class, on purpose (#981):

- **Bank statements** route via `route_by_threshold(confidence, balance_valid)`: an invalid
  running-balance chain sends them to `uploaded` (manual entry), and high confidence + valid
  balance can auto-approve. **Exception:** CSV exports without source statement balances take the
  inferred-balance path (`has_inferred_csv_balances`), which forces `parsed`/review with
  `balance_valid = False` rather than routing to `uploaded` — so they remain reviewable instead of
  demanding manual entry.
- **Brokerage statements** always route to `parsed` (review) regardless of `balance_valid`,
  because they reconcile via `AtomicPosition` position snapshots rather than a running-balance
  chain — `balance_valid` is not a meaningful gating signal for them.

So the same "balance invalid" outcome lands a (non-CSV) bank statement in `uploaded` but a
brokerage statement in `parsed`. This is by design, not a routing bug. Owner: `ExtractionService`
status selection (`BankStatementStatus.PARSED if is_brokerage_payload else route_by_threshold(...)`).

Parsing priority:
1. Prefer structured `positions`, `holdings`, or `securities` arrays from OCR/LLM output.
2. For Moomoo, recover money-market fund snapshots from subscription rows when no holdings table is available.
3. For Futu, preserve aggregate securities valuation as `FUTU_STOCK_AND_OPTIONS` when the statement only exposes a portfolio total.
4. For Interactive Brokers, consume structured position rows from CSV/PDF extraction payloads.

Import entry points:
- Automatic: successful statement background parsing stores brokerage OCR output in `BankStatement.extraction_metadata`, inspects the structured extraction payload, and imports positions when it contains brokerage `positions`, `holdings`, or `securities`, or when broker detection recognizes the filename/institution/content. The parser calls `BrokeragePositionImportService` with the current statement ID as `source_document_id`.
- Statement-scoped manual: `POST /statements/{id}/brokerage/import` first reads the persisted `BankStatement.extraction_metadata` payload, then falls back to Layer 1 `UploadedDocument.extraction_metadata`, and finally reconstructs cash events from parsed statement transactions. This keeps structured holdings importable even when a brokerage PDF has no bank-style transaction rows.
- Manual/API: `POST /portfolio/brokerage/import` remains available for parsed payload backfills and tests.

Import behavior:
- Creates immutable `AtomicPosition` rows with dedup hash `SHA256(user_id|snapshot_date|asset_identifier|broker)`.
- Re-running the same payload is idempotent and does not create duplicate atomic rows. Automatic background parse import and statement-scoped manual import may overlap for the same statement; the second writer must be counted as an existing atomic position instead of surfacing a duplicate-key 500.
- Brokerage payloads still run entry balance validation. When brokerage cash rows do not reconcile like a bank statement, the statement keeps `balance_validated=false` and a validation note, but routes to `parsed` so position import and asset reporting can continue.
- Reconciliation runs after import to refresh `ManagedPosition` with latest quantity, market value, currency, and snapshot metadata.
- A successful statement-scoped brokerage import must make the imported position visible through `GET /portfolio/holdings` and through the balance sheet's broker market valuation adjustment for the same as-of date.
- Import failures do not discard the parsed statement; the statement remains visible and receives a sanitized `validation_error` noting that brokerage positions were not imported.

## Configuration

Required environment variables:
```bash
AI_PROVIDER=zai
ZAI_API_KEY=<YOUR_ZAI_API_KEY>
AI_BASE_URL=https://api.z.ai/api/coding/paas/v4
AI_CHAT_COMPLETIONS_PATH=/chat/completions
AI_LAYOUT_PARSING_PATH=/layout_parsing
AI_MODEL_CATALOG_SOURCE=configured
PRIMARY_MODEL=glm-5.1
OCR_MODEL=glm-4.6v
VISION_MODEL=glm-4.6v
FALLBACK_MODELS=glm-5-turbo,glm-5
VISION_FALLBACK_MODELS=glm-4.5v
AI_JSON_TIMEOUT_SECONDS=360
AI_JSON_MAX_TOKENS=8192
AI_JSON_DISABLE_THINKING=true
# Optional; off by default. Only set for seed-supporting models (e.g. GLM-5.1) —
# glm-4.6v rejects `seed` with HTTP 400.
AI_JSON_SEED=
AI_DAILY_LIMIT_USD=2
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minio
S3_SECRET_KEY=<YOUR_S3_SECRET_KEY>
S3_BUCKET=statements
S3_REGION=us-east-1
S3_PUBLIC_ENDPOINT=https://s3.zitian.party
S3_PUBLIC_BUCKET=statements
S3_PRESIGN_EXPIRY_SECONDS=300
```

## Parsing Resilience

- **Deterministic decoding**: JSON extraction pins `temperature=0` and
  `do_sample=false` so the same statement decodes reproducibly, keeping
  `balance_validated`, `confidence_score`, and Stage-1 routing from flipping
  between uploads of the same source (#989). An optional fixed request `seed`
  (`AI_JSON_SEED`) can further pin decoding, but it is **off by default**: Z.AI/GLM
  validates request params strictly and `seed` is rejected by some models
  (notably `glm-4.6v`, the default vision/OCR model, returns HTTP 400), so it is
  only safe to set for seed-supporting models such as GLM-5.1.
- **Balance-aware self-consistency re-extract**: when a bank statement's
  running-balance chain fails to reconcile, `_extract_with_balance_retry`
  re-extracts up to `AI_EXTRACT_MAX_ATTEMPTS` times (each with a varied seed —
  configured seed, then +1, +2 …) and keeps the first parse that reconciles before
  routing to `uploaded` (#989 Step B). Brokerage payloads are never retried; if no
  attempt reconciles, the smallest-difference result is kept so routing is
  unchanged. Only failing parses retry, so average cost is bounded; set
  `AI_EXTRACT_MAX_ATTEMPTS=1` to disable.
- **Bucket auto-create**: storage ensures the bucket exists before upload.
- **Orphan cleanup**: if DB persistence fails after upload, the uploaded object is deleted.
- **Periodic orphan sweep**: old statement storage objects without matching DB records are deleted by
  `src/services/storage_sweep.py`; EPIC-003 AC3.8 owns the behavior tests. The grace period
  (`STORAGE_SWEEP_GRACE_PERIOD_HOURS`, default 24h) and run interval
  (`STORAGE_SWEEP_INTERVAL_SECONDS`, default 86400s = daily) are config-driven (issue #356);
  objects younger than the grace period are never deleted.
- **JSON-repair retry**: when a model returns an otherwise-valid object wrapped in
  a markdown code fence or padded with prose, `_extract_json_with_models` performs
  one deterministic repair pass (strip the fence, extract the outermost balanced
  `{...}` object, tracking string literals) before counting a `json_parse` failure.
  This keeps a single malformed-but-recoverable response from rejecting an
  otherwise-valid upload (#982). The repair never invents data and falls back to the
  existing model-chain failure path when no object can be recovered.
- **Stuck job supervisor**: statements stuck in `parsing` longer than 30 minutes are marked `rejected`
  with a validation error so users can retry.
- **Error handler rollback-first**: `_handle_parse_failure` calls `db.rollback()` before re-fetching
  the statement, preventing `PendingRollbackError` cascades from leaving statements stuck.
- **`account_last4` sanitization**: `_sanitize_account_last4()` strips non-alphanumeric characters
  and takes the last 4, preventing `StringDataRightTruncationError` from the VARCHAR(4) column.

## Audit-Failed Case Registry

LLM/OCR is the polymorphic extraction layer for statement formats. The system
does not expand deterministic parser rules just because one provider output or
source layout fails audit. Instead, failed cases are captured in
[`extraction_failed_case_registry`](./extraction-audit-failed-cases.yaml) with
sanitized evidence and one of the approved failure categories:

- `parse_schema_failure`
- `balance_mismatch`
- `low_confidence`
- `ambiguous_account_mapping`
- `model_timeout`
- `provider_shape_changed`
- `unsupported_layout`
- `user_review_rejected`

Real source documents, PII, credentials, and full raw statements must not be
committed. A registry case can drive later prompt tuning, model selection,
review workflow changes, or parser work only after a separate EPIC -> AC -> test
slice is registered.

## Model Selection

- **Default**: Uses `OCR_MODEL=glm-4.6v` on the vision OCR path. Dedicated layout parsing is used only when `OCR_MODEL` differs from `VISION_MODEL`.
- **Upload model field**: optional for PDF/image uploads. If omitted, the OCR-first pipeline is used.
- **Manual override**: a selected image-capable model bypasses the default OCR path and is used directly as a vision chat model. Selecting the shared `OCR_MODEL` uses the same vision OCR model.
- **Retry**: `/api/statements/{id}/retry` accepts a model override; omitted uses OCR-first mode.
- **Catalog**: `/api/ai/models` returns the configured provider catalog for UI dropdowns (filterable by modality).
- **Fallback models (text path)**: `FALLBACK_MODELS` (default `glm-5-turbo,glm-5`) are attempted after OCR text extraction when `PRIMARY_MODEL` fails. These structure OCR Markdown and are text-only.
- **Fallback models (vision path)**: `VISION_FALLBACK_MODELS` (default `glm-4.5v`) are appended after the primary OCR/vision model on the vision/image path, deduplicated and order-preserving. Because the vision request carries image content, these fallbacks must be vision-capable; the text-only `FALLBACK_MODELS` are intentionally **not** reused here. A non-retryable failure of the primary vision model (e.g. a provider `400`) therefore falls through to a secondary vision model before the upload is rejected with `ERR_EXT_003` (#1034). Set `VISION_FALLBACK_MODELS` empty to keep the prior single-model behavior.

## Data Integrity & Typing

To prevent floating-point errors (e.g. `0.1 + 0.2 != 0.3`), the system enforces strict typing:

1.  **AI Output**: The LLM prompt must request a strict JSON object (no markdown or extra text).
2.  **Pydantic Validation**:
    -   **NEVER** use `float` for `amount` fields.
    -   Use `Decimal` with strict mode or string coercion. See: `apps/backend/tests/accounting/test_decimal_safety.py`
    -   Example: `amount: Decimal = Field(decimal_places=2)`
3.  **Database Storage**: Stored as `DECIMAL(18,2)`.
4.  **String Field Sanitization**: AI-extracted string fields with DB length constraints (e.g. `account_last4 VARCHAR(4)`)
    are sanitized before persistence to prevent truncation errors.

> **Float Ban**: Any code found using `float` for currency calculation will be rejected by CI.

## Statement Account Mapping

Automatic journal posting from imported statements must never use a generic
fallback account. Before Stage 1 approval creates posted journal entries, the
statement must resolve to a user-owned asset account by one of these paths:

1. The statement already has an explicit `account_id` selected by the user, and
   that account is user-owned, active, `ASSET`, and in the statement currency.
2. A previous approved statement for the same user has exactly one account
   matching `institution`, `account_last4`, and `currency`.
3. The user explicitly confirms first-upload account creation during Stage 1
   approval; the created asset account is bound to the statement before posted
   journal entries are created.

If no confident match exists, or multiple accounts match the same metadata, the
approval flow must block posting with a clear account-mapping action item. Draft
candidate entries may still use legacy defaults in manual workflows, but posted
entries cannot silently use `Bank - Main`.

Before posted entries are created, the statement must also have a complete
`period_start`/`period_end` source range that does not duplicate or overlap any
approved statement for the same account and currency. High-confidence statements
that fail account or source-period eligibility remain in Stage 1 review instead
of posting automatically.

## Account Coverage Contract

Approved statements are the only source for account-level statement coverage.
`GET /api/accounts/coverage` returns one row per active account/currency pair
with the latest confirmed source date, latest confirmed closing balance, stale
status, and period-level continuity issues.

Coverage checks compare monthly statement periods within each account/currency:

- adjacent monthly statements must have `previous.closing_balance ==
  current.opening_balance` within `BALANCE_TOLERANCE`;
- gaps, overlaps, and duplicate monthly periods are emitted as issues before a
  dashboard can treat the account as complete;
- one-day broker snapshots may override the latest confirmed source date and
  balance without requiring daily statement continuity.

## Files

| File | Purpose |
|------|---------|
| `src/models/statement_enums.py`, `src/models/statement_summary.py` | SQLAlchemy models and enums |
| `src/schemas/extraction.py` | Pydantic schemas |
| `src/services/extraction.py` | Core extraction logic |
| `src/services/validation.py` | Validation and confidence scoring |
| `src/services/storage.py` | Object storage uploads + presigned URLs |
| `src/prompts/statement.py` | Parsing prompt templates |
| `tests/fixtures/*.json` | Parsed test data |
| `tools/generate_fixtures.py` | Parse docs with caching |
| `tools/sanitize_fixtures.py` | Mask PII |
