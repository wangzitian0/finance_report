# Two-Layer Contract & Flow Test Workflow

> **SSOT Key**: `tdd-transformation`

## Canonical Hierarchy

- **Domain invariants**: Verified directly in each package's backend/frontend test suite and enforced structurally by `tools/check_app_boundary.py`, `tools/check_base_purity.py`, `tools/check_tier_imports.py`, and `tools/check_public_orm_exports.py`.
- **Business user cases**: `common/meta/flows/user_cases_ssot.json` owns the 47 end-to-end `UC-01..UC-47` journeys across backend APIs, frontend routes, and test modules.
- **Documentation boundary**: Never mirror per-test acceptance tables into `docs/project/EPIC-*.md`.

## Proof Semantics & Local Checks

Tests prove real invariants or user-case journeys (`expect(true).toBe(true)`, stubs, and pure `pass` violate testing discipline). Exception infrastructure files are classified in [`docs/project/traceability-exceptions.md`](../../docs/project/traceability-exceptions.md). Coverage floors live in `common/meta/extension/coverage/policy.py`, `apps/backend/pyproject.toml`, and `apps/frontend/vitest.config.ts`.
