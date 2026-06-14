# Router Contract Maturity — Untyped Endpoints

Kickoff of [#1000](https://github.com/wangzitian0/finance_report/issues/1000). Endpoints below declare no `response_model`, so their response contract is absent from the OpenAPI schema. Type them (or document why a status-only handler is intentional) and lower the budget in `audit_router_contracts.py`.

**Untyped endpoints: 12**

| Method | Route | Handler | File:line |
|--------|-------|---------|-----------|
| `DELETE` | `/{account_id}` | `delete_account` | apps/backend/src/routers/accounts.py:240 |
| `DELETE` | `/valuation-snapshots/{snapshot_id}` | `delete_valuation_snapshot` | apps/backend/src/routers/assets.py:186 |
| `POST` | `` | `chat_message` | apps/backend/src/routers/chat.py:37 |
| `DELETE` | `/session/{session_id}` | `delete_session` | apps/backend/src/routers/chat.py:211 |
| `DELETE` | `/{entry_id}` | `delete_journal_entry` | apps/backend/src/routers/journal.py:142 |
| `POST` | `/prices/update` | `update_prices` | apps/backend/src/routers/portfolio.py:864 |
| `GET` | `/package/snapshots/{snapshot_id}/export` | `export_personal_report_package_snapshot` | apps/backend/src/routers/reports.py:1776 |
| `GET` | `/export` | `export_report` | apps/backend/src/routers/reports.py:2058 |
| `GET` | `/{report_type}/snapshots` | `list_report_snapshots` | apps/backend/src/routers/reports.py:2217 |
| `GET` | `/{statement_id}/document` | `get_statement_document` | apps/backend/src/routers/statements.py:536 |
| `DELETE` | `/{statement_id}` | `delete_statement` | apps/backend/src/routers/statements.py:800 |
| `DELETE` | `/{user_id}` | `delete_user` | apps/backend/src/routers/users.py:102 |
