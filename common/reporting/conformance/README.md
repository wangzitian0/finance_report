# Reporting API response conformance vectors (#1827)

`vectors.json` is the **backend-owned wire contract** for the reporting API
responses the frontend consumes — the #1167 conformance-vector pattern
(`common/audit/*/conformance/`) extended from value semantics to API response
payloads. It is language-neutral data, consumed at **test time only**.

## The rule

| Side | Consumer |
|------|----------|
| Backend (owner) | `apps/backend/tests/schemas/test_api_response_vectors.py` recomputes each endpoint's serialized response from fixed inputs and compares it to this file |
| Frontend | `apps/frontend/src/__tests__/fixtures/apiVectors.ts` loads this exact file as the mock data for the corresponding page tests |

A backend serializer change without regeneration reds the backend drift test;
a regenerated breaking shape reds the frontend tests that consume it. Either
way the drift is a red gate, never a silent ship (G-contract-reddens).

## Regeneration (never hand-edit)

```bash
apps/backend/.venv/bin/python tools/api_response_vectors.py
```

All values are sanitized placeholders (fixed UUIDs, `Vector *` names). Real
financial data is forbidden here.

## Endpoints vectored

- `balance_sheet` — `GET /api/reports/balance-sheet` (`BalanceSheetResponse`)
