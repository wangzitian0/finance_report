# Router Contract Maturity — Untyped Endpoints

Kickoff of [#1000](https://github.com/wangzitian0/finance_report/issues/1000). Endpoints below declare no (non-`None`) `response_model`, so their response contract is absent from the OpenAPI schema. Type them (or document why a status-only handler is intentional) and lower the budget (`DEFAULT_MAX_UNTYPED_ENDPOINTS` in `common/testing/audit_router_contracts.py`).

**Untyped endpoints: 9**

The `Route` column is **router-relative** — it excludes the `APIRouter(prefix=...)` (e.g. `/accounts`), so combine it with the router's prefix to get the full path.

| Method | Route (router-relative) | Handler | File:line |
|--------|-------------------------|---------|-----------|
| `DELETE` | `/{account_id}` | `delete_account` | apps/backend/src/routers/accounts.py:238 |
| `DELETE` | `/valuation-snapshots/{snapshot_id}` | `delete_valuation_snapshot` | apps/backend/src/routers/assets.py:238 |
| `POST` | `` | `chat_message` | apps/backend/src/routers/chat.py:43 |
| `DELETE` | `/session/{session_id}` | `delete_session` | apps/backend/src/routers/chat.py:218 |
| `DELETE` | `/{entry_id}` | `delete_journal_entry` | apps/backend/src/routers/journal.py:154 |
| `GET` | `/package/snapshots/{snapshot_id}/export` | `export_personal_report_package_snapshot` | apps/backend/src/routers/reports.py:525 |
| `GET` | `/export` | `export_report` | apps/backend/src/routers/reports.py:805 |
| `GET` | `/{statement_id}/document` | `get_statement_document` | apps/backend/src/routers/statements.py:541 |
| `DELETE` | `/{statement_id}` | `delete_statement` | apps/backend/src/routers/statements.py:689 |
