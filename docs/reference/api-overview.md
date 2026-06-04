# API Overview

Finance Report exposes a FastAPI REST API. The runtime OpenAPI document is the
authoritative API contract.

## Published References

| Reference | Source | Use |
|---|---|---|
| [Swagger UI](https://report.zitian.party/api/docs) | Runtime OpenAPI | Field-level request/response details |
| [ReDoc](https://report.zitian.party/api/redoc) | Runtime OpenAPI | Long-form runtime API browsing |
| [Generated API Reference](api.md) | `python tools/generate_api_reference.py` | Static endpoint inventory for GitHub Pages |

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
| Auth flow and token policy | [Auth SSOT](../ssot/auth.md) |
| Monetary precision rule | [Accounting SSOT](../ssot/accounting.md#decimal-rule) |
| Database enum naming rule | [Schema SSOT](../ssot/schema.md#enum-naming) |

## Authentication

Authenticated endpoints use JWT bearer auth. Get a token from the login endpoint
shown in the generated reference, then send it as:

```bash
curl -H "Authorization: Bearer <token>" https://report.zitian.party/api/accounts
```

## Local Generation

Regenerate the static endpoint inventory after backend API changes:

```bash
PYTHONPATH=apps/backend python tools/generate_api_reference.py
```

Check that the committed page is current:

```bash
PYTHONPATH=apps/backend python tools/generate_api_reference.py --check
```
