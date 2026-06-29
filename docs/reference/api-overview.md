# Generated Contract References

Finance Report publishes generated references for mutable implementation facts.
Domain SSOT pages explain rationale and link here instead of hand-copying
endpoint or database inventory.

## Published References

| Reference | Source | Use |
|---|---|---|
| [Swagger UI](https://report.zitian.party/api/docs) | Runtime OpenAPI | Field-level request/response details |
| [ReDoc](https://report.zitian.party/api/redoc) | Runtime OpenAPI | Long-form runtime API browsing |
| [Generated API Reference](api.md) | `python tools/generate_api_reference.py` | Static endpoint inventory for GitHub Pages |
| [Generated DB Schema Reference](db-schema.md) | MkDocs hook + `python tools/generate_db_schema_reference.py` | Build-time table, column, enum, index, constraint, and FK inventory |

The production base URL is:

```text
https://report.zitian.party/api
```

## Contract Ownership

Endpoint paths, methods, parameters, request bodies, response schemas, and enum
values are owned by FastAPI OpenAPI and backend schema code. Static Markdown
must not hand-copy those mutable facts.

Use these owners instead:

| Contract | Owner |
|---|---|
| API shape | FastAPI OpenAPI and backend Pydantic schemas |
| Static endpoint inventory | [Generated API Reference](api.md) |
| DB schema inventory | [Generated DB Schema Reference](db-schema.md) |
| DB model rationale and migration guardrails | [Schema SSOT](../ssot/schema.md) |
| Auth flow and token policy | [identity package](../../common/identity/readme.md) |
| Monetary precision rule | [Ledger SSOT](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md#decimal-rule) |
| Database enum naming rule | [Schema SSOT](../ssot/schema.md#enum-naming) |

## Authentication

Authenticated endpoints use JWT bearer auth. Get a token from the login endpoint
shown in the generated reference, then send it as:

```bash
curl -H "Authorization: Bearer <token>" https://report.zitian.party/api/accounts
```

## Local Generation

Regenerate static references after backend API or model changes:

```bash
PYTHONPATH=apps/backend python tools/generate_api_reference.py
cd apps/backend && uv run python ../../tools/generate_db_schema_reference.py
```

MkDocs also generates `db-schema.md` automatically through `docs/hooks.py`. The
file is intentionally gitignored so generated schema inventory does not expand
the repository or PR diff.

Check that generated references are current:

```bash
PYTHONPATH=apps/backend python tools/generate_api_reference.py --check
cd apps/backend && uv run python ../../tools/generate_db_schema_reference.py
cd apps/backend && uv run python ../../tools/generate_db_schema_reference.py --check
```
