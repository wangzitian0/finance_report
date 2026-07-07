# Router Contract Maturity — Untyped Endpoints

Kickoff of [#1000](https://github.com/wangzitian0/finance_report/issues/1000). Endpoints below declare no (non-`None`) `response_model`, so their response contract is absent from the OpenAPI schema. Type them (or document why a status-only handler is intentional) and lower the budget (`DEFAULT_MAX_UNTYPED_ENDPOINTS` in `common/testing/audit_router_contracts.py`).

**Untyped endpoints: 0**

The `Route` column is **router-relative** — it excludes the `APIRouter(prefix=...)` (e.g. `/accounts`), so combine it with the router's prefix to get the full path.

| Method | Route (router-relative) | Handler | File:line |
|--------|-------------------------|---------|-----------|
