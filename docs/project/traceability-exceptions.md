# Traceability Exceptions

Tests and helpers in this exception policy are test infrastructure (`conftest.py`, `factories.py`, `query_budget.py`, `__init__.py`) or cross-cutting tooling/SSOT contract tests (`tests/tooling/*`, `tests/e2e/conftest.py`, `apps/frontend/src/__tests__/helpers/`). They are not counted as product behavior AC proof unless an EPIC or `common/<pkg>/contract.py` roadmap references them directly.

See [common/testing/ci-cd.md](../../common/testing/ci-cd.md) and `common/meta/extension/generate_ac_registry.py`.
