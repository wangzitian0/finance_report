# Statement Parsing Model Selection Logging

> **SSOT Key**: `observability-logging` | Related: [observability.md](./observability.md), [common/extraction/readme.md](../extraction/readme.md), [advisor/readme.md](../advisor/readme.md)

## Structured Audit Events & Correlation

Tracks statement upload, parsing, brokerage import, reconciliation runs, journal post/void, auth failures, and rate limits across frontend (`StatementUploader.tsx`) and backend (`observability/`, `routers/{statements,reconciliation,journal}.py`, `extraction/extension/statement_parsing.py`).

Every staging audit event emits `audit_event` with `request_id`, `statement_id` (when scoped), `phase`, `progress` (`5 parse_started`, `20 extraction_started`, `70 extraction_completed`, `80 statement_metadata_persisted`, `90 transactions_persisted`, `100 statement_persisted`), `file_type`, and `file_hash_prefix`:
- `statement.upload.accepted`, `statement.upload.storage_saved`, `statement.upload.storage_failed`
- `statement.parse.enqueued`, `statement.parse.checkpoint`, `statement.parse.extraction_completed`, `statement.parse.completed`, `statement.parse.failed`, `statement.parse.async_task.failed`
- `statement.brokerage_import.{started,completed,failed}` (`BrokerageImportRejectedError` logs at `warning`; others at `error`)
- `reconciliation.run.{started,completed,failed}`, `reconciliation.match.{accepted,batch_accepted}`, `journal.entry.{posted,voided}`, `auth.failure`, `rate_limit.rejected`

## Sensitive Data Policy & Metrics

- **Redaction**: `observability_events.safe_log_fields()` strips credentials, prompts, raw provider bodies, PII, and document bytes; full SQL/FX noise stays at `debug`.
- **Low-cardinality metrics**: `finance.rate_limit.rejected` (`scope`), `finance.async_parse.failure` (`task`, `error_type`), and `finance.invariant.violation` (`kind`, anonymized `institution_class`).
