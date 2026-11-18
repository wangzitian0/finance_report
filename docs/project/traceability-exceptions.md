# Traceability Exceptions

Tests and helpers in this exception policy are test infrastructure (`conftest.py`, `factories.py`, `query_budget.py`, `__init__.py`) or cross-cutting tooling/SSOT contract tests (`tests/tooling/*`, `tests/e2e/conftest.py`, `apps/frontend/src/__tests__/helpers/`). They support shared test execution rather than product user-case coverage in `common/meta/flows/user_cases_ssot.json`.

See [common/testing/ci-cd.md](../../common/testing/ci-cd.md).
